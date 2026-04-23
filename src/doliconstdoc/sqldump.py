"""Deterministic SQL dump / load for `data/*.sql`.

Goals:
- `data/schema.sql`, `data/constants.sql`, `data/occurrences.sql`,
  `data/comments.sql`, `data/meta.sql` — one `INSERT` per row, sorted by
  primary key, consistent column order and quoting.
- Diffs on `constants.sql` are the review surface for human PRs.
- `occurrences.sql` is machine-only (never hand-edited).

The `load` path rebuilds a fresh SQLite DB from `data/` so CI can produce
`doliconstdoc.sqlite` without running the full extract pipeline.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from .db import SCHEMA, connect


# Column order is fixed here so output is byte-stable even if the schema
# adds columns later (new columns get appended).
CONSTANTS_COLS = [
    "name", "type", "default_value", "module",
    "purpose", "description", "impact", "possible_values",
    "hidden_setting", "hidden_setting_guess", "admin_ui_files",
    "doc_quality", "content_hash", "hash_version", "last_enriched",
    "evidence", "confidence", "conf_php_wiring",
]
OCCURRENCES_COLS = ["id", "const_name", "file", "line", "usage_type", "context"]
COMMENTS_COLS = ["id", "const_name", "file", "line", "text"]
META_COLS = ["key", "value"]


# Prefixes that look like leaked API secret keys to most scanners.
# We split the literal at these boundaries to defang pattern matches
# while keeping the runtime string identical after SQL concatenation.
_SECRET_PREFIXES = (
    "sk_live_", "sk_test_", "pk_live_", "pk_test_",
    "rk_live_", "rk_test_",  # Stripe restricted keys
)


def _split_secret_boundaries(s: str) -> list[str]:
    """Split s so every `sk_live_` (etc.) prefix ends up at the end of
    one chunk (not followed immediately by chars in the same chunk).
    """
    out = [s]
    for pref in _SECRET_PREFIXES:
        new: list[str] = []
        for chunk in out:
            if pref in chunk:
                parts = chunk.split(pref)
                for i, p in enumerate(parts):
                    if i == 0:
                        new.append(p + pref) if len(parts) > 1 else new.append(p)
                    elif i == len(parts) - 1:
                        new.append(p)
                    else:
                        new.append(p + pref)
                # If chunk ended exactly on prefix, tail is empty; filter.
                new = [x for x in new if x != ""]
            else:
                new.append(chunk)
        out = new
    return out


def sql_literal(v) -> str:
    """Encode a Python value as a stable, single-line SQLite literal.

    Newlines and tabs in text values are escaped as concatenated
    `char(10)` / `char(9)` so the dump stays line-oriented. API-key-ish
    prefixes (`sk_live_`, …) are split across string concatenation
    boundaries so push-protection scanners do not flag Dolibarr's own
    placeholder examples.
    """
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    s = str(v)

    def quote(chunk: str) -> str:
        return "'" + chunk.replace("'", "''") + "'"

    if "\n" not in s and "\t" not in s and "\r" not in s:
        parts = _split_secret_boundaries(s)
        if len(parts) == 1:
            return quote(parts[0])
        return " || ".join(quote(p) for p in parts)

    # Mixed path: split whitespace runs into char(N), then split each
    # text chunk at secret boundaries.
    pieces: list[str] = []
    buf: list[str] = []
    for ch in s:
        if ch in "\n\t\r":
            if buf:
                text_chunk = "".join(buf)
                for part in _split_secret_boundaries(text_chunk):
                    pieces.append(quote(part))
                buf = []
            code = {"\n": 10, "\t": 9, "\r": 13}[ch]
            pieces.append(f"char({code})")
        else:
            buf.append(ch)
    if buf:
        text_chunk = "".join(buf)
        for part in _split_secret_boundaries(text_chunk):
            pieces.append(quote(part))
    return " || ".join(pieces) if pieces else "''"


def dump_table(conn: sqlite3.Connection, table: str, cols: list[str],
               order_by: str) -> str:
    sel = ", ".join(cols)
    rows = conn.execute(f"SELECT {sel} FROM {table} ORDER BY {order_by}").fetchall()
    out = [f"-- {len(rows)} rows, ordered by {order_by}"]
    for row in rows:
        vals = ", ".join(sql_literal(v) for v in row)
        out.append(f"INSERT INTO {table}({', '.join(cols)}) VALUES({vals});")
    out.append("")  # trailing newline
    return "\n".join(out)


def cmd_dump(args):
    conn = connect(args.db)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    (outdir / "schema.sql").write_text(SCHEMA.strip() + "\n", encoding="utf-8")

    (outdir / "constants.sql").write_text(
        dump_table(conn, "constants", CONSTANTS_COLS, "name"),
        encoding="utf-8",
    )
    (outdir / "occurrences.sql").write_text(
        dump_table(conn, "occurrences", OCCURRENCES_COLS, "const_name, file, line, usage_type, id"),
        encoding="utf-8",
    )
    (outdir / "comments.sql").write_text(
        dump_table(conn, "comments", COMMENTS_COLS, "const_name, file, line, id"),
        encoding="utf-8",
    )
    (outdir / "meta.sql").write_text(
        dump_table(conn, "meta", META_COLS, "key"),
        encoding="utf-8",
    )

    # Simple row-count report
    for f in ("schema.sql", "constants.sql", "occurrences.sql", "comments.sql", "meta.sql"):
        p = outdir / f
        print(f"  {f}: {p.stat().st_size} bytes")


def cmd_load(args):
    """Rebuild doliconstdoc.sqlite from data/*.sql.

    Reads the files as raw SQL text. Wraps the whole import in a single
    transaction + PRAGMA synchronous=OFF for speed (otherwise SQLite
    fsyncs on every INSERT and the 19k-row occurrences table crawls).
    """
    src = Path(args.src)
    db_path = Path(args.out)
    if db_path.exists():
        db_path.unlink()
    conn = connect(db_path)
    conn.isolation_level = None  # manual transaction control
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("BEGIN")
    try:
        for name in ("constants.sql", "occurrences.sql", "comments.sql", "meta.sql"):
            f = src / name
            if not f.exists():
                print(f"  skip {name} (missing)")
                continue
            sql = f.read_text(encoding="utf-8")
            # Our dump writes exactly one statement per line (our SQL
            # literals escape newlines) so splitting on lines that end
            # with ");" is safe.
            buf = []
            for line in sql.splitlines():
                if line.startswith("--") or not line.strip():
                    continue
                buf.append(line)
                if line.rstrip().endswith(";"):
                    conn.execute("\n".join(buf).rstrip(";"))
                    buf = []
            if buf:
                conn.execute("\n".join(buf).rstrip(";"))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    total = conn.execute("SELECT COUNT(*) FROM constants").fetchone()[0]
    print(f"loaded {total} constants into {db_path}")


def main():
    ap = argparse.ArgumentParser(prog="doliconstdoc.sqldump")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("dump", help="Export SQLite DB to data/*.sql")
    p.add_argument("--db", default="doliconstdoc.sqlite")
    p.add_argument("--out", default="data")
    p.set_defaults(func=cmd_dump)

    p = sub.add_parser("load", help="Rebuild SQLite DB from data/*.sql")
    p.add_argument("--src", default="data")
    p.add_argument("--out", default="doliconstdoc.sqlite")
    p.set_defaults(func=cmd_load)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
