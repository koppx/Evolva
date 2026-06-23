# Implementation Log

## Browser/search MCP presets
- Added `evolva/agent/mcp_presets.py` with `playwright`, `fetch`, and `brave-search` recipes.
- Added env parsing for CLI use.

## Online search tool
- Added `web_search_pro` with `auto|tavily|brave|serpapi|duckduckgo` provider support.
- Existing `web_search` now delegates to provider-aware search.

## benchmark health
- Extended `benchmark_tool_health` to report browser/search binaries, API key presence, and matching MCP server configs.

## CLI/registry
- Added `evolva mcp presets` and `evolva mcp add-preset`.
- Added repeated `--env KEY=VALUE` support to `evolva mcp add`.
- Registered `mcp_presets`, `mcp_add_preset`, and `web_search_pro` tools/capabilities.

## Docs/tests
- Updated README benchmark readiness section.
- Added tests for parser, MCP presets, CLI add-preset, health data, and mocked DuckDuckGo search.
