# Research Program

## Objective

Continuously improve agent-readable skill content and orchestration prompts used by the MCP portfolio while preserving security behavior and baseline correctness.

## Editable surface

- skill markdown files
- planner instructions
- tool descriptions
- clarification and refusal examples

## Non-goals

- no SQL files
- no secret persistence
- no production-side credential changes
- no bypass of row-level security or other security controls

## Acceptance policy

1. A candidate change must pass deterministic `evals-101` gates.
2. A candidate change must not introduce new security regressions.
3. A candidate change must improve the tracked score over the current baseline.
4. If scores tie, prefer the smaller and clearer change set.
