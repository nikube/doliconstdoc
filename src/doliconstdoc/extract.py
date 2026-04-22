"""Phase 1: extract constant occurrences.

Strategy: ripgrep first for fast wide coverage, then tree-sitter-php
only on files that contain complex/dynamic patterns.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# ripgrep returns full match text (no group capture in --json output),
# so we use a second Python regex to extract the constant name.
RG_PATTERNS: dict[str, tuple[str, re.Pattern]] = {
    "getDolGlobal": (
        r"""getDolGlobal(?:String|Int|Bool)\s*\(\s*['"][A-Z][A-Z0-9_]*['"]""",
        re.compile(r"""['"]([A-Z][A-Z0-9_]*)['"]"""),
    ),
    "conf_global": (
        r"""\$conf->global->[A-Z][A-Z0-9_]*""",
        re.compile(r"""\$conf->global->([A-Z][A-Z0-9_]*)"""),
    ),
    "set_const": (
        r"""dolibarr_set_const\s*\(\s*\$?\w+\s*,\s*['"][A-Z][A-Z0-9_]*['"]""",
        re.compile(r"""['"]([A-Z][A-Z0-9_]*)['"]"""),
    ),
    "del_const": (
        r"""dolibarr_del_const\s*\(\s*\$?\w+\s*,\s*['"][A-Z][A-Z0-9_]*['"]""",
        re.compile(r"""['"]([A-Z][A-Z0-9_]*)['"]"""),
    ),
}

DYNAMIC_HINT = re.compile(
    r"""getDolGlobal(?:String|Int|Bool)\s*\(\s*(?!['"])"""
)


@dataclass
class Occurrence:
    const_name: str
    file: str
    line: int
    usage_type: str
    context: str


