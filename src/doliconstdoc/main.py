"""CLI orchestrator: extract -> seed -> enrich."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import HASH_VERSION, PROMPT_VERSION
from . import db as dbmod
from .extract import (
    extract_comments,
    extract_conf_wiring,
    extract_occurrences,
    infer_module,
    infer_type,
)
from .seed import parse_seed


def cmd_extract(args):
    root = Path(args.dolibarr).resolve()
    if not (root / "htdocs").exists():
        print(f"ERROR: {root}/htdocs not found", file=sys.stderr)
        return 2
    conn = dbmod.connect(args.out)
    occs = extract_occurrences(root / "htdocs")
    names: dict[str, dict] = {}
    for o in occs:
        d = names.setdefault(o.const_name, {"module_votes": {}, "count": 0})
        d["count"] += 1
        m = infer_module(o.file)
        d["module_votes"][m] = d["module_votes"].get(m, 0) + 1

    for name, info in names.items():
        mod = max(info["module_votes"].items(), key=lambda kv: kv[1])[0] if info["module_votes"] else None
        dbmod.upsert_constant(conn, name, module=mod, type=infer_type(name, None))

    for o in occs:
        dbmod.insert_occurrence(conn, o.const_name, o.file, o.line, o.usage_type, o.context)

    # Admin UI files per constant
    admin = conn.execute(
        "SELECT const_name, GROUP_CONCAT(file, '|') FROM occurrences "
        "WHERE file LIKE '%/admin/%' OR file LIKE 'admin/%' GROUP BY const_name"
    ).fetchall()
    for name, files in admin:
        conn.execute(
            "UPDATE constants SET admin_ui_files = ? WHERE name = ?",
            (files, name),
        )

    # Phase 1b: comments mentioning constants (stored in separate table)
    known = set(names.keys())
    conn.execute("DELETE FROM comments")
    comments = extract_comments(root / "htdocs", known)
    for c in comments:
        dbmod.insert_comment(conn, c.const_name, c.file, c.line, c.text)

    # Phase 1c: conf.php wiring (conf.class.php)
    wiring = extract_conf_wiring(root / "htdocs")
    for const_name, wire in wiring.items():
        conn.execute(
            "UPDATE constants SET conf_php_wiring = ? WHERE name = ?",
            (wire, const_name),
        )

    dbmod.set_meta(conn, "extract_date", datetime.now(timezone.utc).isoformat())
    dbmod.set_meta(conn, "dolibarr_root", str(root))
    dbmod.set_meta(conn, "hash_version", HASH_VERSION)
    dbmod.set_meta(conn, "prompt_version", PROMPT_VERSION)
    conn.commit()
    print(f"constants: {len(names)}  occurrences: {len(occs)}  comments: {len(comments)}  conf_wiring: {len(wiring)}")
    return 0


def cmd_harvest(args):
    """Re-run just the comments + conf.php wiring passes against the current DB."""
    root = Path(args.dolibarr).resolve()
    if not (root / "htdocs").exists():
        print(f"ERROR: {root}/htdocs not found", file=sys.stderr)
        return 2
    conn = dbmod.connect(args.out)
    known = {r[0] for r in conn.execute("SELECT name FROM constants")}
    if not known:
        print("ERROR: no constants in DB; run extract first", file=sys.stderr)
        return 2
    conn.execute("DELETE FROM comments")
    comments = extract_comments(root / "htdocs", known)
    for c in comments:
        dbmod.insert_comment(conn, c.const_name, c.file, c.line, c.text)
    wiring = extract_conf_wiring(root / "htdocs")
    conn.execute("UPDATE constants SET conf_php_wiring = NULL")
    for const_name, wire in wiring.items():
        conn.execute(
            "UPDATE constants SET conf_php_wiring = ? WHERE name = ?",
            (wire, const_name),
        )
    conn.commit()
    print(f"comments: {len(comments)}  conf_wiring: {len(wiring)}")
    return 0


def cmd_seed(args):
    root = Path(args.dolibarr).resolve()
    seed_path = root / "htdocs" / "install" / "mysql" / "data" / "llx_const.sql"
    conn = dbmod.connect(args.out)
    rows = parse_seed(seed_path)
    for r in rows:
        existing = conn.execute(
            "SELECT admin_ui_files FROM constants WHERE name = ?", (r.name,)
        ).fetchone()
        admin_files = existing[0] if existing else None
        hidden_guess = 0 if admin_files else 1
        inferred_type = None
        if r.type_:
            t = r.type_.lower()
            if t in ("chaine", "string"):
                inferred_type = "string"
            elif t in ("yesno",):
                inferred_type = "bool"
            elif t in ("int", "entier"):
                inferred_type = "int"
        dbmod.upsert_constant(
            conn,
            r.name,
            default_value=r.value,
            hidden_setting_guess=hidden_guess,
            **({"type": inferred_type} if inferred_type else {}),
        )
    dbmod.set_meta(conn, "seed_rows", str(len(rows)))
    conn.commit()
    print(f"seed rows: {len(rows)}")
    return 0


def cmd_enrich(args):
    from .enrich import enrich  # lazy: needs anthropic

    conn = dbmod.connect(args.out)
    prompts_dir = Path(__file__).resolve().parent.parent.parent / "prompts"
    stats = enrich(conn, prompts_dir, dry_run=args.dry_run)
    print(stats)
    return 0


def cmd_stats(args):
    conn = dbmod.connect(args.out)
    total = conn.execute("SELECT COUNT(*) FROM constants").fetchone()[0]
    enriched = conn.execute("SELECT COUNT(*) FROM constants WHERE doc_quality >= 1").fetchone()[0]
    occ = conn.execute("SELECT COUNT(*) FROM occurrences").fetchone()[0]
    hidden = conn.execute("SELECT COUNT(*) FROM constants WHERE hidden_setting = 1").fetchone()[0]
    hidden_guess = conn.execute("SELECT COUNT(*) FROM constants WHERE hidden_setting_guess = 1").fetchone()[0]
    comments = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    wiring = conn.execute("SELECT COUNT(*) FROM constants WHERE conf_php_wiring IS NOT NULL").fetchone()[0]
    low_conf = conn.execute("SELECT COUNT(*) FROM constants WHERE confidence='low'").fetchone()[0]
    med_conf = conn.execute("SELECT COUNT(*) FROM constants WHERE confidence='medium'").fetchone()[0]
    high_conf = conn.execute("SELECT COUNT(*) FROM constants WHERE confidence='high'").fetchone()[0]
    print(f"constants: {total}")
    print(f"enriched (q>=1): {enriched}")
    print(f"occurrences: {occ}")
    print(f"comments: {comments}")
    print(f"conf_php wirings: {wiring}")
    print(f"hidden_setting (confirmed): {hidden}")
    print(f"hidden_setting_guess: {hidden_guess}")
    print(f"confidence: high={high_conf} medium={med_conf} low={low_conf}")
    return 0


def main():
    ap = argparse.ArgumentParser(prog="doliconstdoc")
    ap.add_argument("--out", default="doliconstdoc.sqlite")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name, fn in [("extract", cmd_extract), ("seed", cmd_seed), ("harvest", cmd_harvest)]:
        p = sub.add_parser(name)
        p.add_argument("dolibarr", help="Path to Dolibarr source root")
        p.set_defaults(func=fn)

    p = sub.add_parser("enrich")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_enrich)

    p = sub.add_parser("stats")
    p.set_defaults(func=cmd_stats)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
