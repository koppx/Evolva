# Plan

## Architecture Summary
Introduce a runtime home abstraction in `evolva.config`. Runtime home defaults to `<repo>/.evolva`, with `EVOLVA_RUNTIME_HOME` as the override. All runtime state defaults derive from this home, while explicit constructor paths remain untouched.

Add bounded LLM retry behavior in `evolva.agent.llm`: retry transient HTTP/network failures, preserve existing temperature fallback behavior, and expose a `chat_json()` helper for structured output validation.

Add sandbox isolation controls: explicit writable roots for file tools and best-effort file snapshots that roll back failed shell/Python executions without changing successful command behavior.

Add policy configuration and audit logging: allow profile rules to deny capabilities or override shell/network behavior, load JSON overlays from `EVOLVA_POLICY_FILE`, and write compact decision audit records.

Promote P0 runtime signals into P1 verification: derive metrics/alerts from policy audit, sandbox rollback, LLM retry, and LLM latency trace events; extend Eval scorers to assert metric fields and policy audit rows; add a security regression task for sandbox rollback.

Add durable Workflow execution state: persist each workflow run under runtime home, record per-node status/output/error, and support resume by reusing successful nodes only when their node fingerprints and dependencies still match.

Add MCP production hardening: persist tool schema cache under runtime home, use it for bounded degradation, expose health checks through tools/CLI/TUI, and emit MCP health/error metrics from trace events.

Add Memory / Skill governance: make evidence/status/version fields enforce prompt injection boundaries, add audit/status tools, and keep historical records visible without allowing draft, low-confidence, disabled, or quarantined entries to influence Agent behavior.

Add Repo Index production hardening: persist file manifests and skipped-file diagnostics, reuse unchanged chunks during rebuild, detect stale indexes from file metadata, ignore runtime artifact directories, and expose status through tool/CLI/TUI paths.

Add Multi-agent collaboration governance: preserve the existing role-agent interface, add structured delegate/collaboration reports, enforce role budgets and validation, capture failed-LLM fallback as data, and emit observability signals.

Add Dream / Self-Evolution verification gating: keep candidate discovery local and auditable, make `dream apply` stage high-confidence candidates by default, require `dream verify --promote` before writing Memory / Skill, and keep an explicit config escape hatch for legacy immediate promotion.

Add a narrow UI/TUI production status enhancement: expose Dream gate state, candidate counts, pending verification, verified/promoted totals, and next operator action through `/dream status`.

## Files To Change
- `evolva/config.py`
- `.gitignore`
- `pyproject.toml`
- `evolva/agent/repo_index.py`
- `evolva/maintenance/optimizer.py`
- `README.md`
- `README.en.md`
- `tests/test_config_runtime_paths.py`
- `evolva/agent/llm.py`
- `tests/test_llm_and_images.py`
- `evolva/agent/sandbox.py`
- `evolva/tools/builtin.py`
- `tests/test_sandbox_policy_tools.py`
- `evolva/agent/policy.py`
- `evolva/agent/core.py`
- `evolva/agent/tracing.py`
- `evolva/agent/observability.py`
- `evolva/agent/langgraph_runtime.py`
- `evolva/eval/scorers.py`
- `evals/tasks/security.jsonl`
- `evals/baselines/security.json`
- `evolva/workflow/engine.py`
- `tests/test_agent_cli_workflow_mcp_eval_tui.py`
- `evolva/agent/mcp.py`
- `evolva/cli.py`
- `evolva/tui.py`
- `evolva/agent/memory.py`
- `evolva/agent/skills.py`
- `evolva/agent/repo_index.py`
- `tests/test_repo_index.py`
- `evolva/agent/multi_agent.py`
- `evolva/agent/dream.py`
- `tests/test_dream.py`

## Task Order
1. Add `default_runtime_home()` and `default_runtime_path()`.
2. Move `AgentConfig` runtime defaults to runtime home.
3. Preserve explicit runtime path overrides.
4. Update ignore/index/maintenance boundaries.
5. Document runtime home behavior.
6. Add unit tests for default paths, temp-root relocation, explicit overrides, and runtime config helper behavior.
7. Add LLM tests for runtime timeout, transient retry, non-transient failure, and JSON required-key validation.
8. Add sandbox tests for rollback-on-failure, successful-change retention, writable-root denial, and AgentConfig isolation env parsing.
9. Add policy tests for custom profile rules, policy file overlays, and JSONL audit logs.
10. Add observability and eval tests for policy audit, sandbox rollback, LLM retry, and metric field matching.
11. Update security eval baseline.
12. Add workflow run checkpointing and resume tests.
13. Add MCP tool schema cache, health checks, CLI/TUI command entry, and observability tests.
14. Add Memory / Skill prompt-injection governance and status/audit tools.
15. Add Repo Index manifest, incremental reuse, stale detection, status command, and tests.
16. Add Multi-agent run reports, role budget validation, fallback observability, and tests.
17. Add Dream verification gating and paired tests for staged apply, legacy immediate apply, and verified promotion.
18. Add Dream status rendering in CLI/TUI and paired tests.
19. Run targeted eval gate, Dream tests, CLI/TUI tests, full test suite, and Ruff.

## Test Strategy
- Unit tests: `tests/test_config_runtime_paths.py`, `tests/test_llm_and_images.py`, `tests/test_sandbox_policy_tools.py`.
- Regression tests: state stores, sandbox/policy/tools, LLM/images, workflow DAG execution, MCP manager/CLI/TUI, Memory / Skill governance, Repo Index manifest/stale/status, Multi-agent reports/fallbacks.
- Dream tests: `tests/test_dream.py` covers default staged apply, explicit legacy immediate apply, verifier execution, promotion fingerprinting, CLI rendering, and backlog persistence.
- CLI/TUI tests: `tests/test_agent_cli_workflow_mcp_eval_tui.py` covers `/dream status` command routing and workbench rendering.
- Full project check: `uv run pytest -q`.

## Risks
- Path defaults are dataclass defaults, so root-specific relocation must happen in `__post_init__`.
- Existing docs and examples may still mention `evolva/workspace`; this slice only changes runtime storage defaults, not every historical example path.
