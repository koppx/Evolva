from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evolva.tools.base import ToolResult


@dataclass
class PolicyDecision:
    allowed: bool
    risk: str
    reason: str = ""
    requires_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "risk": self.risk,
            "reason": self.reason,
            "requires_confirmation": self.requires_confirmation,
        }


@dataclass
class PolicyConfig:
    root: Path
    workspace: Path
    network_enabled: bool = os.getenv("EVOLVA_NETWORK", "1") != "0"
    allow_shell: bool = os.getenv("EVOLVA_POLICY_ALLOW_SHELL", "1") != "0"
    secret_patterns: list[str] = field(
        default_factory=lambda: [
            r"sk-[A-Za-z0-9_-]{20,}",
            r"AKIA[0-9A-Z]{16}",
            r"-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----",
            r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^\s'\"]{8,}",
        ]
    )
    denied_shell_patterns: list[str] = field(
        default_factory=lambda: [
            r"\brm\s+-rf\s+(/|~|\*)",
            r"\bgit\s+reset\s+--hard\b",
            r"\bmkfs\b",
            r"\bdd\s+if=",
            r"\bshutdown\b",
            r"\breboot\b",
            r":\(\)\{:\|:&\};:",
        ]
    )


class PolicyEngine:
    """Pre-tool guardrail engine for risk scoring, denylists, and secret checks."""

    def __init__(self, config: PolicyConfig):
        self.config = config
        self.root = config.root.resolve()
        self.workspace = config.workspace.resolve()

    def check_tool(self, name: str, args: dict[str, Any]) -> PolicyDecision:
        if name == "web_search" and not self.config.network_enabled:
            return PolicyDecision(False, "medium", "Network access is disabled by EVOLVA_NETWORK=0")
        if name in {"shell", "python_exec"}:
            if not self.config.allow_shell:
                return PolicyDecision(False, "high", "Shell/Python execution is disabled by policy")
            command = str(args.get("command") or args.get("code") or "")
            for pattern in self.config.denied_shell_patterns:
                if re.search(pattern, command, flags=re.I):
                    return PolicyDecision(False, "critical", f"Denied dangerous pattern: {pattern}")
            if self._contains_secret(command):
                return PolicyDecision(True, "high", "Command/code appears to contain a secret", True)
            return PolicyDecision(True, "high", "Executable tool requires confirmation", True)
        if name in {"write_file", "read_file", "list_files"}:
            path = str(args.get("path", "."))
            if not self._path_is_under_root(path):
                return PolicyDecision(False, "high", f"Path escapes sandbox root: {path}")
            if name == "write_file" and self._contains_secret(str(args.get("content", ""))):
                return PolicyDecision(True, "high", "File content appears to contain a secret", True)
            return PolicyDecision(True, "low", "Path is inside sandbox root")
        return PolicyDecision(True, "low", "No special policy restrictions")

    def as_tool_result(self) -> ToolResult:
        lines = [
            f"root={self.root}",
            f"workspace={self.workspace}",
            f"network={'enabled' if self.config.network_enabled else 'disabled'}",
            f"shell={'enabled' if self.config.allow_shell else 'disabled'}",
            f"secret_patterns={len(self.config.secret_patterns)}",
            f"denied_shell_patterns={len(self.config.denied_shell_patterns)}",
        ]
        return ToolResult(True, "\n".join(lines))

    def _path_is_under_root(self, path: str) -> bool:
        candidate = Path(path)
        resolved = candidate.resolve() if candidate.is_absolute() else (self.root / candidate).resolve()
        try:
            resolved.relative_to(self.root)
            return True
        except ValueError:
            return False

    def _contains_secret(self, text: str) -> bool:
        return any(re.search(pattern, text) for pattern in self.config.secret_patterns)
