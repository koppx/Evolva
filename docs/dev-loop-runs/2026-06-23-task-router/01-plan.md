# Plan

## Architecture Summary
Add a deterministic `TaskRouter` inside `evolva.agent.multi_agent`. It classifies task text into a small set of routes:

- `simple`: stay in the single-agent loop.
- `tool_task`: single agent with tools.
- `research`: researcher + reviewer.
- `coding`: planner + coder + reviewer.
- `review`: reviewer.
- `complex`: planner + researcher + coder + reviewer.

`MultiAgentCoordinator.collaborate_report()` uses the router when roles are not explicit. `EvolvaAgent.chat()` calls the router before the main graph runtime. If the route says multi-agent should run, Evolva runs `collaborate_report()`, records a `task_route` trace event, stores a compact context note, then continues the main agent loop with that evidence available.

## Files To Change
- `evolva/agent/multi_agent.py`
- `evolva/agent/core.py`
- `evolva/config.py`
- `tests/test_agent_cli_workflow_mcp_eval_tui.py`
- `README.md`
- `README.en.md`
- `docs/dev-loop-runs/2026-06-23-task-router/*`

## Task Order
1. Add `TaskRoute` and `TaskRouter`.
2. Add config flags for auto routing and max automatic roles.
3. Wire router into `MultiAgentCoordinator`.
4. Wire pre-chat routing into `EvolvaAgent.chat()`.
5. Add trace/context recording.
6. Add tests for classification, role selection, explicit role preservation, and chat integration.
7. Update README.
8. Run targeted tests, full pytest, Ruff, and relevant mypy if needed.

## Test Strategy
- Unit tests:
  - simple tasks do not route to multi-agent.
  - research/coding/review/complex tasks select expected roles.
  - explicit roles still override routing.
- Integration tests:
  - complex `chat()` records `task_route` and context before main response.
  - disabled router skips auto collaboration.
- Verification:
  - targeted pytest for multi-agent / chat tests.
  - full pytest.
  - full Ruff.

## Risks
- Over-routing can add cost and latency; heuristics should remain conservative.
- Fake LLM tests can be sensitive to extra calls; tests should disable routing or use simple prompts where appropriate.
- Context injection should be compact to avoid bloating the main prompt.
