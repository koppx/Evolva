# Acceptance Report

## Verdict
PASS_WITH_NOTES

## Scope Checked
- Capability policy model and tool metadata.
- Structured sandbox command execution.
- Optional Docker/container sandbox backend.
- Fixed sandbox smoke checks for deployment/pre-prod backend validation.
- Trace redaction.
- Atomic state persistence.
- MCP request lifecycle hardening.
- MCP timeout/message-size config persistence.
- Artifact manifest lifecycle limits and verification.
- Eval harness trace binding and security evals.
- Eval metric and safe-glob scorers for observability and recovery artifact checks.
- Local metrics and alert hooks derived from trace events.
- Prometheus-style metrics export and CLI/interactive metrics inspection.
- Fallback-mode tool calls use the same policy, tracing, metric, and alert path as normal agent tool calls.
- CI quality gates for lint, typing, coverage, build, and eval regression.
- Focused and full regression tests.
- Chinese technical scheme organized by module with function, verification, tests, and observability.

## Reviewers Run
- Reduced inline requirements review
- Reduced inline test strategy review
- Reduced inline risk review

## Tests Run
- `PYTHONPYCACHEPREFIX=/private/tmp/evolva-pycache python3 -m compileall evolva` - PASS.
- `git diff --check` - PASS.
- `uv run pytest tests/test_sandbox_policy_tools.py tests/test_state_stores.py tests/test_agent_cli_workflow_mcp_eval_tui.py tests/test_loops.py -q` - PASS, `86 passed, 1 skipped`.
- `uv run pytest -q` - PASS, `131 passed, 1 skipped`.
- `uv run --extra dev ruff check evolva tests` - PASS.
- `uv run --extra dev mypy evolva/agent/capabilities.py evolva/agent/observability.py evolva/agent/redaction.py evolva/agent/sandbox.py evolva/storage.py evolva/agent/mcp.py evolva/eval/scorers.py evolva/tools/builtin.py` - PASS.
- `uv run --extra dev coverage run -m pytest -q` - PASS, `138 passed, 1 skipped`.
- `uv run --extra dev coverage report` - PASS, total coverage `80%` against `fail_under = 75`.
- `uv run --extra dev python -m build` - PASS.
- `uv run --extra dev python -m evolva.cli eval evals/tasks/smoke.jsonl --yes --baseline evals/baselines/smoke.json --min-score 1.0 --no-regression` - PASS, `2/2`.
- `uv run --extra dev python -m evolva.cli eval evals/tasks/repo_index.jsonl --yes --baseline evals/baselines/repo_index.json --min-score 1.0 --no-regression` - PASS, `2/2`.
- `uv run --extra dev python -m evolva.cli eval evals/tasks/security.jsonl --yes --baseline evals/baselines/security.json --min-score 1.0 --no-regression` - PASS, `7/7`.
- `uv run --extra dev pytest tests/test_state_stores.py tests/test_core.py -q` - PASS, `36 passed`.
- `uv run --extra dev pytest tests/test_sandbox_policy_tools.py -q` - PASS, `11 passed`.
- `uv run --extra dev pytest tests/test_state_stores.py tests/test_agent_cli_workflow_mcp_eval_tui.py -q` - PASS, `50 passed, 1 skipped`.
- `uv run --extra dev pytest tests/test_sandbox_policy_tools.py tests/test_agent_cli_workflow_mcp_eval_tui.py -q` - PASS, `44 passed, 1 skipped`.

