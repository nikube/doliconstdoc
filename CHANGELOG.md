# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Tags follow
`vMAJOR.MINOR` (see README).

## [24.2] - 2026-10-25

### Changed
- Re-extracted against the Dolibarr **stable tag `24.0.2`** @ `7e92776476`
  (2026-10-02) instead of `develop`: 3231 constants (16 added, 4 removed,
  60 with changed usage since v24.1), 18882 occurrences, 1083 comments.
- 16 new constants enriched from a source-level read (Opus), 60 changed
  constants updated against the new code (Sonnet). Confidence distribution:
  **1559 high / 1610 medium / 62 low**.
- Notable corrections: `MAIN_INFO_LOCALTAX_CALC` is really the dynamic
  `MAIN_INFO_LOCALTAX_CALC1/2` written by `admin/company.php`;
  `PRODUCT_ADDON_PDF` no longer falls back to `strato`;
  `PROJECT_CAN_ALWAYS_LINK_TO_ALL_SUPPLIERS` defaults to 1 in
  `conf.class.php`; `PDF_USE_A` documents values 0/1/3; `PRODUCT_USE_UNITS`
  and `TICKET_EMAIL_MUST_EXISTS` admin switches are commented out
  (hidden); `SUBTOTAL_TITLE_` is toggled by `admin/subtotals.php`.
- Removed: `AVAILABILITIES_ADDON_PDF`, `HOLIDAY_DISALLOW_NEGATIVE_BALANCE`,
  `MAIN_SOCIETE_SHOW_COMPLETE_NAME`, `MAIN_USE_DOL_EVAL_NEW`.
- `hidden_setting_guess` recomputed from `admin_ui_files` (2006).

## [24.1] - 2026-07-24

### Changed
- Re-extracted against Dolibarr `develop` @ `a4d355d24f` (2026-07-24):
  3219 constants (59 added, 20 removed, 391 with changed usage since the
  April v24.0 extraction), 18800 occurrences, 1056 comments.
- Re-enriched the 450 added/changed constants (Sonnet batch pipeline).
- Deep-dive re-enrichment of all 1243 low-confidence constants: agents
  investigated the actual source tree (code around each occurrence, missed
  admin UI writes, dead/commented-out references) instead of the extracted
  payload only. Confidence distribution moves from 1018/957/1243
  (high/medium/low) to **1555/1608/56**; the surviving lows are documented
  dead code, source typos (`FATURE_LOCAL_TAX2_OPTION`,
  `MAIN_MAIL_SMTPS_IDT`), dynamic name prefixes or write-only orphans.
- ~40 `hidden_setting` corrections where a real admin UI write existed but
  was missed by the extractor (`ajax_constantonoff`, `setModuleOptions`
  forms, numbering-module inline forms).
- `meta` now records `dolibarr_version` and `dolibarr_commit`.

## [24.0] - 2026-04-22

### Added
- `comments` table capturing single-line and block PHP comments that literally
  mention a known constant name, with a stoplist for false positives
  (`XXX`, `TODO`, `API`, `DOL`, …).
- `constants.evidence` column (JSON list of verbatim citations from the
  enrichment payload).
- `constants.confidence` column (`high` / `medium` / `low`, rules in
  `prompts/enrich_v2.txt`).
- `constants.conf_php_wiring` column — mappings parsed from
  `core/class/conf.class.php` for constants set only via `conf.php`
  (`$dolibarr_main_*`) rather than the admin UI.
- `main.py harvest <dolibarr-root>` subcommand: re-runs only the comments +
  conf.php wiring passes against an existing DB (no re-extract).
- `doliconstdoc.payload.build_payload()` — emits a payload block that
  includes `COMMENTS:` and `CONF_PHP_WIRING:` alongside ranked occurrences.
- `doliconstdoc.dump_batch` CLI — writes `/tmp/batch_*.txt` files suitable
  for parallel enrichment.
- `doliconstdoc.apply_batch` CLI — merges one or more `enrich_*.py` files
  back into the DB, accepting both the legacy 6-tuple and the v2 8-tuple
  shape.
- `prompts/enrich_v2.txt` — strict protocol forcing verbatim evidence,
  confidence tagging and banning speculative wording (unless tagged
  `[SPECULATION]`).
- `doliconstdoc.exportcsv` CLI — writes a 3-column CSV (`name`, `purpose`,
  `where`) derived from the DB. `where` is `conf.php` when a wiring is
  recorded, else the deduplicated admin UI paths, else `hidden`.
- `doliconstdoc.sqldump` CLI with `dump` and `load` subcommands. Writes
  `data/{schema,constants,occurrences,comments,meta}.sql` with one
  `INSERT` per row, sorted by primary key, newlines escaped as
  `|| char(10) || …` so diffs stay line-oriented.
- `data/` directory committed: the SQL dump is now the diffable source of
  truth; `doliconstdoc.sqlite` is always rebuildable from it.
- `doc_quality=2` semantics: rows flagged as human-reviewed are never
  overwritten by `apply_batch` and are excluded by `dump_batch` unless
  `--include-human-reviewed` is passed.

### Changed
- `extract.py`: occurrence context window grown from ±2 lines to ±10 lines
  for `check` and `write` usages (authoritative dev comments often sit a few
  lines above the handler).
- `extract.py`: `extract_comments()` and `extract_conf_wiring()` run as part
  of the `extract` pipeline.
- `stats` subcommand now reports `comments`, `conf_php wirings` and the
  confidence histogram.

### Fixed
- `hidden_setting_guess` was previously under-counting (observed value: 15
  across 3180 constants). It is now recomputed from `admin_ui_files`
  (1975 flagged).

### Known limits
- The enrichment pipeline currently runs via parallel Claude Code subagents,
  not via the legacy `enrich.py` Anthropic API entry point. `enrich.py`
  exists as a reference implementation but is not exercised by CI.
- `tree-sitter-php` is declared as a dependency but is not yet wired; dynamic
  patterns (`getDolGlobalString('PREFIX_'.$var)`) are only flagged, not
  resolved.
