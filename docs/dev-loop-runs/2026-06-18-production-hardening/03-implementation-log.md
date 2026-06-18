# Implementation Log

## Start State
- Branch: `main`
- Base SHA: `c1a1c1cdff424360ca2e285ac0b23ed05d21f6f8`
- Dirty state: untracked `lark_auth/` only, not touched.

## Tasks
- [x] Policy capability model
- [x] Structured sandbox runner
- [x] Optional container sandbox backend
- [x] Trace redaction
- [x] Atomic state stores
- [x] MCP supervisor hardening
- [x] Artifact lifecycle controls
- [x] Security eval and CI gates
- [x] Metrics and alert hooks
- [x] Tests and verification

## Changes
- Added `evolva/agent/capabilities.py` with capability enums and default tool capability mapping.
- Extended `Tool` metadata and builtin tool registration to declare capabilities.
- Upgraded `PolicyDecision` to include capabilities, redactions, and audit tags; added profile-aware denials for `safe` and `prod`.
- Reworked sandbox shell execution to parse commands into `CommandSpec`, reject shell control operators, execute with `shell=False`, and return bounded structured metadata.
- Added `DockerWorkspaceBackend` and backend selection for `EVOLVA_SANDBOX_BACKEND=docker|container`, including bind-mounted workspace, disabled container network by default, read-only container root, tmpfs `/tmp`, memory/CPU/pids limits, user mapping, missing-Docker handling, and backend details in `sandbox_info`.
- Added config knobs for container image, network, read-only root, memory, CPUs, pids limit, and user.
- Added fixed sandbox smoke validation through `Sandbox.smoke_check()`, `/sandbox smoke`, and `evolva sandbox smoke` so pre-prod can verify the configured backend without accepting arbitrary commands.
- Added `evolva/agent/redaction.py` and applied redaction to trace events and final answers before persistence.
- Added `evolva/storage.py` with file locks, atomic JSON writes, fsync-backed JSONL append helpers, corrupt JSON quarantine, and read-modify-write update helpers.
- Migrated memory, context, todo, artifact, and trace persistence to the storage helpers.
- Hardened MCP stdio reads with request timeout, max message size, non-blocking stderr tail, timeout-triggered process cleanup, atomic config persistence, and persisted timeout/message-size knobs.
- Extended artifact manifests with max file size, max record count, digest verification, and metadata pruning.
- Added security eval tasks and baselines covering destructive command denial, shell-control rejection, path escape denial, trace redaction, MCP timeout observability, and corrupt-state recovery.
- Extended eval trace scorers to bind checks to the exact trace run produced by a task, and added metric/file-glob scorers for operational signal and recovery artifact validation.
- Added CI gates for Python 3.10/3.11/3.12, ruff, scoped mypy, coverage, package build, and smoke/repo/security evals.
- Added `evolva/agent/observability.py` with JSONL metrics, alert rules, alert dedupe, recent metric/alert readers, and default rules for policy denials, tool failures, tool errors, MCP timeouts, and artifact errors.
- Connected `TraceRecorder` to observability so trace events emit metrics for policy decisions, redaction hits, tool calls, latency, failed tools, MCP timeouts, and artifact errors.
- Added config paths for `evolva/metrics/metrics.jsonl` and `evolva/metrics/alerts.jsonl`, plus `EVOLVA_OBSERVABILITY`.
- Added human-readable metrics/alerts rendering and Prometheus text export from the local JSONL sink.
- Added interactive `/metrics`, `/metrics alerts`, `/metrics prometheus` commands and automation commands `evolva metrics list|alerts|prometheus`.
- Routed fallback-mode `list_files`, `read_file`, and `web_search` through `_call_tool()` so policy, tracing, metrics, and alerts remain active even without an LLM.
- Added focused unit/integration/failure tests for policy capabilities, sandbox parsing, trace redaction, corrupt-state recovery, concurrent todo writes, MCP timeout/oversize, and loop compatibility.
- Added `06-technical-scheme.md`, a Chinese module-by-module production technical scheme organized as function, verification, tests, and observability.

