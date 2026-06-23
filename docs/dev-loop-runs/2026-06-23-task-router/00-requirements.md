# Requirements Baseline

## Goal
Add a Task Router so Evolva can decide when complex user requests should automatically use multiple role agents, instead of relying only on the model to choose `delegate_agent` / `collaborate`.

## Non-goals
- Do not make every request use sub-agents.
- Do not let routing bypass Policy, Sandbox, Trace, or role budgets.
- Do not add unrestricted tool access for sub-agents.
- Do not change public command names.

## User-visible Behavior
- Simple questions continue through the normal single-agent loop.
- Complex implementation, review, research, or planning requests get an automatic route decision.
- The selected roles are based on task type and capped by existing multi-agent budgets.
- Route decisions and multi-agent outputs are written to Trace and Context before the main agent continues.

## Acceptance Criteria
- Router classifies simple / research / coding / review / complex requests deterministically.
- `collaborate_report()` can use the router when roles are not explicitly supplied.
- `EvolvaAgent.chat()` invokes the router before the main LLM loop for complex tasks.
- Route decisions are auditable in Trace and visible in Context.
- Existing explicit role selection and max-role budget behavior remain intact.
- Targeted tests and full checks pass.

## Constraints
- Current worktree starts clean at `8246dc1`.
- Routing must be conservative to avoid unnecessary cost.
- Sub-agent tool access remains governed by existing role allowlists and `_call_tool()`.

## Assumptions
- Deterministic heuristics are preferable for the first version because they are cheap, testable, and do not add an extra model call.
- Future versions can replace or augment the heuristic router with a learned/LLM classifier.

## Open Questions
None blocking.

## Source Request
User asked to implement the Task Router idea so Evolva can decide how many sub-agents to start for complex tasks.

## Repo Context
- `MultiAgentCoordinator.collaborate_report()` defaults to all four roles when roles are omitted.
- `EvolvaAgent.chat()` currently starts the LangGraph loop directly after fallback checks.
- Sub-agents already have role tool scopes and governed tool execution.
