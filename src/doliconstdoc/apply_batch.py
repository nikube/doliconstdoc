"""Merge ENRICH tuples back into the DB.

Input: one or more Python modules each exposing `ENRICH = [(...), ...]`.
Tuple shape (new):
    (name, purpose, description, impact, possible_values,
     hidden_setting, evidence, confidence)
Legacy tuple shape (6 fields, no evidence/confidence) is also accepted.
"""

from __future__ import annotations

import argparse
import datetime
import glob
import importlib.util
import json
import os
from pathlib import Path

from .db import connect


def _load_enrich(path: str):
    spec = importlib.util.spec_from_file_location(
        f"enrich_{os.path.basename(path)}", path
    )
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    assert spec and spec.loader
    spec.loader.exec_module(mod)  # type: ignore
    return mod.ENRICH


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="doliconstdoc.sqlite")
    ap.add_argument("files", nargs="+", help="enrich_*.py files or glob patterns")
    args = ap.parse_args()

    paths = []
    for f in args.files:
        if any(ch in f for ch in "*?["):
            paths.extend(sorted(glob.glob(f)))
        else:
            paths.append(f)

    rows = []
    for p in paths:
        rows.extend(_load_enrich(p))
    print(f"loaded {len(rows)} entries from {len(paths)} files")

    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    conn = connect(args.out)
    missing = []
    for t in rows:
        if len(t) == 6:
            name, purpose, desc, impact, pv, hidden = t
            evidence = None
            confidence = None
        elif len(t) >= 8:
            name, purpose, desc, impact, pv, hidden, evidence, confidence = t[:8]
            if isinstance(evidence, list):
                evidence = json.dumps(evidence, ensure_ascii=False)
        else:
            print(f"  skip malformed tuple: {t[:2]}")
            continue
        # Never overwrite human-reviewed rows (doc_quality=2).
        conn.execute(
            """UPDATE constants SET purpose=?, description=?, impact=?,
                   possible_values=?, hidden_setting=?, doc_quality=1,
                   last_enriched=?, evidence=?, confidence=?
               WHERE name=? AND (doc_quality IS NULL OR doc_quality < 2)""",
            (purpose, desc, impact, pv, int(hidden), now,
             evidence, confidence, name),
        )
        if conn.total_changes == 0:
            missing.append(name)
    conn.commit()
    print(f"updated {len(rows) - len(missing)}/{len(rows)}")
    if missing:
        print("missing:", missing[:20], "..." if len(missing) > 20 else "")


if __name__ == "__main__":
    main()
