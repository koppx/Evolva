# Implementation Log

## Changes
- Added `AgentConfig.multi_agent_tool_steps` with `EVOLVA_MULTI_AGENT_TOOL_STEPS`.
- Added role-level tool allowlists to `AgentRole`.
- Added `tool_calls` to `AgentRoleResult`.
- Added `MultiAgentCoordinator.attach_tools()` so `EvolvaAgent` can attach the governed `_call_tool()` runner after registry construction.
- Implemented a bounded sub-agent JSON tool loop with one tool call per step and final-answer termination.
- Rejected tools outside the role allowlist before execution.
- Kept all allowed tool execution inside the main Policy / approval / Sandbox / Trace path.
- Updated README multi-agent production notes.
- Added tests for allowed sub-agent tool calls, denied tool calls, and structured report serialization.

## Verification
- `.venv/bin/python -m pytest tests/test_agent_cli_workflow_mcp_eval_tui.py::test_multi_agent_reports_budget_and_llm_failure_fallback tests/test_agent_cli_workflow_mcp_eval_tui.py::test_sub_agent_can_call_allowed_tools_through_governed_runner tests/test_agent_cli_workflow_mcp_eval_tui.py::test_sub_agent_rejects_tools_outside_role_scope tests/test_sandbox_policy_tools.py::test_builtin_multi_agent_tools_return_structured_reports -q` passed: 4 passed.
- `.venv/bin/python -m ruff check evolva/agent/multi_agent.py evolva/agent/core.py evolva/config.py tests/test_agent_cli_workflow_mcp_eval_tui.py tests/test_sandbox_policy_tools.py` passed.
- `.venv/bin/python -m pytest -q` passed: 165 passed, 1 skipped.
- `.venv/bin/python -m ruff check .` passed.
