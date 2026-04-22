"""Minimal CSV export of the constants table.

Three columns:
    name     — constant name
    purpose  — short LLM-generated summary (≤180 chars)
    where    — "conf.php" if a conf_php_wiring is recorded,
               otherwise the deduplicated list of admin/*.php paths
               where the constant can be set (joined by '|'),
               otherwise "hidden".

Usage:
    python3 -m doliconstdoc.exportcsv out.csv
    python3 -m doliconstdoc.exportcsv out.tsv --delimiter $'\\t'
"""

from __future__ import annotations

import argparse
import csv
import sys

from .db import connect


def compute_where(admin_ui_files: str | None, conf_php_wiring: str | None) -> str:
    if conf_php_wiring:
        return "conf.php"
    if admin_ui_files:
        unique = sorted({p for p in admin_ui_files.split("|") if p})
        if unique:
            return "|".join(unique)
    return "hidden"


def main():
    ap = argparse.ArgumentParser(prog="doliconstdoc.exportcsv")
    ap.add_argument("out", help="Output CSV path")
    ap.add_argument("--db", default="doliconstdoc.sqlite",
                    help="SQLite DB path (default: doliconstdoc.sqlite)")
    ap.add_argument("--delimiter", default=",",
                    help="CSV delimiter (default: ',')")
    args = ap.parse_args()

    conn = connect(args.db)
    rows = conn.execute(
        "SELECT name, purpose, admin_ui_files, conf_php_wiring "
        "FROM constants ORDER BY name"
    ).fetchall()

    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=args.delimiter)
        w.writerow(["name", "purpose", "where"])
        for name, purpose, admin_ui, wiring in rows:
            w.writerow([name, purpose or "", compute_where(admin_ui, wiring)])

    print(f"wrote {len(rows)} rows to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
