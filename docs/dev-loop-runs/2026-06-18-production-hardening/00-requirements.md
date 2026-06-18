# Requirements Baseline

## Goal
Implement the production-hardening technical plan for Evolva with code, verification, tests, and observability hooks for each major execution-safety module.

## Non-goals
- Do not introduce a hosted multi-tenant service layer in this iteration.
- Do not require Docker or another external sandbox runtime to run the existing test suite.
- Do not commit, push, or open a PR unless explicitly requested.

## User-visible Behavior
- Tool execution is governed by explicit capabilities and profile-aware policy decisions.
- Shell commands are parsed and executed without `shell=True`, with allowlist checks, timeout handling, cwd validation, and output truncation.
- Trace data is redacted before persistence.
- Local state stores use atomic writes and recover from corrupted JSON where practical.
- MCP requests can time out instead of hanging the caller indefinitely.

## Acceptance Criteria
- Policy decisions include capabilities, audit tags, risk, confirmation requirement, and denial reason.
- Shell command execution rejects shell control operators and dangerous commands, and executes allowed commands with `shell=False`.
- Trace files do not persist known secret patterns in event payloads or final answers.
- Memory, context, todo, and artifact stores use atomic write helpers.
- MCP request path supports a request timeout and bounded message size.
- Unit and integration tests cover success, denial, timeout, redaction, corrupt-state recovery, and loop command gate behavior.
- Verification commands are recorded in `03-implementation-log.md` and summarized in `04-acceptance-report.md`.

## Constraints
- Keep compatibility with the current CLI/TUI/tool API where possible.
- Preserve existing tests and public behavior unless it conflicts with production safety.
- Avoid touching unrelated untracked state such as `lark_auth/`.
- Use local stdlib-first dependencies unless the project already depends on a library.

## Assumptions
- The first implementation pass should use a hardened local backend rather than requiring container runtime setup.
- `dev` profile can preserve current interactive local behavior, while `safe` and `prod` are stricter.
- Existing loop allowlist behavior should remain compatible with current specs, but enforcement should become safer.

## Open Questions
- None blocking for the first hardening pass.

## Source Request
The user asked to implement the previously designed technical plan and required every module to include function definition, verification method, tests, and observability.

## Repo Context
- Repository root: `/Users/bytedance/Documents/agent`
- Branch: `main`
- Base SHA: `c1a1c1cdff424360ca2e285ac0b23ed05d21f6f8`
- Dirty state at start: only untracked `lark_auth/`, intentionally ignored.
- Feature-dev-loop required Superpowers dependencies are unavailable in this session; implementation proceeds in reduced inline mode with artifacts recorded here.
