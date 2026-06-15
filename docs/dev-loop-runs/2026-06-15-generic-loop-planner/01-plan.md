# Implementation Plan

## Architecture Summary
Add an LLM-first Loop Planner layer above the existing Loop Engine:

- `evolva/loops/planner.py`: data models, intent analyzer, decomposer/templates, renderer, session persistence, spec synthesis.
- Existing `LoopSpec` gains `execution_limits` metadata so generated specs carry bounded execution contracts.
- Existing `validate_loop_spec` checks execution limits and generated phase retry caps.
- CLI and TUI route natural-language `/loop` to planner commands while keeping existing runner commands.

## Files Expected to Change
- `evolva/loops/spec.py`
- `evolva/loops/runner.py`
- `evolva/loops/__init__.py`
- `evolva/cli.py`
- `evolva/tui.py`
- `tests/test_loops.py`
- `README.md`
- New: `evolva/loops/planner.py`

## Task Order
1. Add planner models/session/rendering/spec synthesis.
2. Add execution limits to specs and validation.
3. Wire CLI `/loop plan/revise/show-draft/confirm/execute/save/cancel` plus natural-language fallback.
4. Wire TUI slash commands with friendly messages and async execute.
5. Add tests for planner, CLI, TUI, validation, persistence.
6. Update README.
7. Run targeted and full tests.

## Verification Commands
- `.venv/bin/python -m pytest -q tests/test_loops.py`
- `.venv/bin/python -m pytest -q tests/test_agent_cli_workflow_mcp_eval_tui.py`
- `.venv/bin/python -m pytest -q`
- Manual CLI smoke commands for plan/confirm/save.

## Risks and Mitigations
- Risk: generated shell command fails validation due missing allowlist. Mitigation: synthesize `command_allowlist` from command candidates.
- Risk: planner over-promises execution. Mitigation: plan defaults to non-executing confirmation page; execution requires confirm.
- Risk: arbitrary natural language creates unsafe commands. Mitigation: only template-known safe commands; high-risk requests get manual confirmation checkpoint and no destructive commands.
- Risk: TUI/CLI command divergence. Mitigation: shared planner helpers and tests for both.
