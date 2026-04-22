# DoliConstDoc

SQLite base documenting every Dolibarr configuration constant (`getDolGlobalString/Int/Bool`, `$conf->global->X`, `dolibarr_set_const`, seed SQL, module descriptors, templates). Built for developer + LLM consumption.

## Quickstart

```bash
cd ~/work/dev/doliconstdoc

# Phase 1 — extract occurrences (rg + PCRE2 + Python post-parse)
PYTHONPATH=src python3 -m doliconstdoc.main --out doliconstdoc.sqlite extract /path/to/dolibarr

# Phase 2 — merge seed SQL defaults (llx_const.sql)
PYTHONPATH=src python3 -m doliconstdoc.main --out doliconstdoc.sqlite seed /path/to/dolibarr

# Phase 3 — LLM enrichment (requires anthropic SDK + ANTHROPIC_API_KEY)
pip install --break-system-packages anthropic
PYTHONPATH=src python3 -m doliconstdoc.main --out doliconstdoc.sqlite enrich --dry-run   # budget preview
PYTHONPATH=src python3 -m doliconstdoc.main --out doliconstdoc.sqlite enrich             # real run

# Stats
PYTHONPATH=src python3 -m doliconstdoc.main --out doliconstdoc.sqlite stats
```

## Current state (v0)

- Built against Dolibarr `develop` (24.0.0-alpha) to anticipate the next stable release; the exact version is recorded in `meta.dolibarr_version`.
- 3180 constants, 19316 occurrences, 41 seed defaults (from `install/mysql/data/llx_const.sql`).
- 1144 comment lines harvested that literally name a known constant, on ~470 distinct constants.
- 3180 / 3180 enriched under the v2 prompt (`evidence` + `confidence` + `conf_php_wiring`). Confidence distribution: 1137 high / 843 medium / 1199 low.
- 1975 `hidden_setting=1` confirmed (same as `hidden_setting_guess`, heuristic = no `admin/*.php` occurrence).

## Pipeline

```
extract.py   → ripgrep (PCRE2) lists all constant mentions, Python regex extracts names,
              classifies usage (read/write/check), stores ±2 lines context with ">>> " marker on the match line.
seed.py      → parses INSERT INTO llx_const(...) VALUES(...) from install/mysql/data/llx_const.sql,
              fills default_value / type, guesses hidden_setting (no occurrence in */admin/*.php).
enrich.py    → groups constants in 3 buckets and calls the LLM:
                batch (≤3 occ, 20 per prompt, Haiku)
                solo Haiku (moderate frequency)
                solo Sonnet (MAIN_SECURITY_* / MAIN_FEATURES_LEVEL* / freq ≥ 50)
              Occurrences ranked (admin > comment > check/write > rest) before capping at cap=10.
hash.py      → deterministic bundle (name, type, default, module, sorted occurrences) → sha256.
              HASH_VERSION bumped on format change to invalidate cache cleanly. Currently v2.
```

## Resuming enrichment (Claude Code session, in-session)

The user's workflow is **in-session enrichment by Claude Code** (no API key, no cost). `enrich.py` exists as a reference implementation for a future API run, but it is not the primary path.

### Recipe for a new Claude Code session

1. Read this README and `<your claude memory dir>/reference_doliconstdoc.md` + `feedback_doliconstdoc_enrichment.md`.
2. Check progress: `PYTHONPATH=src python3 -m doliconstdoc.main --out doliconstdoc.sqlite stats` — see how many are already enriched.
3. Select the next N un-enriched constants (user will say "go N"):
   ```python
   import sqlite3, sys
   sys.path.insert(0, 'src')
   from doliconstdoc.enrich import format_occurrences
   c = sqlite3.connect('doliconstdoc.sqlite')
   done = {r[0] for r in c.execute("SELECT name FROM constants WHERE doc_quality>=1")}
   candidates = [r[0] for r in c.execute("""
     SELECT const_name FROM occurrences
     WHERE const_name NOT IN (SELECT name FROM constants WHERE doc_quality>=1)
     GROUP BY const_name ORDER BY COUNT(*) DESC LIMIT ?""", (N,))]
   # Dump payloads with ranked occurrences for reading
   ```
4. For each constant, read its payload (name, type, default, module, ranked occurrences) and write purpose/description/impact/possible_values/hidden_setting from the code evidence.
5. Commit via a temp Python script that `UPDATE constants SET ... WHERE name=?` and sets `doc_quality=1, last_enriched=now`.
6. Run `stats` to confirm count went up.

**Tips from prior sessions:**
- Trust the ranked occurrences (`format_occurrences`). `/admin/*` files + inline `//` comments are the gold signal.
- Conservative on `hidden_setting=1`: set it only if no admin UI file is cited in occurrences AND the constant's role makes "no UI" plausible.
- Don't invent behavior. If context is sparse, say so in `description` ("Exact behavior unclear from code alone.").
- User asks in increments ("go 50", "go 300"). Do not over-batch — output token cost on Claude's side accumulates.
- Avoid dumping payloads inline (keeps conversation context lean). Use a Python dump to stdout only when needed for review.

