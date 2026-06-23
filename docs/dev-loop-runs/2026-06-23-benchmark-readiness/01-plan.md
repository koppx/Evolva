# Plan

1. Add `evolva.agent.mcp_presets` with built-in browser/search/fetch recipes and env parsing.
2. Extend benchmark tooling with browser/search health and `web_search_pro` provider fallback.
3. Register new tools in the builtin registry and policy capabilities.
4. Extend CLI with `mcp presets`, `mcp add-preset`, and `--env KEY=VALUE` for MCP add.
5. Update tests and README.
6. Run focused and full verification plus benchmark health/smoke.

## Risks
- Live MCP package names can change; preset add is lazy and docs call out first-run network dependency.
- DuckDuckGo HTML can change; tests mock parser behavior and API providers are preferred when configured.
