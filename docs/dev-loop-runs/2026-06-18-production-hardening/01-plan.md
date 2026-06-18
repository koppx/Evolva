# Implementation Plan

## Architecture Summary
Introduce a production safety control path:

`Tool/Loop/MCP request -> Capability Policy -> Structured Sandbox Runner -> Redacted Trace -> Metrics/Alerts -> Atomic State/Artifact Store -> Eval/CI tests`

## Modules And Delivery Order
1. Policy capability model
   - Add capability enums/metadata and richer `PolicyDecision`.
   - Update builtin tools to declare capabilities.
   - Verification: policy tests for profile behavior, unknown tools, path/network/shell decisions.

2. Structured sandbox runner
   - Add `CommandSpec`/parser.
   - Reject shell control operators and execute with `shell=False`.
   - Add output truncation and metadata.
   - Add optional Docker/container backend with disabled network, read-only container root, tmpfs, memory/CPU/pids limits, and non-root user mapping.
   - Add fixed sandbox smoke checks via `Sandbox.smoke_check()`, interactive `/sandbox smoke`, and `evolva sandbox smoke`.
   - Verification: command parsing, allowlist, dangerous command, timeout, cwd escape, backend selection, generated Docker argv, missing Docker handling, and fixed smoke command success/failure.

3. Trace redaction
   - Add reusable redactor.
   - Apply redaction in `TraceRecorder.event()` and `TraceRecorder.end()`.
   - Verification: known secrets never appear in trace files.

4. Atomic state stores
   - Add atomic JSON/JSONL helpers.
   - Migrate memory/context/todo/artifact writes.
   - Verification: corrupt JSON recovery, atomic update, append behavior.

5. MCP supervisor hardening
   - Add request timeout, max message size, non-blocking stderr tail.
   - Persist timeout/message-size limits with atomic config writes.
   - Ensure config env is redacted in traces through common redactor.
   - Verification: fake MCP timeout, oversized message failures, config reload, and security eval timeout signal.

6. Loop/workflow integration tests
   - Ensure command gate still works with new sandbox.
   - Ensure policy decisions are traced with capabilities.

7. Artifact lifecycle controls
   - Add manifest size/record limits, digest verification, and manifest pruning.
   - Verification: record oversize rejection, digest verification, and deterministic pruning.

8. Eval and CI gates
   - Add a security eval suite for command denial, shell control rejection, path escape denial, trace redaction, MCP timeout observability, and corrupt-state recovery.
   - Add metric and safe glob scorers so evals can verify operational signals and recovery artifacts.
   - Add Python-version CI matrix with lint, scoped type checks, coverage, package build, and eval gates.
   - Verification: ruff, mypy, coverage, build, smoke eval, repo-index eval, and security eval.

9. Metrics and alert hooks
   - Add a local JSONL metrics sink and alert-rule evaluator.
   - Derive metrics from trace events for policy decisions, denials, redaction hits, tool calls, latency, failures, MCP timeouts, and artifact errors.
   - Add human-readable metrics/alerts rendering, Prometheus text export, interactive `/metrics` commands, and `evolva metrics` automation commands.
   - Verification: sink-level metric/alert/export tests, TraceRecorder integration tests, agent-level tool-call metric tests, and CLI parser/command tests.

## Test Strategy
- Unit tests for each new helper and edge case.
- Integration tests through `EvolvaAgent._call_tool`, `LoopRunner`, and `TraceRecorder`.
- Failure tests for denied commands, corrupt state, MCP timeout, redaction fallback.

## Exact Verification Commands
- `uv run pytest tests/test_sandbox_policy_tools.py tests/test_state_stores.py tests/test_agent_cli_workflow_mcp_eval_tui.py tests/test_loops.py -q`
- `uv run pytest -q`
- `uv run --extra dev ruff check evolva tests`
- `uv run --extra dev mypy evolva/agent/capabilities.py evolva/agent/observability.py evolva/agent/redaction.py evolva/agent/sandbox.py evolva/storage.py evolva/agent/mcp.py evolva/eval/scorers.py evolva/tools/builtin.py`
- `uv run --extra dev coverage run -m pytest -q`
- `uv run --extra dev coverage report`
- `uv run --extra dev python -m build`
- `uv run --extra dev python -m evolva.cli eval evals/tasks/smoke.jsonl --yes --baseline evals/baselines/smoke.json --min-score 1.0 --no-regression`
- `uv run --extra dev python -m evolva.cli eval evals/tasks/repo_index.jsonl --yes --baseline evals/baselines/repo_index.json --min-score 1.0 --no-regression`
- `uv run --extra dev python -m evolva.cli eval evals/tasks/security.jsonl --yes --baseline evals/baselines/security.json --min-score 1.0 --no-regression`

## Known Risks
- Existing tests or README examples may assume raw shell strings with shell syntax. The compatibility layer should allow simple commands while rejecting shell operators.
- File locking differs by platform. This first pass targets Unix/macOS with a no-op fallback where `fcntl` is unavailable.

## Acceptance Mapping
- Requirements 1-2 map to modules 1-2.
- Requirement 3 maps to module 3.
- Requirement 4 maps to module 4.
- Requirement 5 maps to module 5.
- Requirement 6 maps to modules 1-9 test, eval, CI, and observability updates.
