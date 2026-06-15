# Implementation Log

## Scope
Implemented production-oriented generic Loop Engineering support for natural-language `/loop` requests.

## Changed Files

- `evolva/loops/planner.py`
  - Added LLM-first intent analysis for `web_feature`, `code_feature`, `bugfix`, `docs`, `release`, `analysis`, and `data_task`, with deterministic heuristic fallback when no model is configured or JSON parsing fails.
  - Added `LoopDraft`, user-visible phases/checkpoints/risks, execution budgets, draft persistence, revision, confirmation, save, and rendering helpers.
  - Generated executable `LoopSpec` from draft only after the user confirms the draft flow.
- `evolva/loops/spec.py`
  - Added `execution_limits` to `LoopSpec` serialization/deserialization.
- `evolva/loops/runner.py`
  - Added validation for `execution_limits`.
  - Added runtime enforcement for max duration, max tool calls, max shell command runs, and max file changes.
  - Kept shell command allowlist and Policy checks on both shell phases and command gates.
- `evolva/cli.py`
  - Added CLI lifecycle: `loop plan`, `show-draft`, `revise`, `confirm`, `execute`, `save`, `cancel`.
  - Fixed free-form parser so `--show-spec` works before or after natural-language text.
- `evolva/tui.py`
  - Added natural-language `/loop <request>` routing and draft lifecycle commands.
  - Added generated-spec execution worker after confirmation.
- `evolva/loops/__init__.py`
  - Exported new planner/session/render APIs.
- `tests/test_loops.py`
  - Added planner, session, CLI/TUI, validation, parser, and runtime-budget coverage.
- `README.md`
  - Documented natural-language `/loop` flow, confirmation gate, execution limits, allowlist safety, and CLI examples.

## Behavior Delivered

1. User can type `/loop <natural-language requirement>` and gets a Loop Draft instead of immediate code execution.
2. Draft shows interpreted intent, goal, phase graph, checkpoints, command candidates/allowlist, assumptions, risks, and execution budgets.
3. User can revise the draft, confirm it, execute it only after confirmation, save it as a reusable Loop spec, or cancel it.
4. CLI supports the same lifecycle for automation.
5. Generated LoopSpec is strict-validated before being marked ready.
6. Runtime guardrails now actively stop loops that exceed declared budgets.

## Verification Commands

```bash
.venv/bin/python -m pytest -q tests/test_loops.py
# 18 passed in 2.10s

.venv/bin/python -m pytest -q tests/test_loops.py tests/test_agent_cli_workflow_mcp_eval_tui.py
# 49 passed, 1 skipped in 2.31s

.venv/bin/python -m pytest -q
# 109 passed, 1 skipped in 3.23s
```

A later final verification run should be treated as the source of truth if its timing differs.

## Manual Smoke

```bash
.venv/bin/python -m evolva.cli loop --yes plan "做一个响应式 landing page，有 hero、pricing、FAQ" --show-spec
.venv/bin/python -m evolva.cli loop --yes confirm
.venv/bin/python -m evolva.cli loop --yes save manual-generated-loop
```

The first smoke exposed a parser issue where `--show-spec` after a free-form request was swallowed into the request. This was fixed by changing the free-form positional parser from `argparse.REMAINDER` to `nargs="+"` and adding regression coverage.

## Residual Notes

- The planner is now LLM-first for production behavior: it calls the configured model to decompose the request into phases/checkpoints/risks/budgets, then sanitizes the output. Heuristic planning remains as an offline fallback that preserves the same confirmation contract.
- Generated commands are safe allowlist candidates; runtime context scan can still recommend replacing them when the repo uses different tooling.
