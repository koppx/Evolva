# Acceptance Report

## Verdict
PASS

## Scope Checked
- Runtime state defaults.
- Runtime config persistence helpers.
- LLM timeout config, transient retry, non-transient error boundary, and JSON validation.
- Sandbox writable roots and failure rollback.
- Policy profile overlays and JSONL audit logging.
- Trace-derived observability for policy audit, sandbox rollback, LLM latency, and LLM retry.
- Eval scorer coverage for metric fields and policy audit rows.
- Security eval gate coverage for sandbox rollback and policy audit.
- Workflow run persistence and resume of unchanged successful nodes.
- MCP schema cache, degraded cache fallback, health command, and observability signals.
- Memory / Skill governance for prompt injection, status updates, and audit summaries.
- Repo Index manifest, stale detection, incremental chunk reuse, runtime ignore boundaries, and status output.
- Multi-agent role budget validation, structured reports, failed-LLM fallback, and observability signals.
- Dream default staged apply, explicit legacy immediate apply, verifier-backed promotion, and promotion fingerprinting.
- Dream CLI/TUI status rendering for verification gate and promotion state.
- Repo-index and maintenance ignore boundaries.
- Existing state store, sandbox/policy/tool, and LLM/image regressions.

## Reviewers Run
Reduced inline acceptance review.

## Tests Run
- `uv run pytest tests/test_config_runtime_paths.py tests/test_state_stores.py tests/test_sandbox_policy_tools.py tests/test_llm_and_images.py -q`
- `uv run pytest tests/test_config_runtime_paths.py tests/test_llm_and_images.py tests/test_agent_cli_workflow_mcp_eval_tui.py::test_agent_uses_langgraph_runtime_for_llm_tool_loop -q`
- `uv run pytest tests/test_sandbox_policy_tools.py -q`
- `uv run pytest tests/test_config_runtime_paths.py tests/test_sandbox_policy_tools.py tests/test_core.py -q`
- `.venv/bin/python -m pytest tests/test_state_stores.py::test_trace_recorder_emits_metrics_and_alerts tests/test_agent_cli_workflow_mcp_eval_tui.py::test_eval_harness_score_summary_report_and_run_file tests/test_llm_and_images.py tests/test_sandbox_policy_tools.py -q`
- `.venv/bin/python -m evolva.cli eval evals/tasks/security.jsonl --yes --baseline evals/baselines/security.json --min-score 1.0 --no-regression`
- `.venv/bin/python -m pytest tests/test_agent_cli_workflow_mcp_eval_tui.py::test_workflow_engine_tool_role_agent_templates_and_errors tests/test_agent_cli_workflow_mcp_eval_tui.py::test_workflow_engine_runs_explicit_dag_and_rejects_cycles tests/test_agent_cli_workflow_mcp_eval_tui.py::test_workflow_engine_persists_and_resumes_successful_nodes tests/test_core.py::test_workflow_engine_tool_node -q`
- `.venv/bin/python -m pytest tests/test_agent_cli_workflow_mcp_eval_tui.py::test_mcp_manager_config_render_and_fake_client tests/test_agent_cli_workflow_mcp_eval_tui.py::test_mcp_manager_tool_cache_and_health tests/test_agent_cli_workflow_mcp_eval_tui.py::test_cli_parser_main_once_and_handle_commands tests/test_agent_cli_workflow_mcp_eval_tui.py::test_cli_mcp_cmd_json_error_and_success tests/test_config_runtime_paths.py -q`
- `.venv/bin/python -m pytest tests/test_state_stores.py::test_trace_recorder_emits_metrics_and_alerts tests/test_agent_cli_workflow_mcp_eval_tui.py::test_mcp_manager_tool_cache_and_health tests/test_agent_cli_workflow_mcp_eval_tui.py::test_cli_mcp_cmd_json_error_and_success -q`
- `.venv/bin/python -m pytest tests/test_state_stores.py::test_memory_search_ranks_exact_matches tests/test_state_stores.py::test_memory_governance_filters_context_and_tracks_status tests/test_state_stores.py::test_skill_store_seeds_sanitizes_and_appends tests/test_state_stores.py::test_skill_governance_filters_inactive_skills_and_audits tests/test_sandbox_policy_tools.py::test_builtin_file_memory_context_todo_and_policy_tools tests/test_config_runtime_paths.py::test_agent_config_reads_request_timeout_from_runtime_config -q`
- `.venv/bin/python -m pytest tests/test_repo_index.py tests/test_agent_cli_workflow_mcp_eval_tui.py::test_cli_parser_main_once_and_handle_commands -q`
- `.venv/bin/python -m pytest tests/test_agent_cli_workflow_mcp_eval_tui.py::test_multi_agent_roles_fallback_and_errors tests/test_agent_cli_workflow_mcp_eval_tui.py::test_multi_agent_reports_budget_and_llm_failure_fallback tests/test_sandbox_policy_tools.py::test_builtin_multi_agent_tools_return_structured_reports tests/test_state_stores.py::test_trace_recorder_emits_metrics_and_alerts -q`
- `.venv/bin/python -m pytest tests/test_dream.py -q`
- `.venv/bin/python -m pytest tests/test_agent_cli_workflow_mcp_eval_tui.py::test_cli_parser_main_once_and_handle_commands tests/test_agent_cli_workflow_mcp_eval_tui.py::test_tui_non_curses_command_completion_queue_and_confirmation -q`
- `.venv/bin/python -m pytest tests/test_agent_cli_workflow_mcp_eval_tui.py::test_cli_dream_cmd_integration -q`
- `uv run pytest -q`
- `.venv/bin/python -m pytest -q`
- `uv run ruff check .`
- `.venv/bin/python -m ruff check .`
- `.venv/bin/python -m ruff check evolva/agent/dream.py evolva/config.py tests/test_dream.py`
- `.venv/bin/python -m ruff check evolva/agent/dream.py evolva/cli.py evolva/tui.py tests/test_dream.py tests/test_agent_cli_workflow_mcp_eval_tui.py`