## Commands
- `PYTHONPYCACHEPREFIX=/private/tmp/evolva-pycache python3 -m compileall evolva`
  - Result: pass.
- `git diff --check`
  - Result: pass.
- `uv run pytest tests/test_sandbox_policy_tools.py tests/test_state_stores.py tests/test_agent_cli_workflow_mcp_eval_tui.py tests/test_loops.py -q`
  - Result: `86 passed, 1 skipped in 5.70s`.
- `uv run pytest -q`
  - Result: `131 passed, 1 skipped in 5.04s`.
- `uv run --extra dev ruff check evolva tests`
  - Result: pass, `All checks passed!`.
- `uv run --extra dev mypy evolva/agent/capabilities.py evolva/agent/observability.py evolva/agent/redaction.py evolva/agent/sandbox.py evolva/storage.py evolva/agent/mcp.py evolva/eval/scorers.py evolva/tools/builtin.py`
  - Result: pass, `Success: no issues found in 8 source files`.
- `uv run --extra dev coverage run -m pytest -q`
  - Result: `138 passed, 1 skipped in 7.13s`.
- `uv run --extra dev coverage report`
  - Result: pass, total coverage `80%` against `fail_under = 75`.
- `uv run --extra dev python -m build`
  - Result: pass, source distribution and wheel built.
- `uv run --extra dev python -m evolva.cli eval evals/tasks/smoke.jsonl --yes --baseline evals/baselines/smoke.json --min-score 1.0 --no-regression`
  - Result: pass, `2/2` tasks met baseline and minimum score.
- `uv run --extra dev python -m evolva.cli eval evals/tasks/repo_index.jsonl --yes --baseline evals/baselines/repo_index.json --min-score 1.0 --no-regression`
  - Result: pass, `2/2` tasks met baseline and minimum score.
- `uv run --extra dev python -m evolva.cli eval evals/tasks/security.jsonl --yes --baseline evals/baselines/security.json --min-score 1.0 --no-regression`
  - Result: pass, `7/7` tasks met baseline and minimum score.
- `uv run --extra dev pytest tests/test_state_stores.py tests/test_core.py -q`
  - Result: `36 passed in 0.82s` after adding fsync to JSONL append, observability tests, and fallback policy routing coverage.
- `uv run --extra dev pytest tests/test_sandbox_policy_tools.py -q`
  - Result: `11 passed in 0.26s` after adding Docker backend selection, argv, resource-limit, and missing-Docker tests.
- `uv run --extra dev pytest tests/test_state_stores.py tests/test_agent_cli_workflow_mcp_eval_tui.py -q`
  - Result: `50 passed, 1 skipped in 4.76s` after adding eval metric/glob scorers and MCP timeout config persistence coverage.
- `uv run --extra dev pytest tests/test_sandbox_policy_tools.py tests/test_agent_cli_workflow_mcp_eval_tui.py -q`
  - Result: `44 passed, 1 skipped in 3.67s` after adding sandbox smoke and CLI coverage.

## Notes
- A first `python3 -m compileall evolva` attempt failed because macOS Python tried to write bytecode under `/Users/bytedance/Library/Caches`, which is outside the sandbox. Re-running with `PYTHONPYCACHEPREFIX=/private/tmp/evolva-pycache` passed.
- `uv run pytest` required elevated execution because `uv` needs user-level cache access under `~/.cache/uv`.
- Full-repo mypy is intentionally not enabled yet because the existing codebase has legacy typing debt. CI starts with scoped type checks for the newly added production primitives and leaves full migration as a tracked follow-up.
- Docker backend tests validate generated `docker run` command structure without requiring a Docker daemon in CI. A real daemon smoke test should be added to deployment/pre-prod where Docker is available.
