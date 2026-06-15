# Requirements Baseline

## Goal
Implement the product design in `docs/loop-engineering-product-design.md`: make `/loop <natural language request>` a generic Intent-to-Loop planning entrypoint that can decompose a user request, show a friendly confirmation plan, support revision/confirmation/saving/execution, and remain safe and bounded.

## Non-goals
- Do not build a remote/cloud multi-tenant orchestration service.
- Use the configured LLM first for production task decomposition; keep deterministic heuristics as an offline fallback when LLM access is unavailable or invalid.
- Do not execute natural-language `/loop` requests immediately.
- Do not remove or break existing `/loop list/show/validate/dry-run/run` commands.

## User-visible Behavior
- `/loop 做一个网页...` creates a readable Loop draft, not an execution.
- `/loop plan <request>` does the same explicitly.
- `/loop show-draft` displays the current draft.
- `/loop revise <feedback>` updates the draft and records the revision.
- `/loop confirm` validates the generated spec and marks it ready when validation passes.
- `/loop execute` runs only the confirmed draft-generated spec.
- `/loop save <name>` writes the generated spec as reusable JSON.
- `/loop cancel` clears the current draft.
- CLI exposes analogous subcommands where practical.

## Acceptance Criteria
1. Natural-language `/loop` is routed to plan mode when the first token is not a reserved command.
2. The generated draft includes goal, intent type, assumptions, phases, checkpoints, command candidates, risks, execution limits, and next actions.
3. Generated spec is valid under strict loop validation for common offline cases.
4. Shell commands in generated specs are explicit and allowlisted.
5. Execution is bounded with execution limits and phase retry/timeout caps.
6. User confirmation is required before execution.
7. Draft state persists on disk across CLI/TUI command calls.
8. Existing loop commands continue to work.
9. Tests cover planner generation, revision, save, CLI command routing, and TUI slash behavior.

## Constraints
- Preserve dirty worktree; do not revert unrelated existing changes.
- Prefer stdlib only.
- Keep code understandable and production-grade enough for local trusted engineering workflows.
- Avoid destructive shell commands in generated specs.

## Assumptions
- LLM-first intent analysis is required for production behavior; offline deterministic intent analysis is only the fallback path.
- Generated execution phases can use agent prompts for implementation work and shell phases for validation commands.
- A single active draft per Evolva config root is sufficient for V1.

## Open Questions
None blocking; proceed with product-document defaults.

## Source Request
用户要求：“按照产品文档，帮我对evolva改造，实现这个重要功能，要求不许偷懒，功能要对用户友好，尽可能开箱即用”。

## Repo Context
- Repo root: `/Users/bytedance/Documents/agent`
- Base SHA: `e133cdbf4022ed3443b3927445bcc37888b56642`
- Existing Loop Engine has LoopSpec, LoopRunner, validate, dry-run, allowlist, retry, resume, trace/report.
- Current worktree already has previous Loop Engineering changes and docs.
