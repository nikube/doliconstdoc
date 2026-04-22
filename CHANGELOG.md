# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are not
yet tagged — the first tagged release is tracked below under *Unreleased*.

## [Unreleased]

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
