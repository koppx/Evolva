# Requirements Baseline

## Goal
Make Evolva Loop Engineering more practical for real local engineering workflows by addressing the highest-priority gaps found in the review: first-class traceability, real quality gates, better execution controls, validation, and durable run evidence.

## Non-goals
- Do not build a full distributed workflow engine.
- Do not add external services or network dependencies.
- Do not change the public TUI product direction.
- Do not implement automated PR creation or git mutation.

## User-visible Behavior
- Running a loop from CLI/TUI should produce both a loop run report and trace evidence.
- `command_success` gates should actually execute their configured command.
- Loop phases can configure timeout and retries.
- Users can validate loop specs before running them.
- Loop run reports should include trace id, gate output, attempts, and artifact metadata when available.

## Acceptance Criteria
- Standalone `LoopRunner.run()` creates a trace run when no active trace exists.
- Nested loop runs do not clobber an existing trace.
- `LoopGate(type="command_success")` executes `command` through the agent tool/policy path and records output.
- `LoopPhase` supports `timeout` and `retries`; tool/shell phases receive timeout when appropriate; retry attempts are recorded.
- CLI supports `evolva loop validate <loop_id|path>` and slash `/loop validate <loop_id|path>`.
- Tests cover the new behavior.
- Full test suite passes.

## Constraints
- Preserve existing JSON loop compatibility.
- Keep implementation local-first and stdlib-oriented.
- Do not revert unrelated user changes.
- Avoid adding dependencies unless necessary.

## Assumptions
- Existing dirty state is clean and branch is `main`.
- Superpowers workflow dependencies are not installed, so this run uses reduced inline mode.
- P0 improvements are enough to move this project closer to actual landing without over-scoping.

## Open Questions
None blocking.

## Source Request
用户："帮我修改一下，到能实际落地"

## Repo Context
Repo root: `/Users/bytedance/Documents/agent`
Base SHA: `e133cdb`
Branch: `main`
Dirty state at start: clean (`## main...origin/main`)
