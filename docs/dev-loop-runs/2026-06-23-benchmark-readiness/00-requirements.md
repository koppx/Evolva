# Requirements Baseline

## Goal
Add browser/search MCP or online browsing support to improve Evolva benchmark readiness for web-heavy tasks.

## Non-goals
- Do not install network packages automatically.
- Do not run live MCP downloads during implementation.
- Do not replace existing benchmark media/OCR tooling.

## User-visible Behavior
- Users can list and add browser/search/fetch MCP presets.
- Users can add env-backed MCP servers safely.
- Evolva exposes a provider-aware online search tool with DuckDuckGo fallback.
- benchmark health reports browser/search readiness.

## Acceptance Criteria
- `evolva mcp presets` lists browser/search presets.
- `evolva mcp add-preset playwright` persists a stdio MCP config.
- `web_search_pro` supports API providers and mocked DuckDuckGo fallback.
- `evolva benchmark health` includes browser/search fields.
- benchmark smoke can still read the local benchmark metadata/attachments.

## Constraints
- Preserve existing dirty worktree changes.
- Network is restricted; tests must mock online calls.
- MCP servers must be configured lazily, not started during preset add.

## Assumptions
- Common MCP entrypoints are suitable as presets: `@playwright/mcp@latest`, `mcp-server-fetch`, and `@modelcontextprotocol/server-brave-search`.
- API-key search providers are optional.

## Open Questions
None blocking.

## Source Request
“那就接入browser/search MCP 或在线搜索/浏览工具”
