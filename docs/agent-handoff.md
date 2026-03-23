# Agent Handoff

This document is the fastest way to onboard a new agent to `autoresearch`.

## What `autoresearch` does

`autoresearch` is a bounded research worker for agent-facing content.

Its current job is to:

- propose small changes to bundled `skills-201` docs
- evaluate those changes with deterministic bundled datasets
- reject any change with security regressions
- accept only the best candidate that beats the current baseline
- append every evaluated attempt to `experiments/history.jsonl`

It is deliberately not a general code mutator. The default mutation surface is text only.

## Why it exists

The project is meant to improve agent behavior assets safely:

- skill docs
- workflow guidance
- clarification examples
- security wording
- tool descriptions

The main idea is to turn prompt and skill iteration into a measurable closed loop instead of ad hoc editing.

## Current architecture

### Main modules

- `autoresearch/loop.py`
  - owns the orchestration loop
  - resolves the baseline
  - evaluates all proposed candidates
  - ranks them
  - accepts only the best improving candidate

- `autoresearch/strategy.py`
  - defines the current bounded proposal library
  - generates candidate text patches for the approved surface
  - today it proposes clarification, BYOK/security, composition, and tool-routing improvements

- `autoresearch/workspace.py`
  - creates a temporary copy of the approved files
  - applies candidate patches in isolation
  - ensures evaluation does not mutate the source surface directly

- `autoresearch/evaluation.py`
  - contains the `Skills201EvalGateway`
  - loads the bundled target corpus
  - simulates workflow/tool routing behavior from the docs
  - runs gate first, then nightly only after gate pass

- `autoresearch/evals.py`
  - standalone copy of the minimal evaluation framework
  - contains contracts, graders, dataset loading, and the base runner abstraction

- `autoresearch/storage.py`
  - appends experiment records to the JSONL ledger
  - derives current baseline from accepted prior runs

- `autoresearch/config.py`
  - resolves the standalone repo root
  - declares bundled datasets and editable target profiles

### Bundled surfaces

- `targets/skills-201/`
  - default mutation target
  - contains the README and mirrored skill docs the loop edits/evaluates

- `targets/mcp-201-prompts/`
  - future prompt-only optimization surface
  - currently bundled as a small extracted prompt/doc target, not the primary mutation target

- `datasets/gate/`
  - deterministic must-pass routing checks

- `datasets/nightly/`
  - broader follow-up checks that only run after gate success

## Runtime flow

1. Load the approved target profile from `autoresearch/config.py`.
2. Copy the allowed files into a temp workspace.
3. Evaluate the untouched baseline workspace.
4. Propose bounded candidates from `autoresearch/strategy.py`.
5. For each candidate:
   - create a fresh temp workspace
   - apply only that candidate's patches
   - run the eval gateway
   - record a provisional result
6. Rank candidates by:
   - score first
   - then fewer patches
   - then fewer target files
7. Accept only the best candidate if:
   - gate passed
   - no security regressions were found
   - score strictly beat the baseline
8. Append all attempts to `experiments/history.jsonl`.

## What the eval actually measures today

The bundled `Skills201EvalGateway` is intentionally lightweight and deterministic.

It checks whether the bundled skill docs imply the right behavior for prompts like:

- crop only
- colorize only
- crop then colorize
- ambiguous requests that should clarify
- BYOK requests that must stay ephemeral

It also checks for obvious security regressions in text such as guidance that implies:

- saving API keys
- storing API keys
- persisting credentials
- bypassing RLS

This is not a live end-to-end product evaluation yet. It is a deterministic text-driven proxy for agent behavior.

## How to run it

From the repo root:

```bash
./scripts/setup_local.sh
./scripts/run_tests.sh
./scripts/run_local.sh
```

Expected behavior:

- tests should pass
- one local iteration should print the winning candidate and score
- the ledger should be written to `experiments/history.jsonl`

You can also run the CLI directly:

```bash
. .venv/bin/activate
python -m autoresearch.cli --ledger experiments/history.jsonl
```

## How to deploy it

This project is designed as a worker, not a web app.

The intended deployment shape is:

- scheduled container job
- cron-like worker
- CI-triggered experiment run

Current container path:

```bash
./scripts/deploy_docker.sh
docker run --rm -v "$(pwd)/experiments:/app/experiments" autoresearch:local
```

For a first real deployment, a new agent should focus on:

- repeatable container build
- mounted or persisted ledger volume
- log capture for each run
- configurable schedule
- safe promotion flow for accepted candidates

## What is not implemented yet

- automatic promotion of accepted patches back into the real target files
- real `mcp-201` downstream validation in the acceptance flow
- live product adapters instead of deterministic text-driven simulation
- richer candidate generation using an LLM or search-based proposal engine
- human review workflow for accepted changes before promotion
- rollback/versioned promotion path

## Best next extensions

### 1. Add promotion

Right now the loop discovers winning candidates but does not write them back to the source target.

Add:

- a promotion command that applies the accepted candidate to `targets/skills-201`
- optional human approval before promotion
- an audit trail linking promotion events to ledger entries

### 2. Add real `mcp-201` validation

The safest next strengthening step is:

- keep `skills-201` as the mutation surface
- add `mcp-201` as a downstream validation surface
- reject any candidate that helps `skills-201` but regresses `mcp-201`

That preserves safety while making evaluation more realistic.

### 3. Expand candidate generation

Today candidates are hand-authored in `autoresearch/strategy.py`.

Extend this by adding:

- more proposal templates
- candidate sampling
- LLM-generated drafts with strict validation
- scoring explanations and failure reason classification

### 4. Add richer datasets

The current datasets are intentionally small.

A new agent can extend them with:

- more ambiguous prompts
- more refusal/security cases
- more workflow composition cases
- negative cases that ensure unsafe suggestions are rejected

### 5. Add operational deployment

For deployment readiness, add:

- environment-based configuration for ledger path and run mode
- structured JSON logging
- container health/status output
- optional GitHub integration for opening review PRs instead of direct promotion

## Guardrails for any future agent

- Do not widen the editable surface without explicit approval.
- Do not generate SQL files.
- Do not add any mechanism that bypasses RLS or weakens security controls.
- Do not persist secrets or keys.
- Keep the default target text-only until a stronger eval stack exists.
- Prefer deterministic gates before any softer or LLM-based scoring.

## Suggested next-agent brief

If you hand this project to a new agent, give it this goal:

> Extend `autoresearch` from a standalone deterministic research worker into a deployment-ready, reviewable promotion system. Keep `skills-201` as the primary mutation target, add downstream `mcp-201` validation, preserve all security constraints, and avoid widening the editable surface beyond approved prompt/skill/doc files unless explicitly approved.