def rg_json_search(pattern: str, root: Path) -> list[dict]:
    cmd = [
        "rg",
        "--pcre2",
        "--json",
        "--type", "php",
        "-e", pattern,
        str(root),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    results = []
    for raw in proc.stdout.splitlines():
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if msg.get("type") == "match":
            results.append(msg["data"])
    return results


def classify_usage(line_text: str, pattern_kind: str) -> str:
    if pattern_kind in ("set_const",):
        return "write"
    if pattern_kind == "del_const":
        return "write"
    if pattern_kind == "conf_global":
        # heuristic: assignment?
        if re.search(r"\$conf->global->\w+\s*=", line_text):
            return "write"
        return "read"
    if pattern_kind == "getDolGlobal":
        # inside an if/condition?
        if re.search(r"\bif\s*\(.*getDolGlobal", line_text):
            return "check"
        if re.search(r"!?empty\s*\(.*getDolGlobal", line_text):
            return "check"
        return "read"
    return "read"


def infer_module(rel_path: str) -> str:
    parts = rel_path.split("/")
    if not parts:
        return ""
    if parts[0] == "htdocs" and len(parts) > 1:
        parts = parts[1:]
    head = parts[0]
    if head in ("core", "main.inc.php", "includes", "install"):
        return "core"
    return head


def normalize_context(file: Path, line_no: int, span: int = 2) -> str:
    """Return ±span lines with a leading ">>> " marker on the match line."""
    try:
        lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    start = max(0, line_no - 1 - span)
    end = min(len(lines), line_no + span)
    out = []
    for idx in range(start, end):
        prefix = ">>> " if idx == line_no - 1 else "    "
        out.append(prefix + lines[idx])
    return "\n".join(out).rstrip()


def context_span_for(usage_type: str) -> int:
    """check/write usages tend to carry the most semantic context; give them more lines."""
    if usage_type in ("check", "write"):
        return 10
    return 3


COMMENT_RE = re.compile(r"^\s*(?://|\*|/\*)")


def nearby_comment(file: Path, line_no: int, span: int = 3) -> str:
    """Return the closest comment line within ±span of the match, if any."""
    try:
        lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    target = line_no - 1
    for offset in range(1, span + 1):
        for idx in (target - offset, target + offset):
            if 0 <= idx < len(lines) and COMMENT_RE.match(lines[idx]):
                return lines[idx].strip()
    return ""


def relpath(file: Path, root: Path) -> str:
    try:
        rel = file.resolve().relative_to(root.resolve())
    except ValueError:
        return str(file)
    return str(rel).replace("\\", "/")


def extract_occurrences(root: Path) -> list[Occurrence]:
    occs: list[Occurrence] = []
    seen = set()
    for kind, (pattern, name_re) in RG_PATTERNS.items():
        for m in rg_json_search(pattern, root):
            path = Path(m["path"]["text"])
            line_no = m["line_number"]
            line_text = m["lines"]["text"].rstrip("\n")
            for sub in m.get("submatches", []):
                full = sub["match"]["text"]
                nm = name_re.search(full)
                if not nm:
                    continue
                name = nm.group(1)
                if not name.isupper() or len(name) < 2:
                    continue
                rel = relpath(path, root)
                key = (name, rel, line_no, kind)
                if key in seen:
                    continue
                seen.add(key)
                utype = classify_usage(line_text, kind)
                occs.append(
                    Occurrence(
                        const_name=name,
                        file=rel,
                        line=line_no,
                        usage_type=utype,
                        context=normalize_context(path, line_no, span=context_span_for(utype)),
                    )
                )
    return occs


# Comments mentioning CONSTANT_NAME (single-line // and # ; multi-line /* … */)
# Ripgrep returns the raw match; we post-parse each line in Python.
COMMENT_SEARCH_PATTERNS = (
    # Single-line: // or #, anything, constant name
    r"""(?://|\#).*\b[A-Z][A-Z0-9_]{2,}\b""",
    # Multi-line-ish: /* anywhere on a line with a constant name
    r"""\*.*\b[A-Z][A-Z0-9_]{2,}\b""",
)
COMMENT_CONST_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")

# Tokens that look like CONSTANT_NAME but are just uppercase noise in comments.
_COMMENT_STOPLIST = {
    "XXX", "TODO", "FIXME", "HACK", "NOTE", "TBD", "WIP", "API", "URL",
    "HTTP", "HTTPS", "SQL", "PHP", "HTML", "CSS", "JSON", "XML", "UTF",
    "DOL", "ROOT", "OK", "KO", "ID",
}


@dataclass
class CommentOcc:
    const_name: str
    file: str
    line: int
    text: str


def extract_comments(root: Path, known_constants: set[str]) -> list[CommentOcc]:
    """Find comments that mention a constant name. Only keep names we already know about.

    This picks up authoritative comments that are NOT on the exact match line and thus
    miss the ±N context window. Example:
        // MAILING_LIMIT_SENDBYCLI may be defined or not (-1=forbidden, 0 or undefined=no limit).
    """
    out: list[CommentOcc] = []
    seen: set[tuple[str, str, int]] = set()
    for pat in COMMENT_SEARCH_PATTERNS:
        for m in rg_json_search(pat, root):
            path = Path(m["path"]["text"])
            line_no = m["line_number"]
            line_text = m["lines"]["text"].rstrip("\n")
            # require actual comment marker so we don't pick up string literals
            stripped = line_text.lstrip()
            if not (stripped.startswith("//") or stripped.startswith("#")
                    or stripped.startswith("*") or stripped.startswith("/*")):
                continue
            names = (set(COMMENT_CONST_RE.findall(line_text)) & known_constants) - _COMMENT_STOPLIST
            if not names:
                continue
            rel = relpath(path, root)
            for nm in names:
                key = (nm, rel, line_no)
                if key in seen:
                    continue
                seen.add(key)
                out.append(CommentOcc(const_name=nm, file=rel, line=line_no,
                                      text=line_text.strip()[:500]))
    return out


# Wiring from conf.php keys into $conf->global->CONST in core/class/conf.class.php.
# Example:
#   if (!empty($this->file->mailing_limit_sendbycli)) {
#       $this->global->MAILING_LIMIT_SENDBYCLI = $this->file->mailing_limit_sendbycli;
CONF_WIRING_RE = re.compile(
    r"""\$this->global->([A-Z][A-Z0-9_]*)\s*=\s*\$this->file->(\w+)"""
)


def extract_conf_wiring(root: Path) -> dict[str, str]:
    """Return {CONST_NAME: conf.php_key} mappings found in conf.class.php."""
    target = root / "htdocs" / "core" / "class" / "conf.class.php"
    if not target.exists():
        # fallback: search anywhere
        for p in root.rglob("conf.class.php"):
            target = p
            break
    if not target.exists():
        return {}
    try:
        txt = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    out: dict[str, str] = {}
    for m in CONF_WIRING_RE.finditer(txt):
        name, key = m.group(1), m.group(2)
        out.setdefault(name, f"$dolibarr_main_{key} (conf.php) → ${{conf->global->{name}}}")
    return out


def dynamic_files(root: Path) -> list[Path]:
    """Files with getDolGlobal* called with a non-literal first arg."""
    cmd = [
        "rg", "--pcre2", "-l", "--type", "php",
        "-e", DYNAMIC_HINT.pattern,
        str(root),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return [Path(p) for p in proc.stdout.splitlines() if p]


def infer_type(name: str, default_value: str | None) -> str:
    if default_value is None:
        # naming heuristics
        if any(s in name for s in ("ENABLE", "DISABLE", "SHOW", "HIDE", "USE_", "ALLOW")):
            return "bool"
        return "string"
    v = default_value.strip()
    if v in ("0", "1"):
        return "bool"
    if v.lstrip("-").isdigit():
        return "int"
    return "string"
