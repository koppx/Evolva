# Plan

## Architecture Summary
Extend `MultiAgentCoordinator` with an optional governed tool runner. The runner is attached by `EvolvaAgent` after the main `ToolRegistry` is built, and points to `EvolvaAgent._call_tool()`. This keeps all sub-agent tool calls inside the same Policy, confirmation, Sandbox, Trace, and artifact code path used by the main agent.

Each role receives a conservative tool allowlist:
- `planner`: status/context/todo/repo status.
- `researcher`: read/search tools plus web search.
- `coder`: read/search/status plus sandboxed Python.
- `reviewer`: read/search/status plus sandboxed Python.

The sub-agent loop asks the LLM for one JSON action per step:

```json
{"thought": "...", "tool": {"name": "read_file", "args": {"path": "README.md"}}, "final": null}
```

or:

```json
{"thought": "...", "tool": null, "final": "answer"}
```

The loop stops on final output, tool denial/failure, malformed tool requests, or `EVOLVA_MULTI_AGENT_TOOL_STEPS`.

## Files To Change
- `evolva/agent/multi_agent.py`
- `evolva/agent/core.py`
- `evolva/config.py`
- `README.md`
- `README.en.md`
- `tests/test_agent_cli_workflow_mcp_eval_tui.py`
- `tests/test_sandbox_policy_tools.py`
- `docs/dev-loop-runs/2026-06-23-sub-agent-tools/*`

## Task Order
1. Add config for max sub-agent tool steps.
2. Add role tool scopes and tool call summary structures.
3. Attach the main governed tool runner after registry construction.
4. Implement the bounded sub-agent JSON tool loop.
5. Add unit/regression tests for allowed tools, denied tools, and report serialization.
6. Update README production notes.
7. Run targeted tests, full pytest, and Ruff.

## Test Strategy
- Unit tests:
  - Allowed researcher tool call reads a file and returns final answer.
  - Denied researcher write attempt fails before the file is created.
  - Collaboration reports include per-role `tool_calls`.
- Regression tests:
  - Existing fallback and max-role behavior remains intact.
  - Builtin `delegate_agent`/`collaborate` tool data remains structured.
- Verification commands:
  - `.venv/bin/python -m pytest tests/test_agent_cli_workflow_mcp_eval_tui.py::test_multi_agent_reports_budget_and_llm_failure_fallback tests/test_agent_cli_workflow_mcp_eval_tui.py::test_sub_agent_can_call_allowed_tools_through_governed_runner tests/test_agent_cli_workflow_mcp_eval_tui.py::test_sub_agent_rejects_tools_outside_role_scope tests/test_sandbox_policy_tools.py::test_builtin_multi_agent_tools_return_structured_reports -q`
  - `.venv/bin/python -m pytest -q`
  - `.venv/bin/python -m ruff check .`

## Risks
- A cyclic dependency exists between the coordinator and tool registry; attaching the runner after registry construction avoids it.
- Tool outputs can be large; the loop records bounded summaries.
- Allowing write/shell/MCP by default would be too risky; those remain excluded from role scopes.
