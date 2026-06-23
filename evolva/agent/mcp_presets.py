from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MCPPreset:
    """A safe, local MCP server recipe.

    Presets only persist server configs. They do not install packages or start
    the server until the user explicitly asks Evolva to list/call MCP tools.
    """

    name: str
    description: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    request_timeout: int = 60
    max_message_bytes: int = 4_000_000
    tags: tuple[str, ...] = ()
    install_hint: str = ""

    def to_server_config(self, *, env_overrides: dict[str, str] | None = None, name: str | None = None) -> dict[str, Any]:
        env = dict(self.env)
        env.update(env_overrides or {})
        return {
            "name": name or self.name,
            "command": self.command,
            "args": list(self.args),
            "env": env,
            "request_timeout": self.request_timeout,
            "max_message_bytes": self.max_message_bytes,
        }


MCP_PRESETS: dict[str, MCPPreset] = {
    "playwright": MCPPreset(
        name="playwright",
        description="Browser automation MCP for dynamic benchmark web pages, screenshots, forms, and JS-rendered sites.",
        command="npx",
        args=("-y", "@playwright/mcp@latest"),
        request_timeout=90,
        max_message_bytes=8_000_000,
        tags=("browser", "web", "benchmark"),
        install_hint="First run may download the npm package and Playwright browsers; network access is required.",
    ),
    "fetch": MCPPreset(
        name="fetch",
        description="MCP fetch server for robust page retrieval and HTML-to-text extraction.",
        command="uvx",
        args=("mcp-server-fetch",),
        request_timeout=60,
        max_message_bytes=4_000_000,
        tags=("fetch", "web", "benchmark"),
        install_hint="Requires uv/uvx and network access on first run.",
    ),
    "brave-search": MCPPreset(
        name="brave-search",
        description="Search MCP backed by Brave Search API; useful when benchmark questions require current web search.",
        command="npx",
        args=("-y", "@modelcontextprotocol/server-brave-search"),
        request_timeout=60,
        max_message_bytes=4_000_000,
        tags=("search", "web", "benchmark"),
        install_hint="Requires BRAVE_API_KEY in the server environment and network access on first run.",
    ),
}


def list_mcp_presets() -> list[dict[str, Any]]:
    return [
        {
            "name": preset.name,
            "description": preset.description,
            "command": preset.command,
            "args": list(preset.args),
            "env_keys": sorted(preset.env),
            "request_timeout": preset.request_timeout,
            "max_message_bytes": preset.max_message_bytes,
            "tags": list(preset.tags),
            "install_hint": preset.install_hint,
        }
        for preset in sorted(MCP_PRESETS.values(), key=lambda item: item.name)
    ]


def get_mcp_preset(name: str) -> MCPPreset:
    key = str(name or "").strip()
    if key not in MCP_PRESETS:
        choices = ", ".join(sorted(MCP_PRESETS))
        raise KeyError(f"Unknown MCP preset `{name}`. Available presets: {choices}")
    return MCP_PRESETS[key]


def parse_env_pairs(values: list[str] | tuple[str, ...] | None) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in values or []:
        key, sep, value = str(raw).partition("=")
        key = key.strip()
        if not sep or not key:
            raise ValueError(f"Invalid --env value `{raw}`; expected KEY=VALUE")
        env[key] = value
    return env
