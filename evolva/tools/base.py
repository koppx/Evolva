from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ToolResult:
    ok: bool
    output: str
    data: Any = None


@dataclass
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    func: Callable[..., ToolResult]
    needs_confirmation: bool = False


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def describe(self) -> str:
        lines = []
        for name in self.names():
            t = self._tools[name]
            lines.append(f"- {name}: {t.description}; schema={t.schema}")
        return "\n".join(lines)

    def call(self, name: str, args: dict[str, Any]) -> ToolResult:
        tool = self.get(name)
        return tool.func(**args)
