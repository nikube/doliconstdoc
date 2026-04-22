# DoliConstDoc

SQLite documentation base for every Dolibarr configuration constant
(`getDolGlobalString/Int/Bool`, `$conf->global->X`, `dolibarr_set_const`,
seed SQL, module descriptors, templates). Built for developer + LLM
consumption.

Shipped as a pre-built `.sqlite` attached to each GitHub
[Release](https://github.com/nikube/doliconstdoc/releases). This repository
contains the tooling that produces it.

## Current state

- Built against Dolibarr `develop` (24.0.0-alpha) to track the next stable
  release; the exact source version is recorded in `meta.dolibarr_version`.
- **3180 constants**, 19316 occurrences, 41 seed defaults (from
  `install/mysql/data/llx_const.sql`), 1144 comment lines that literally
  name a known constant.
- **All 3180 enriched** under the v2 prompt (evidence + confidence +
  `conf.php` wiring). Confidence distribution: 1137 high / 843 medium /
  1199 low.
- 1975 `hidden_setting=1` (no `admin/*.php` write occurrence).

## Quickstart — build the DB locally

Requires Python 3.11+, `ripgrep`, and a local Dolibarr checkout.

```bash
pip install -e .

PYTHONPATH=src python3 -m doliconstdoc.main --out doliconstdoc.sqlite extract /path/to/dolibarr
PYTHONPATH=src python3 -m doliconstdoc.main --out doliconstdoc.sqlite seed    /path/to/dolibarr
PYTHONPATH=src python3 -m doliconstdoc.main --out doliconstdoc.sqlite harvest /path/to/dolibarr
PYTHONPATH=src python3 -m doliconstdoc.main --out doliconstdoc.sqlite stats
```

`extract` + `seed` + `harvest` are deterministic. Enrichment is a separate
step (see below) because it calls an LLM.

## Schema

```sql
constants(name PK, type, default_value, module,
          purpose, description, impact, possible_values,
          hidden_setting, hidden_setting_guess, admin_ui_files,
          doc_quality, content_hash, hash_version, last_enriched,
          evidence,        -- JSON list of verbatim citations
          confidence,      -- 'high' | 'medium' | 'low'
          conf_php_wiring) -- $dolibarr_main_* → $conf->global->NAME, if any
occurrences(id, const_name FK, file, line, usage_type, context)
comments(id, const_name FK, file, line, text)   -- //, /*, *, # comments that cite CONST
meta(key PK, value)
```

## Enrichment — LLM-based, treat with care

Enrichment is done by an LLM, which will extrapolate semantics from a
narrow context window when the code alone is ambiguous. **Treat the
generated fields as a starting point, not ground truth — especially the
rows tagged `confidence='low'`.** Three measures reduce the risk:

1. **Extended context**: `extract.py` uses ±10 lines around `check`/`write`
   occurrences, so authoritative comments a few lines above the handler
   land in the payload.
2. **Dedicated `comments` table**: `extract_comments()` greps single-line
   and block comments that literally name a known constant (with a
   stoplist for `XXX`, `TODO`, `API`, …). Always appended to the payload.
3. **`conf.class.php` wiring**: `extract_conf_wiring()` parses
   `$this->global->NAME = $this->file->key` assignments. A constant with a
   wiring line is set only via `conf.php`, not the admin UI; the prompt
   forces the model to state that.

The prompt (`prompts/enrich_v2.txt`) additionally requires:

- `evidence`: list of 1–4 verbatim citations from the payload.
- `confidence ∈ {high, medium, low}` with explicit rules.
- No speculative wording unless tagged `[SPECULATION]`.

### Running enrichment

Two options:

1. **Anthropic API** (`enrich.py`, reference implementation): install
   `anthropic`, set `ANTHROPIC_API_KEY`, run `enrich`. Not exercised by
   CI; approximate cost ~$6–10 on Haiku + Sonnet for 3180 constants.
2. **In-session via Claude Code subagents** (the path actually used to
   produce the current DB): dump batches, spawn parallel `sonnet` agents
   against `prompts/enrich_v2.txt`, merge their output.

```bash
# dump batches of 50 for constants matching a filter:
PYTHONPATH=src python3 -m doliconstdoc.dump_batch \
  --filter "confidence IS NULL OR confidence='low'" --chunk 50 --dir /tmp

# … run N parallel subagents writing /tmp/enrich_<label>.py …

# merge:
PYTHONPATH=src python3 -m doliconstdoc.apply_batch /tmp/enrich_*.py
```

## Re-run behavior

- `extract` + `seed` + `harvest` repopulate from scratch.
- `enrich` (API path) computes a per-constant `content_hash` and skips
  constants whose bundle is unchanged.
- Bumping `HASH_VERSION` in `src/doliconstdoc/__init__.py` invalidates the
  cache globally — useful after prompt changes.

## Querying

```bash
python3 -c "
import sqlite3
c = sqlite3.connect('doliconstdoc.sqlite')
for row in c.execute(\"SELECT name, purpose FROM constants WHERE hidden_setting=1 LIMIT 20\"):
    print(row)
"
```

Or open `doliconstdoc.sqlite` in DB Browser for SQLite.

## Known limits

- Dynamic patterns (`getDolGlobalString('PREFIX_'.$var)`) are flagged via
  `DYNAMIC_HINT` but not resolved; they appear under whatever literal
  prefix grep found. `tree-sitter-php` is declared in dependencies but not
  yet wired.
- One DB = one Dolibarr source snapshot. No cross-version diff.
- Overrides defined in `conf.php` (`$dolibarr_main_*`) are recorded as a
  wiring hint only, never as live values.

## Directory layout

```
doliconstdoc/
├── prompts/
│   ├── enrich_v2.txt          # active prompt (evidence + confidence)
│   ├── single.txt             # legacy
│   └── batch.txt              # legacy
└── src/doliconstdoc/
    ├── __init__.py            # HASH_VERSION, PROMPT_VERSION
    ├── db.py                  # schema + migrations
    ├── extract.py             # ripgrep + comments + conf.class wiring
    ├── seed.py                # llx_const.sql parser
    ├── payload.py             # per-constant payload for the LLM
    ├── dump_batch.py          # CLI: write /tmp/batch_*.txt
    ├── apply_batch.py         # CLI: merge /tmp/enrich_*.py
    ├── enrich.py              # legacy API-based enrichment
    ├── hash.py                # content_hash for incremental runs
    └── main.py                # top-level CLI
```

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
