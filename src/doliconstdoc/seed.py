"""Phase 2: parse install/mysql/data/llx_const.sql.

Extract default values and mark hidden_setting_guess heuristically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Tolerant pattern: INSERT INTO llx_const (name, value, type, ...) VALUES ('NAME', 'VAL', 'TYPE', ...);
# Dolibarr writes these with quoted identifiers and sometimes wraps multiple rows.
INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+llx_const\s*\(([^)]+)\)\s*VALUES\s*(.+?);",
    re.IGNORECASE | re.DOTALL,
)

# A VALUES tuple '(...)' — allow quoted strings with escaped quotes.
TUPLE_RE = re.compile(r"\((?:[^()']|'(?:''|[^'])*')+\)")

# Split inside a tuple by commas outside of quotes.
FIELD_RE = re.compile(r"""'((?:''|[^'])*)'|([^,]+)""")


@dataclass
class SeedRow:
    name: str
    value: str | None
    type_: str | None
    note: str | None
    visible: str | None


def _parse_tuple(chunk: str) -> list[str]:
    inner = chunk.strip()[1:-1]
    fields: list[str] = []
    i, n = 0, len(inner)
    cur = []
    in_str = False
    while i < n:
        c = inner[i]
        if in_str:
            if c == "'":
                if i + 1 < n and inner[i + 1] == "'":
                    cur.append("'")
                    i += 2
                    continue
                in_str = False
                i += 1
                continue
            cur.append(c)
            i += 1
            continue
        if c == "'":
            in_str = True
            i += 1
            continue
        if c == ",":
            fields.append("".join(cur).strip())
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    if cur:
        fields.append("".join(cur).strip())
    # strip surrounding quotes left on non-string items (NULL, numbers)
    return fields


def parse_seed(seed_path: Path) -> list[SeedRow]:
    if not seed_path.exists():
        return []
    sql = seed_path.read_text(encoding="utf-8", errors="replace")
    rows: list[SeedRow] = []
    for m in INSERT_RE.finditer(sql):
        cols = [c.strip().strip("`").lower() for c in m.group(1).split(",")]
        values_blob = m.group(2)
        for t in TUPLE_RE.finditer(values_blob):
            fields = _parse_tuple(t.group(0))
            if len(fields) != len(cols):
                continue
            record = dict(zip(cols, fields))
            name = record.get("name", "").strip()
            if not name:
                continue
            rows.append(
                SeedRow(
                    name=name,
                    value=record.get("value"),
                    type_=record.get("type"),
                    note=record.get("note"),
                    visible=record.get("visible"),
                )
            )
    return rows


def guess_hidden(name: str, admin_files: set[str]) -> int:
    """1 if no occurrence in any htdocs/admin/* file, else 0. Rough heuristic."""
    return 0 if admin_files else 1
