# Implementation Plan

## Goal and Architecture Summary
Upgrade Evolva loop execution from a light runner to a more reliable local engineering loop unit. The changes will stay within existing modules and preserve compatibility.

## Files Expected to Change
- `evolva/loops/spec.py`: add phase execution controls, richer gate/run result metadata, validation helper.
- `evolva/loops/runner.py`: add trace lifecycle, retries, timeout propagation, real command gates, artifact capture, validation rendering.
- `evolva/loops/__init__.py`: export validation renderer if needed.
- `evolva/cli.py`: add `/loop validate` and `evolva loop validate`.
- `evolva/tui.py`: add `/loop validate`.
- `tests/test_loops.py`: cover new behavior.
- `docs/dev-loop-runs/...`: record process artifacts.

## Task Order
1. Extend dataclasses for phase controls and richer results.
2. Implement LoopRunner trace lifecycle and command gate execution.
3. Add validation rendering and CLI/TUI command wiring.
4. Add tests for trace lifecycle, command gate, retry/timeout, validate.
5. Run targeted and full tests.
6. Write acceptance artifacts.

## Verification Commands
- `.venv/bin/python -m pytest -q tests/test_loops.py`
- `.venv/bin/python -m pytest -q`

## Risks and Mitigations
- Risk: starting trace in nested agent chat could clobber existing trace. Mitigation: only start/end trace if no current trace exists.
- Risk: command gates bypass policy. Mitigation: run through `agent._call_tool("shell", ...)`.
- Risk: timeout semantics only apply to tool args. Mitigation: add timeout to shell/python args if not specified and record it.

## Acceptance Mapping
Matches all criteria from `00-requirements.md`.
