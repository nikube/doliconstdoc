"""Build batch files for LLM enrichment agents.

Usage:
    python -m doliconstdoc.dump_batch --out doliconstdoc.sqlite \\
        --names MAILING_LIMIT_SENDBYCLI,XXX \\
        --batch-file /tmp/batch_test.txt

Or, for bulk re-enrichment, select by confidence / doc_quality:
    python -m doliconstdoc.dump_batch --out doliconstdoc.sqlite \\
        --filter "confidence IS NULL OR confidence='low'" \\
        --chunk 50 --dir /tmp
"""

from __future__ import annotations

import argparse
import string
from pathlib import Path

from .db import connect
from .payload import build_payload


def label_for(i: int) -> str:
    if i < 26:
        return string.ascii_lowercase[i]
    return string.ascii_lowercase[i // 26 - 1] + string.ascii_lowercase[i % 26]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="doliconstdoc.sqlite")
    ap.add_argument("--names", help="Comma-separated list of constant names")
    ap.add_argument("--filter", help="SQL WHERE clause on constants (without WHERE)")
    ap.add_argument("--chunk", type=int, default=50)
    ap.add_argument("--dir", default="/tmp", help="Output directory for batch_*.txt")
    ap.add_argument("--batch-file", help="Single-file mode: write all to this path")
    ap.add_argument("--limit", type=int, default=0, help="Cap total constants (0 = no cap)")
    args = ap.parse_args()

    conn = connect(args.out)
    if args.names:
        names = [n.strip() for n in args.names.split(",") if n.strip()]
    elif args.filter:
        sql = f"SELECT name FROM constants WHERE {args.filter}"
        if args.limit:
            sql += f" LIMIT {args.limit}"
        names = [r[0] for r in conn.execute(sql)]
    else:
        names = [r[0] for r in conn.execute("SELECT name FROM constants ORDER BY name")]
        if args.limit:
            names = names[: args.limit]

    if args.batch_file:
        Path(args.batch_file).write_text(
            "\n\n".join(build_payload(conn, n) for n in names)
        )
        print(f"wrote {args.batch_file}  ({len(names)} constants)")
        return

    outdir = Path(args.dir)
    outdir.mkdir(parents=True, exist_ok=True)
    nbatches = 0
    for i in range(0, len(names), args.chunk):
        label = label_for(nbatches)
        path = outdir / f"batch_{label}.txt"
        path.write_text(
            "\n\n".join(build_payload(conn, n) for n in names[i : i + args.chunk])
        )
        nbatches += 1
    print(f"wrote {nbatches} batches of up to {args.chunk} constants into {outdir}/")


if __name__ == "__main__":
    main()
