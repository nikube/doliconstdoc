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

## Submitting corrections via pull request

Under `data/` every SQLite table is mirrored as a deterministic SQL dump:

- `data/constants.sql` — one `INSERT` per constant, ordered by `name`.
  **This is the file you edit** to fix a wrong purpose, description,
  impact, possible_values, or `hidden_setting` flag.
- `data/occurrences.sql` — pure machine output, regenerated on every
  extraction. **Do not edit by hand**; PRs touching it will be rejected.
- `data/comments.sql`, `data/meta.sql` — same policy as `occurrences.sql`.

### Marking a row as human-reviewed

`doc_quality` distinguishes the source of the current row content:

| Value | Meaning                                                  |
|-------|----------------------------------------------------------|
| `0`   | Extracted only (type, default, module inferred).         |
| `1`   | Enriched by the LLM.                                     |
| `2`   | Reviewed or corrected by a human.                        |

When you fix a row in `data/constants.sql`, **set its `doc_quality` to 2
in the same line**. The build pipeline never overwrites `doc_quality=2`
rows, so your correction is safe from future re-enrichment.

### PR checklist

1. Your diff touches `data/constants.sql` only (unless you are also
   patching the extractor or prompt).
2. Every modified line has `doc_quality = 2`.
3. One concern per PR: fix one description, or one `hidden_setting` flag,
   not a mix.
4. In the PR description, briefly say *why* — quote the source code that
   makes the current value wrong.

## Rebuilding the SQLite from `data/`

```bash
PYTHONPATH=src python3 -m doliconstdoc.sqldump load --src data --out doliconstdoc.sqlite
```

## Style

- Keep extractor changes deterministic and cheap to re-run.
- Don't invent semantics in prompts. If you extend the prompt, keep the
  "no speculation without `[SPECULATION]` tag" rule and keep the `evidence`
  field mandatory.
- Add a short entry to `CHANGELOG.md` under `## [Unreleased]` when your
  change is user-visible.
