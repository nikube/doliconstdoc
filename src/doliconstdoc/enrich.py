"""Phase 3: LLM enrichment with batching + prompt caching.

Uses Anthropic SDK. Haiku 4.5 for most constants, Sonnet 4.6 for criticals.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import PROMPT_VERSION, HASH_VERSION
from .hash import content_bundle, content_hash

CRITICAL_PREFIXES = ("MAIN_SECURITY_", "MAIN_FEATURES_LEVEL")
CRITICAL_MIN_FREQ = 50

MODEL_HAIKU = "claude-haiku-4-5-20251001"
MODEL_SONNET = "claude-sonnet-4-6"

BATCH_SIZE = 20
BATCH_MAX_OCCS = 3


@dataclass
class ConstantPayload:
    name: str
    type_: str | None
    default_value: str | None
    module: str | None
    hidden_guess: int
    occurrences: list[tuple[str, int, str, str]]  # file, line, usage, context


def load_payloads(conn: sqlite3.Connection) -> list[ConstantPayload]:
    rows = conn.execute(
        "SELECT name, type, default_value, module, hidden_setting_guess FROM constants"
    ).fetchall()
    out = []
    for name, type_, dv, module, hg in rows:
        occs = conn.execute(
            "SELECT file, line, usage_type, context FROM occurrences "
            "WHERE const_name = ? ORDER BY file, line",
            (name,),
        ).fetchall()
        out.append(
            ConstantPayload(
                name=name,
                type_=type_,
                default_value=dv,
                module=module,
                hidden_guess=hg or 0,
                occurrences=[(f, l, u, c) for (f, l, u, c) in occs],
            )
        )
    return out


def is_critical(p: ConstantPayload) -> bool:
    if any(p.name.startswith(pref) for pref in CRITICAL_PREFIXES):
        return True
    if len(p.occurrences) >= CRITICAL_MIN_FREQ:
        return True
    return False


def is_trivial(p: ConstantPayload) -> bool:
    if is_critical(p):
        return False
    return len(p.occurrences) <= BATCH_MAX_OCCS


def _occ_score(occ: tuple[str, int, str, str]) -> int:
    """Lower = higher priority. admin/* first, then ones with comments, then writes, then rest."""
    f, _l, u, c = occ
    score = 100
    if "/admin/" in f or f.startswith("admin/"):
        score -= 50
    if c and any(line.strip().startswith(("//", "/*", "*")) for line in c.splitlines()):
        score -= 20
    if u in ("write", "check"):
        score -= 10
    return score


def format_occurrences(occs: list[tuple[str, int, str, str]], cap: int = 10) -> str:
    """Rank by score (admin/comment/write first) then cap. Keep the ">>>" marker line."""
    ranked = sorted(occs, key=_occ_score)
    selected = ranked[:cap]
    lines = []
    for f, l, u, c in selected:
        # pick the line marked ">>>" (the actual match); fall back to first non-empty
        match_line = ""
        for ln in (c or "").splitlines():
            if ln.startswith(">>> "):
                match_line = ln[4:].strip()
                break
        if not match_line and c:
            match_line = next((ln.strip() for ln in c.splitlines() if ln.strip()), "")
        lines.append(f"{f}:{l}|{u}|{match_line[:180]}")
    if len(occs) > cap:
        lines.append(f"... (+{len(occs) - cap} more occurrences not shown)")
    return "\n".join(lines)


def render_single(p: ConstantPayload, template: str) -> str:
    return template.format(
        NAME=p.name,
        TYPE=p.type_ or "unknown",
        DEFAULT=p.default_value if p.default_value is not None else "",
        MODULE=p.module or "",
        HIDDEN_GUESS=p.hidden_guess,
        OCCURRENCES=format_occurrences(p.occurrences),
    )


def render_batch(batch: list[ConstantPayload], template: str) -> str:
    items = []
    for p in batch:
        items.append(
            json.dumps(
                {
                    "name": p.name,
                    "type": p.type_ or "unknown",
                    "default": p.default_value or "",
                    "module": p.module or "",
                    "hidden_guess": p.hidden_guess,
                    "occurrences": format_occurrences(p.occurrences, cap=5).split("\n"),
                },
                ensure_ascii=False,
            )
        )
    return template.format(ITEMS="\n".join(items))


def _extract_json(text: str):
    text = text.strip()
    # strip markdown fences if the model added them
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
    return json.loads(text)


def enrich(conn: sqlite3.Connection, prompts_dir: Path, dry_run: bool = False) -> dict:
    if dry_run:
        client = None
    else:
        from anthropic import Anthropic
        client = Anthropic()

    tpl_single = (prompts_dir / "single.txt").read_text(encoding="utf-8")
    tpl_batch = (prompts_dir / "batch.txt").read_text(encoding="utf-8")

    payloads = load_payloads(conn)
    stats = {"triv_batches": 0, "solo_haiku": 0, "solo_sonnet": 0, "cached": 0, "skipped_empty": 0}

    # Build cache check
    def cached_ok(p: ConstantPayload) -> bool:
        bundle = content_bundle(p.name, p.type_, p.default_value, p.module, p.occurrences)
        new_hash = content_hash(bundle)
        row = conn.execute(
            "SELECT content_hash, hash_version, doc_quality FROM constants WHERE name = ?",
            (p.name,),
        ).fetchone()
        if not row:
            return False
        old_hash, old_ver, quality = row
        return old_hash == new_hash and old_ver == HASH_VERSION and (quality or 0) >= 1

    to_process = []
    for p in payloads:
        if not p.occurrences and not p.default_value:
            stats["skipped_empty"] += 1
            continue
        if cached_ok(p):
            stats["cached"] += 1
            continue
        to_process.append(p)

    triviaux = [p for p in to_process if is_trivial(p)]
    solo = [p for p in to_process if not is_trivial(p)]

    # Batch triviaux
    for i in range(0, len(triviaux), BATCH_SIZE):
        batch = triviaux[i : i + BATCH_SIZE]
        if dry_run:
            stats["triv_batches"] += 1
            continue
        prompt = render_batch(batch, tpl_batch)
        resp = client.messages.create(
            model=MODEL_HAIKU,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            items = _extract_json(resp.content[0].text)
        except Exception:
            items = []
        for item in items:
            _save_enrichment(conn, item)
        stats["triv_batches"] += 1
        conn.commit()

    # Solo (Haiku or Sonnet)
    for p in solo:
        critical = is_critical(p)
        model = MODEL_SONNET if critical else MODEL_HAIKU
        if dry_run:
            stats["solo_sonnet" if critical else "solo_haiku"] += 1
            continue
        prompt = render_single(p, tpl_single)
        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            item = _extract_json(resp.content[0].text)
            item["name"] = p.name
            _save_enrichment(conn, item)
        except Exception:
            pass
        stats["solo_sonnet" if critical else "solo_haiku"] += 1
        conn.commit()

    # Update hashes for everything processed (including cached-miss failures)
    for p in payloads:
        bundle = content_bundle(p.name, p.type_, p.default_value, p.module, p.occurrences)
        h = content_hash(bundle)
        conn.execute(
            "UPDATE constants SET content_hash = ?, hash_version = ? WHERE name = ?",
            (h, HASH_VERSION, p.name),
        )
    conn.commit()

    return stats


def _save_enrichment(conn: sqlite3.Connection, item: dict) -> None:
    name = item.get("name")
    if not name:
        return
    pv = item.get("possible_values")
    pv_json = json.dumps(pv, ensure_ascii=False) if pv is not None else None
    conn.execute(
        "UPDATE constants SET purpose = ?, description = ?, impact = ?, "
        "possible_values = ?, hidden_setting = ?, doc_quality = 1, last_enriched = ? "
        "WHERE name = ?",
        (
            item.get("purpose"),
            item.get("description"),
            item.get("impact"),
            pv_json,
            int(bool(item.get("hidden_setting", 0))),
            datetime.now(timezone.utc).isoformat(),
            name,
        ),
    )