## Requirement Coverage
- Policy decisions include capabilities, audit tags, risk, confirmation requirement, and denial reason: covered by `tests/test_sandbox_policy_tools.py`.
- Shell command execution rejects shell control operators and executes with `shell=False`: covered by sandbox parser/execution tests.
- Container sandbox backend is selectable, constructs structured `docker run` argv without a shell, disables network by default, sets read-only root/tmpfs/resource/user limits, and handles missing Docker: covered by `tests/test_sandbox_policy_tools.py`.
- Sandbox backend can be smoke-tested through fixed diagnostic code and CLI/interactive commands: covered by `tests/test_sandbox_policy_tools.py` and `tests/test_agent_cli_workflow_mcp_eval_tui.py`.
- Trace files do not persist known secret patterns: covered by `test_trace_recorder_redacts_secret_payloads`.
- Memory, context, todo, artifact, and trace stores use atomic storage helpers: implemented and covered by corrupt recovery/concurrent update tests.
- MCP request path supports timeout, bounded message size, and persisted timeout/message-size config: covered by MCP timeout, oversized-message, and config-reload tests.
- Artifact lifecycle has size limits, manifest count limits, digest verification, and pruning: covered by `tests/test_core.py`.
- Security eval gate covers command denial, shell injection rejection, path escape denial, persisted-trace redaction, MCP timeout metrics, and corrupt-state recovery: covered by `evals/tasks/security.jsonl`.
- Metrics and alerts are emitted for policy denials, redaction hits, tool failures, MCP timeouts, and artifact errors: covered by `tests/test_state_stores.py` and agent-level metric assertions in `tests/test_core.py`.
- Metrics can be inspected interactively and exported as Prometheus text for monitoring integration: covered by `tests/test_state_stores.py` and `tests/test_agent_cli_workflow_mcp_eval_tui.py`.
- Fallback-mode file reads route through policy and emit denial metrics/alerts for path escape attempts: covered by `test_fallback_chat_routes_file_reads_through_policy`.
- CI now installs dev dependencies and runs lint, scoped type checks, compile, coverage, build, and eval regression gates.
- Loop command gate remains compatible: covered by focused loop regression tests.
- `06-technical-scheme.md` maps each production-hardening module to goal, input, output, dependencies, function, validation criteria, test design, and observability hooks.

## Findings
- No blocking findings remain.
- Important note: Docker/container isolation is implemented as an optional backend and has unit/CLI coverage; live-daemon validation is exposed through `evolva sandbox smoke` and should run in the target pre-prod environment.

## Fixes Applied
- Added capability metadata and profile-aware policy.
- Added structured command parsing/execution.
- Added optional Docker/container sandbox backend with production-oriented defaults and config knobs.
- Added fixed sandbox smoke checks for local and Docker/container backend validation.
- Added trace redaction before persistence.
- Added atomic storage helpers and migrated core stores.
- Added MCP read timeout and message size limits.
- Added atomic MCP config persistence for timeout and message-size knobs.
- Added artifact manifest limits, verification, and pruning.
- Added security evals, exact trace-run scorer binding, and CI quality gates.
- Added metric and safe-glob eval scorers for observability and recovery validation.
- Added local JSONL metrics and alert rules connected to trace events.
- Added Prometheus text export and CLI/interactive metrics inspection.
- Removed a fallback-mode policy bypass for direct list/read/search interactions.
- Added regression tests for the new production-hardening behavior.

## Residual Risks
- The default backend remains local for developer compatibility; container isolation is available by configuration and smoke-testable, but CI still does not run against a live Docker daemon.
- File locking is robust for local Unix/macOS use; distributed or network filesystem semantics are not covered.
- Redaction is best-effort pattern-based and should be expanded with project-specific secret detectors over time.
- CI uses scoped mypy checks for new production primitives; full-repo typing remains a migration item.

## Follow-ups
- Run `EVOLVA_SANDBOX_BACKEND=docker evolva sandbox smoke` in pre-prod/live Docker-enabled runtime and wire it into deployment gates.
- Add OpenTelemetry or hosted logging adapters if the deployment target needs push-based telemetry in addition to Prometheus text export.
- Expand security eval coverage for project-specific secret formats.
- Gradually migrate the full repository to mypy rather than limiting type checks to newly hardened primitives.
