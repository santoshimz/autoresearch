# Architecture Decisions

## ADR-001: Keep `skills-201` as the primary mutation target

### Status

Accepted

### Context

`autoresearch` is a bounded research worker for agent-facing content. Its current loop, default target profile, and deterministic evaluation stack are centered on `targets/skills-201/`.

The repo also bundles `targets/mcp-201-prompts/`, which is useful because it captures realistic downstream prompt-routing behavior for image workflows such as crop-only, colorize-only, and crop-then-colorize flows.

The question is whether `mcp-201` should become the main mutation target now.

### Decision

Keep `skills-201` as the primary mutation target for now.

Use `mcp-201` as project context and as a downstream validation surface, not as the default editable surface.

### Rationale

- The current orchestration and scoring path is already wired around `skills-201`, including the default approved profile and deterministic gate-first evaluation flow.
- `skills-201` is a safer text-first surface for bounded mutation. It keeps edits in documentation and skill guidance instead of pushing the loop toward more operational prompt-planner behavior too early.
- Promoting `mcp-201` to the main target today would widen the editable surface before the acceptance flow has stronger downstream validation and promotion controls.
- `mcp-201` includes realistic routing and BYOK/security-sensitive context. That makes it valuable for catching regressions, but it also means mutating it directly too early would raise the risk of teaching the system the wrong behavior around tool routing, key handling, or other security constraints.
- The current project goal is to improve agent behavior assets safely and deterministically first, then strengthen realism by validating against downstream surfaces.

### Consequences

- The default loop continues to mutate and score `skills-201`.
- `mcp-201` should be added to acceptance-time validation so a candidate that improves `skills-201` but regresses downstream routing or security behavior is rejected.
- The project should not switch the default mutation target to `mcp-201` until there is a stronger evaluation and promotion stack for that surface.
