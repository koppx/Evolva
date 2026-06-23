# Requirements Baseline

## Goal
Make Evolva sub-agents more production-useful by allowing them to call a bounded set of tools while preserving the existing Policy, Sandbox, Trace, and observability controls.

## Non-goals
- Do not give sub-agents unrestricted tool access.
- Do not allow recursive delegation from sub-agents in this slice.
- Do not bypass existing user confirmation or Policy checks.
- Do not commit or push changes unless explicitly requested.

## User-visible Behavior
- `delegate_agent` and `collaborate` can return role outputs informed by allowed tool calls.
- Each role has a conservative default tool allowlist.
- Sub-agent tool calls are included in structured delegate/collaboration reports.
- Tool-denied or failed sub-agent runs degrade with explicit status and error details.

## Acceptance Criteria
- Sub-agents can call allowed read/status tools through the main agent's governed tool runner.
- Sub-agents cannot call tools outside their role allowlist.
- Tool calls still pass through existing Policy/Sandbox/Trace code paths.
- `AgentRoleResult` includes auditable tool call summaries.
- Existing fallback behavior still works when no LLM or no tool runner is available.
- Targeted tests and full project checks pass.

## Constraints
- The repository already has a dirty worktree from the broader productionization work; do not revert it.
- Keep default tool scopes safe enough for local production use.
- Preserve current public commands and tool names.

## Assumptions
- Read-only inspection tools are safe defaults for researcher/reviewer roles.
- `python_exec` is acceptable for coder/reviewer because it still goes through confirmation, Sandbox, and Policy.
- Write, shell, MCP, Dream, and delegation tools should remain out of default sub-agent scopes.

## Open Questions
None blocking.

## Source Request
User asked: "子agent 这个实现太简单了，要能调用一定范围的工具吧，你给出设计方案，然后再实现"

## Repo Context
- `MultiAgentCoordinator` currently calls the LLM once per role and explicitly tells it not to claim tool execution.
- `EvolvaAgent._call_tool()` already centralizes Policy, confirmation, Trace, and artifact recording.
- `ToolRegistry` stores tool metadata and capabilities.
