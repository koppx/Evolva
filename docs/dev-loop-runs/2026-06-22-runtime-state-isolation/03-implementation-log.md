# Implementation Log

## Changes
- Added `EVOLVA_RUNTIME_HOME`, `default_runtime_home()`, and `default_runtime_path()` in `evolva/config.py`.
- Changed runtime state defaults from `evolva/*` to `.evolva/*`.
- Preserved explicit constructor paths and relocated default paths when `AgentConfig(root=tmp_path)` is used.
- Moved default MCP server config path to runtime home while leaving `evolva/mcp/servers.example.json` as a tracked example.
- Added `.evolva/` to `.gitignore`, Ruff excludes, repo-index generated ignores, and maintenance generated-dir checks.
- Updated README runtime-state wording.
- Added `tests/test_config_runtime_paths.py`.
- Added runtime-config-backed `request_timeout`.
- Added `llm_max_retries` and `llm_retry_backoff` config knobs.
- Added transient HTTP/network retry handling to `OpenAICompatibleLLM.chat()`.
- Added `OpenAICompatibleLLM.chat_json()` required-key validation.
- Expanded `tests/test_llm_and_images.py`.
- Added `SandboxSnapshot`, writable-root checks, and rollback-on-failure execution wrapper.
- Added `EVOLVA_SANDBOX_WRITABLE_ROOTS`, `EVOLVA_SANDBOX_SNAPSHOT_ROOTS`, `EVOLVA_SANDBOX_ROLLBACK_ON_FAILURE`, and `EVOLVA_SANDBOX_MAX_SNAPSHOT_BYTES`.
- Updated `write_file` to use `sandbox.resolve_write()`.
- Expanded README safety docs and sandbox tests.
- Added `EVOLVA_POLICY_FILE` and runtime-home policy audit path.
- Added configurable Policy profile rules, JSON policy overlays, and compact JSONL audit logging.
- Wired Agent policy construction to policy file and audit file config.
- Expanded policy tests.
- Added LLM attempts/retries metadata to `LLMResponse` and `llm_response` trace events.
- Added `policy.audit`, `sandbox.rollback`, `llm.latency_ms`, and `llm.retry` metrics plus rollback/retry alert rules.
- Added Eval `policy_audit` scorer and metric field matching.
- Added security eval checks for policy audit and sandbox rollback.
- Added durable Workflow run files under runtime home with `running`, `failed`, and `completed` statuses.
- Added Workflow node fingerprinting and `resume=True` reuse of successful unchanged nodes.
- Added `WorkflowResult` run metadata and persisted result serialization.
- Added runtime-home MCP tool schema cache with TTL and stale-cache fallback on server failure.
- Added `mcp_health` tool plus `/mcp health` and `evolva mcp health` entry points.
- Added trace-derived `mcp.health` and `mcp.error` metrics plus an MCP error alert rule.
- Added active-only, confidence-gated Memory context injection with status updates and governance audit summaries.
- Added active-only Skill matching/context, metadata-first manifests, status updates, and Skill governance audit summaries.
- Added `memory_status`, `memory_audit`, `skill_status`, and `skill_audit` tools.
- Added Repo Index file manifest, skipped-file diagnostics, stale detection, and incremental unchanged-file chunk reuse.
- Added `repo_index_status` tool plus `/repo status` in CLI/TUI.
- Expanded generated/runtime directory ignores for default `.evolva/`, legacy `evolva/*`, and test runtime layouts.
- Added `AgentRoleResult` and `MultiAgentRun` reports with role status, latency, errors, and fallback markers.
- Added role de-duplication, unknown-role validation, empty-task validation, and `EVOLVA_MULTI_AGENT_MAX_ROLES` budget enforcement.
- Added trace-derived `multi_agent.run`, `multi_agent.role`, and `multi_agent.fallback` metrics plus fallback alerting.
- Added `EVOLVA_DREAM_REQUIRE_VERIFICATION`, defaulting Dream apply to staged verification before Memory / Skill writes.
- Added Dream verified-promotion flow so `/dream verify --promote` writes the evolution lesson and records the promotion fingerprint.
- Preserved legacy immediate Dream apply behind explicit `EVOLVA_DREAM_REQUIRE_VERIFICATION=0`.
- Added `/dream status` for CLI/TUI to show Dream verification gate state, candidate counts, pending verification, verified/promoted totals, and next action.