### API fallback

If the user ever wants to burst through the remainder, `enrich.py` works: install `anthropic`, set `ANTHROPIC_API_KEY`, run the `enrich` subcommand. Est. ~$6-10 on Haiku+Sonnet for the remaining ~3100.

## Re-run behavior

Re-running after the Dolibarr source changes:
- `extract` + `seed` re-populate from scratch (deletes/inserts occurrences).
- `enrich` computes content_hash per constant and **skips already-enriched ones whose bundle hash is unchanged** — only new/changed constants re-hit the LLM.
- Bumping `HASH_VERSION` in `src/doliconstdoc/__init__.py` forces a global re-enrichment (useful after prompt changes).

## Schema

```sql
constants(name PK, type, default_value, module,
          purpose, description, impact, possible_values,
          hidden_setting, hidden_setting_guess, admin_ui_files,
          doc_quality, content_hash, hash_version, last_enriched,
          -- v2 enrichment fields:
          evidence,        -- JSON list of verbatim citations from payload
          confidence,      -- 'high' | 'medium' | 'low'
          conf_php_wiring) -- $dolibarr_main_* → $conf->global->NAME (if any)
occurrences(id, const_name FK, file, line, usage_type, context)
comments(id, const_name FK, file, line, text)   -- //, /*, *, # comments that cite CONST
meta(key PK, value)  -- keys: dolibarr_version, extract_date, hash_version, prompt_version, seed_rows
```

## Anti-hallucination pipeline (v2)

Enrichment is done by an LLM, which will happily extrapolate semantics from a
narrow context window when the code alone is ambiguous. Treat the generated
fields as a starting point, not ground truth — especially the rows tagged
`confidence='low'`. Three measures reduce the risk:

1. **Extended context**: `extract.py` now uses ±10 lines around `check`/`write`
   occurrences (vs ±2 before), so authoritative comments a few lines above the
   handler are captured in the stored context.
2. **Dedicated `comments` table**: `extract_comments()` greps all single-line
   and block comments that literally name a known constant, with a stoplist
   for false positives (`XXX`, `TODO`, `API`, etc.). 1.1k comments on ~470
   constants. `payload.build_payload()` always appends these verbatim.
3. **`conf.class.php` wiring**: `extract_conf_wiring()` parses
   `$this->global->NAME = $this->file->key` assignments and records the
   `$dolibarr_main_key` → constant mapping. A constant with a wiring line is
   set only in `conf.php` (not the admin UI); the prompt forces the model to
   state that in `description`.

The v2 prompt (`prompts/enrich_v2.txt`) additionally requires:
- `evidence`: list of 1–4 verbatim citations from the payload.
- `confidence` ∈ {high, medium, low} with explicit rules.
- Ban on speculative wording unless tagged `[SPECULATION]`.

### Re-enrich workflow

```bash
# 1. Re-harvest comments + conf.php wiring on an existing extracted DB:
PYTHONPATH=src python3 -m doliconstdoc.main --out doliconstdoc.sqlite harvest /path/to/dolibarr

# 2. Dump a batch (ad-hoc names or SQL filter):
PYTHONPATH=src python3 -m doliconstdoc.dump_batch \
  --filter "confidence IS NULL OR confidence='low'" --chunk 50 --dir /tmp

# 3. Run N parallel Sonnet subagents pointed at prompts/enrich_v2.txt.

# 4. Merge:
PYTHONPATH=src python3 -m doliconstdoc.apply_batch /tmp/enrich_*.py
```

## Querying

```bash
python3 -c "
import sqlite3
c = sqlite3.connect('doliconstdoc.sqlite')
for row in c.execute(\"SELECT name, purpose FROM constants WHERE hidden_setting=1 AND doc_quality>=1 LIMIT 20\"):
    print(row)
"
```

Or open `doliconstdoc.sqlite` in DB Browser for SQLite.

## Known limits v0

- Dynamic patterns (`getDolGlobalString('MAIN_MODULE_'.strtoupper($m))`) are flagged via `DYNAMIC_HINT` in `extract.py` but tree-sitter-php path is not wired yet — they currently appear under whatever literal prefix grep found.
- `hidden_setting_guess` is conservative (15/3180 flagged, ~24 real ones confirmed in the 80-sample).
- Overrides in `conf.php` (`$dolibarr_main_*`) are explicitly out of scope.
- No diff across Dolibarr versions (one DB = one version snapshot).

## Directory layout

```
doliconstdoc/
├── doliconstdoc.sqlite       # the output
├── prompts/
│   ├── single.txt            # solo-constant prompt
│   └── batch.txt             # 20-at-a-time prompt
└── src/doliconstdoc/
    ├── __init__.py           # HASH_VERSION, PROMPT_VERSION
    ├── db.py                 # schema + helpers
    ├── extract.py            # phase 1
    ├── seed.py               # phase 2
    ├── enrich.py             # phase 3 (Haiku/Sonnet + cache)
    ├── hash.py               # phase 4
    └── main.py               # CLI
```
