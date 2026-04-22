# Contributing

Thanks for considering a contribution. A few notes before you open a PR.

## What this project is

A tool that produces a SQLite documentation base for Dolibarr configuration
constants. The DB is a *derived artefact*: it is rebuilt from a specific
Dolibarr source tree. The code in this repo is what you usually want to
patch; the DB shipped with a release is the output of running that code.

## Where changes usually land

- **Extractor** (`src/doliconstdoc/extract.py`) — ripgrep patterns, comment
  harvesting, `conf.class.php` wiring, context window sizing.
- **Payload builder** (`src/doliconstdoc/payload.py`) — what the LLM agent
  sees when enriching a constant.
- **Enrichment prompt** (`prompts/enrich_v2.txt`) — the contract the agent
  has to follow. Changes here frequently require bumping
  `PROMPT_VERSION` in `src/doliconstdoc/__init__.py` and re-enriching.
- **DB schema** (`src/doliconstdoc/db.py`) — add columns via the
  `MIGRATIONS` list so existing DBs still open.

## Running the pipeline locally

```bash
# Requires a local Dolibarr checkout (htdocs/ at the root).
PYTHONPATH=src python3 -m doliconstdoc.main --out doliconstdoc.sqlite extract /path/to/dolibarr
PYTHONPATH=src python3 -m doliconstdoc.main --out doliconstdoc.sqlite seed    /path/to/dolibarr
PYTHONPATH=src python3 -m doliconstdoc.main --out doliconstdoc.sqlite harvest /path/to/dolibarr
PYTHONPATH=src python3 -m doliconstdoc.main --out doliconstdoc.sqlite stats
```

Enrichment is done in-session via parallel Claude Code subagents driven by
`doliconstdoc.dump_batch` + `doliconstdoc.apply_batch` against
`prompts/enrich_v2.txt`. A legacy `enrich.py` path using the Anthropic API
is kept as a reference implementation (requires `ANTHROPIC_API_KEY`).

## Style

- Keep extractor changes deterministic and cheap to re-run.
- Don't invent semantics in prompts. If you extend the prompt, keep the
  "no speculation without `[SPECULATION]` tag" rule and keep the `evidence`
  field mandatory.
- Add a short entry to `CHANGELOG.md` under `## [Unreleased]` when your
  change is user-visible.
