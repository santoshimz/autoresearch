# autoresearch

`autoresearch` adapts the experimentation pattern from [`autoresearch-macos`](https://github.com/miolini/autoresearch-macos) to this portfolio's actual target: improving skill documents, prompts, and tool-use instructions over time without weakening security or breaking the baseline contract measured by `evals-101`.

## Why `autoresearch` exists inside `autoresearch`

This repo uses a standard Python package layout. The outer folder is the repository root. The inner `autoresearch/` folder is the importable Python package used by the CLI and tests.

## Purpose

- propose small, reviewable changes to prompts, policies, or skill documents
- run `evals-101` gate suites before any broader comparison
- accept changes only when they improve the tracked score and introduce no new regressions
- keep a clean append-only experiment ledger with redacted metadata

## Repository layout

- `research_program.md`: human-owned constraints and optimization targets
- `autoresearch/models.py`: experiment and evaluation data models
- `autoresearch/storage.py`: append-only JSONL experiment ledger
- `autoresearch/loop.py`: constrained research loop with gate-first acceptance logic
- `autoresearch/cli.py`: command-line entrypoint
- `tests/`: unit tests for the loop and acceptance logic
- `scripts/setup_local.sh`: local bootstrap
- `scripts/run_local.sh`: run one local research iteration
- `scripts/run_tests.sh`: unit-test wrapper
- `scripts/deploy_docker.sh`: build a container image for scheduled workers

## Guardrails

- no direct production writes from the loop itself
- restricted editable surface defined in `research_program.md`
- no credential persistence
- deterministic eval gates must pass before broader scoring matters
- no SQL script generation

## Prerequisites

- Python 3.11+
- `pip`

## Local setup

```bash
./scripts/setup_local.sh
```

## Run locally

Run one local iteration:

```bash
./scripts/run_local.sh
```

That writes an append-only JSONL record to `experiments/history.jsonl`.

Run tests:

```bash
./scripts/run_tests.sh
```

## Deployment

This repo is designed for a scheduled worker model rather than a browser app. The normal deployment target is a container or job runner that wakes up, proposes a bounded change, runs evals, records the outcome, and exits.

Build the container image:

```bash
./scripts/deploy_docker.sh
```

Example container run:

```bash
docker run --rm -v "$(pwd)/experiments:/app/experiments" autoresearch:local
```

## Operating model

1. load the optimization rules from `research_program.md`
2. propose a bounded change
3. run `evals-101` gate checks
4. reject any change with security regressions
5. accept only changes that beat the current baseline score
6. record every attempt in the ledger for later review