## Requirement Coverage
- Runtime state under `.evolva/`: covered by `test_agent_config_defaults_runtime_state_under_dot_evolva`.
- Temp-root relocation: covered by `test_agent_config_temp_root_relocates_default_runtime_paths`.
- Explicit overrides preserved: covered by `test_agent_config_preserves_explicit_runtime_paths`.
- Runtime config helper behavior: covered by `test_runtime_config_helpers_use_runtime_home_env`.
- Runtime timeout config: covered by `test_agent_config_reads_request_timeout_from_runtime_config`.
- LLM transient retry: covered by `test_llm_chat_retries_transient_http_errors`.
- LLM non-transient failure: covered by `test_llm_chat_does_not_retry_non_transient_http_errors`.
- LLM JSON validation: covered by `test_llm_chat_json_validates_required_keys`.
- Sandbox rollback on failed execution: covered by `test_sandbox_rolls_back_workspace_on_failed_python`.
- Sandbox success retention: covered by `test_sandbox_keeps_workspace_changes_on_success`.
- Writable roots: covered by `test_sandbox_writable_roots_restrict_file_tools`.
- Sandbox isolation env config: covered by `test_agent_config_reads_sandbox_isolation_env`.
- Policy custom profile rules and audit log: covered by `test_policy_custom_profile_rules_and_audit_log`.
- Policy file overlays: covered by `test_policy_file_extends_profiles_and_patterns`.
- Policy file config env: covered by `test_agent_config_reads_policy_file_env`.
- Trace observability signals: covered by `test_trace_recorder_emits_metrics_and_alerts`.
- MCP cache and degraded health: covered by `test_mcp_manager_tool_cache_and_health`.
- MCP health CLI/parser: covered by `test_cli_parser_main_once_and_handle_commands` and `test_cli_mcp_cmd_json_error_and_success`.
- Memory prompt governance: covered by `test_memory_governance_filters_context_and_tracks_status`.
- Skill prompt governance: covered by `test_skill_governance_filters_inactive_skills_and_audits`.
- Governance tools: covered by `test_builtin_file_memory_context_todo_and_policy_tools`.
- Repo Index manifest/stale/reuse/skipped diagnostics: covered by `tests/test_repo_index.py`.
- Multi-agent report/budget/fallback governance: covered by `test_multi_agent_reports_budget_and_llm_failure_fallback` and `test_builtin_multi_agent_tools_return_structured_reports`.
- Dream staged apply: covered by `test_dream_engine_apply_stages_candidates_until_verified`.
- Dream legacy immediate apply opt-out: covered by `test_dream_engine_legacy_apply_can_write_immediately`.
- Dream verifier-backed promotion: covered by `test_dream_verify_backlog_runs_eval_verifier_and_promotes`.
- Dream status rendering: covered by `test_dream_status_renders_gate_and_candidate_counts`, `test_cli_parser_main_once_and_handle_commands`, and `test_tui_non_curses_command_completion_queue_and_confirmation`.
- Eval metric field and policy audit matching: covered by `test_eval_harness_score_summary_report_and_run_file`.
- Security eval rollback gate: covered by `sandbox_rolls_back_failed_python_001` in `evals/tasks/security.jsonl`.
- Workflow checkpoint/resume: covered by `test_workflow_engine_persists_and_resumes_successful_nodes`.
- Existing behavior: covered by full test suite.

## Findings
No blockers or important issues remain.

## Residual Risks
- Historical ignored runtime files under `evolva/` may still exist locally; this change prevents new default writes there but does not delete local files.
- Examples that intentionally write task artifacts to `evolva/workspace` are not migrated in this slice.
- Snapshot rollback is best-effort and bounded by configured snapshot size; skipped large files are reported but not restored.
- Dream promotion quality depends on verifier strength; weak manual or overly broad Eval verifiers can still promote low-value lessons.

## Follow-ups
- P0 LLM: integrate `chat_json()` into planner/loop paths where strict JSON is required.
- P1 Workflow/Loop: add retry policy controls and richer run-state inspection in TUI.
- P3 UI/TUI: surface Dream candidate verification state and promotion history more clearly in the workbench.