## Verification
- `python3 -m pytest ...` could not run because system Python has no `pytest`.
- `uv run pytest tests/test_config_runtime_paths.py tests/test_state_stores.py tests/test_sandbox_policy_tools.py tests/test_llm_and_images.py -q` passed: 42 passed.
- `uv run pytest tests/test_config_runtime_paths.py tests/test_llm_and_images.py tests/test_agent_cli_workflow_mcp_eval_tui.py::test_agent_uses_langgraph_runtime_for_llm_tool_loop -q` passed: 19 passed.
- `uv run pytest tests/test_sandbox_policy_tools.py -q` passed: 14 passed.
- `uv run pytest tests/test_config_runtime_paths.py tests/test_sandbox_policy_tools.py tests/test_core.py -q` passed: 39 passed.
- `uv run pytest tests/test_config_runtime_paths.py tests/test_sandbox_policy_tools.py tests/test_core.py -q` passed: 42 passed.
- `uv run pytest -q` passed: 153 passed, 1 skipped.
- `uv run ruff check .` passed.
- `.venv/bin/python -m pytest tests/test_state_stores.py::test_trace_recorder_emits_metrics_and_alerts tests/test_agent_cli_workflow_mcp_eval_tui.py::test_eval_harness_score_summary_report_and_run_file tests/test_llm_and_images.py tests/test_sandbox_policy_tools.py -q` passed: 31 passed.
- `.venv/bin/python -m evolva.cli eval evals/tasks/security.jsonl --yes --baseline evals/baselines/security.json --min-score 1.0 --no-regression` passed: 8/8.
- `.venv/bin/python -m pytest tests/test_agent_cli_workflow_mcp_eval_tui.py::test_workflow_engine_tool_role_agent_templates_and_errors tests/test_agent_cli_workflow_mcp_eval_tui.py::test_workflow_engine_runs_explicit_dag_and_rejects_cycles tests/test_agent_cli_workflow_mcp_eval_tui.py::test_workflow_engine_persists_and_resumes_successful_nodes tests/test_core.py::test_workflow_engine_tool_node -q` passed: 4 passed.
- `.venv/bin/python -m pytest tests/test_agent_cli_workflow_mcp_eval_tui.py::test_mcp_manager_config_render_and_fake_client tests/test_agent_cli_workflow_mcp_eval_tui.py::test_mcp_manager_tool_cache_and_health tests/test_agent_cli_workflow_mcp_eval_tui.py::test_cli_parser_main_once_and_handle_commands tests/test_agent_cli_workflow_mcp_eval_tui.py::test_cli_mcp_cmd_json_error_and_success tests/test_config_runtime_paths.py -q` passed: 11 passed.
- `.venv/bin/python -m pytest tests/test_state_stores.py::test_trace_recorder_emits_metrics_and_alerts tests/test_agent_cli_workflow_mcp_eval_tui.py::test_mcp_manager_tool_cache_and_health tests/test_agent_cli_workflow_mcp_eval_tui.py::test_cli_mcp_cmd_json_error_and_success -q` passed: 3 passed.
- `.venv/bin/python -m pytest tests/test_state_stores.py::test_memory_search_ranks_exact_matches tests/test_state_stores.py::test_memory_governance_filters_context_and_tracks_status tests/test_state_stores.py::test_skill_store_seeds_sanitizes_and_appends tests/test_state_stores.py::test_skill_governance_filters_inactive_skills_and_audits tests/test_sandbox_policy_tools.py::test_builtin_file_memory_context_todo_and_policy_tools tests/test_config_runtime_paths.py::test_agent_config_reads_request_timeout_from_runtime_config -q` passed: 6 passed.
- `.venv/bin/python -m pytest tests/test_repo_index.py tests/test_agent_cli_workflow_mcp_eval_tui.py::test_cli_parser_main_once_and_handle_commands -q` passed: 7 passed.
- `.venv/bin/python -m pytest tests/test_agent_cli_workflow_mcp_eval_tui.py::test_multi_agent_roles_fallback_and_errors tests/test_agent_cli_workflow_mcp_eval_tui.py::test_multi_agent_reports_budget_and_llm_failure_fallback tests/test_sandbox_policy_tools.py::test_builtin_multi_agent_tools_return_structured_reports tests/test_state_stores.py::test_trace_recorder_emits_metrics_and_alerts -q` passed: 4 passed.
- `.venv/bin/python -m pytest -q` passed: 163 passed, 1 skipped.
- `.venv/bin/python -m ruff check .` passed.
- `.venv/bin/python -m pytest tests/test_dream.py -q` passed: 14 passed.
- `.venv/bin/python -m pytest tests/test_agent_cli_workflow_mcp_eval_tui.py::test_cli_parser_main_once_and_handle_commands tests/test_agent_cli_workflow_mcp_eval_tui.py::test_tui_non_curses_command_completion_queue_and_confirmation -q` passed: 2 passed.
- `.venv/bin/python -m pytest tests/test_agent_cli_workflow_mcp_eval_tui.py::test_cli_dream_cmd_integration -q` passed: 1 passed.
- `.venv/bin/python -m ruff check evolva/agent/dream.py evolva/config.py tests/test_dream.py` passed.
- `.venv/bin/python -m ruff check evolva/agent/dream.py evolva/cli.py evolva/tui.py tests/test_dream.py tests/test_agent_cli_workflow_mcp_eval_tui.py` passed.

## Notes
The first `uv run` needed access to the user-level uv cache outside the workspace, so tests were rerun with escalated filesystem permission.
