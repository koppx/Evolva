# Requirements Baseline

## Goal
Deliver P0/P1/P2/P3 production-hardening slices: isolate runtime state from source code, harden the OpenAI-compatible LLM client for retries, timeout configuration, and structured JSON validation, strengthen sandbox execution with explicit write scopes plus failure rollback, make Policy decisions configurable and auditable, wire those production signals into observability and eval gates, add durable Workflow run checkpoints with resume, harden MCP with schema cache plus health checks, govern Memory / Skill prompt injection, make Repo Index fresher and diagnosable, put role-agent collaboration behind explicit budgets and reports, and require Dream/Self-Evolution candidates to pass verification before durable Memory / Skill promotion.

## Non-goals
- Do not redesign broad UI behavior in this slice.
- Do not move or delete existing local ignored runtime files.
- Do not change README diagram assets.

## User-visible Behavior
- Default runtime state lives under `.evolva/`.
- `EVOLVA_RUNTIME_HOME` can point runtime state to a different directory.
- TUI provider configuration still works and writes a git-ignored config file.
- Existing tests and explicit temp configs continue to work.
- Workflow DAG runs write status/output checkpoints and can resume successful unchanged nodes after a failed run.
- MCP tool schemas are cached under runtime home and health can be checked from CLI/TUI/tool calls.
- Only active, sufficiently confident Memory items and active Skills are injected into prompt context.
- Repo Index records file fingerprints, skipped-file diagnostics, and stale/fresh status.
- Multi-agent role collaboration returns structured run reports with role status, latency, fallback, and errors.
- `/dream apply` stages high-confidence candidates for verification by default instead of immediately writing Memory / Skill.
- `/dream verify --promote` promotes verified candidates and records the resulting evolution fingerprint.
- `EVOLVA_DREAM_REQUIRE_VERIFICATION=0` preserves the legacy immediate-apply behavior for local compatibility.
- `/dream status` shows whether the Dream verification gate is required plus backlog, pending verification, verified, and promoted counts.

## Acceptance Criteria
- `AgentConfig()` defaults all runtime state paths to `.evolva/`.
- `AgentConfig(root=tmp_path)` relocates default runtime paths under `tmp_path/.evolva`.
- Explicitly supplied runtime paths are preserved.
- Runtime config helpers use the configured runtime home and preserve owner-only file permissions.
- Repository index and maintenance checks ignore `.evolva/`.
- `request_timeout` can be read from runtime config when no environment override is set.
- Transient LLM HTTP failures are retried with bounded attempts.
- Non-transient LLM HTTP failures fail immediately.
- LLM JSON responses can be validated for required top-level keys.
- Sandbox writable roots can be configured and enforced by file tools.
- Failed shell/Python executions restore files under configured snapshot roots.
- Successful shell/Python executions keep their changes.
- Sandbox isolation knobs are configurable through `AgentConfig`.
- Policy profiles can be extended by config or JSON policy file.
- Policy decisions are written to JSONL audit logs without raw tool arguments.
- Trace-derived metrics include policy audit, sandbox rollback, LLM latency, and LLM retry signals.
- Eval tasks can assert metric tags/fields and policy audit rows.
- Security eval baseline covers sandbox rollback and policy audit.
- Workflow runs persist `running` / `failed` / `completed` state under runtime home.
- Workflow resume reuses only successful nodes whose spec fingerprints still match.
- MCP tool listing writes/uses a runtime cache and can degrade to cached schemas when a server is temporarily unavailable.
- MCP health reports status, tool count, latency, cache age, timeout settings, and errors.
- Trace-derived metrics include MCP health and error signals.
- Memory governance supports active/draft/quarantined/rolled_back status, evidence, version bumping, audit summaries, and configurable prompt confidence threshold.
- Skill governance supports active/draft/deprecated/disabled/quarantined status, metadata-first manifests, status updates, and active-only prompt injection.
- Repo Index reuses unchanged file chunks during rebuilds, detects file changes through manifest comparison, ignores runtime artifact directories, and exposes `/repo status`.
- Multi-agent collaboration validates roles, enforces `EVOLVA_MULTI_AGENT_MAX_ROLES`, degrades failed role calls to fallback output, and emits trace-derived metrics.
- Dream apply requires verification before durable Memory / Skill writes by default.
- Dream verification with `--promote` writes verified evolution lessons and records the promotion fingerprint.
- Dream legacy immediate apply remains available only through explicit opt-out config.
- Dream status is available from CLI/TUI and gives an operator-readable next action.
- Full test suite passes.

## Constraints
- Keep runtime state local-first and git-ignored.
- Avoid breaking existing tests that pass explicit temp paths.
- Keep changes tightly scoped to the prioritized production-hardening plan.

## Assumptions
- Current legacy ignored directories under `evolva/` can remain on disk for existing local users.
- Future PRs can add migration/copy tooling if needed.

## Open Questions
None blocking for this slice.

## Source Request
The user asked to optimize the listed productionization gaps according to the technical plan, with implementation and tests moving in parallel.

## Repo Context
- Existing `AgentConfig` kept runtime artifacts under `evolva/*`.
- `.gitignore` already ignored legacy runtime paths.
- Tests use explicit temp config paths in many places, so the default migration must preserve explicit overrides.
