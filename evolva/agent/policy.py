from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evolva.agent.capabilities import Capability, capabilities_for_tool
from evolva.tools.base import ToolResult


@dataclass
class PolicyDecision:
    allowed: bool
    risk: str
    reason: str = ""
    requires_confirmation: bool = False
    capabilities: list[str] = field(default_factory=list)
    redactions: list[str] = field(default_factory=list)
    audit_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "risk": self.risk,
            "reason": self.reason,
            "requires_confirmation": self.requires_confirmation,
            "capabilities": self.capabilities,
            "redactions": self.redactions,
            "audit_tags": self.audit_tags,
        }


@dataclass
class PolicyConfig:
    root: Path
    workspace: Path
    profile: str = os.getenv("EVOLVA_PROFILE", "dev")
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
            r"\brm\s+-[A-Za-z]*r[A-Za-z]*f\b",
            r"\brm\s+-[A-Za-z]*f[A-Za-z]*r\b",
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

    def check_tool(self, name: str, args: dict[str, Any], capabilities: list[str] | None = None) -> PolicyDecision:
        caps = capabilities_for_tool(name, capabilities)
        cap_values = [cap.value for cap in caps]
        profile = (self.config.profile or "dev").lower()
        audit_tags = [f"profile:{profile}", *(f"capability:{cap.value}" for cap in caps)]
        if profile in {"safe", "prod"}:
            denied = self._profile_denied_capability(profile, caps)
            if denied:
                return PolicyDecision(
                    False,
                    "high",
                    f"Capability `{denied.value}` is disabled in {profile} profile",
                    False,
                    cap_values,
                    [],
                    [*audit_tags, "profile_denied"],
                )
        if Capability.NETWORK in caps and not self.config.network_enabled:
            return PolicyDecision(False, "medium", "Network access is disabled by EVOLVA_NETWORK=0", False, cap_values, [], [*audit_tags, "network_disabled"])
        if Capability.RUN_COMMAND in caps or Capability.RUN_PYTHON in caps:
            if not self.config.allow_shell:
                return PolicyDecision(False, "high", "Shell/Python execution is disabled by policy", False, cap_values, [], [*audit_tags, "shell_disabled"])
            command = str(args.get("command") or args.get("code") or "")
            for pattern in self.config.denied_shell_patterns:
                if re.search(pattern, command, flags=re.I):
                    return PolicyDecision(False, "critical", f"Denied dangerous pattern: {pattern}", False, cap_values, [], [*audit_tags, "dangerous_command"])
            if self._contains_secret(command):
                return PolicyDecision(True, "high", "Command/code appears to contain a secret", True, cap_values, ["command"], [*audit_tags, "secret_in_command"])
            return PolicyDecision(True, "high", "Executable tool requires confirmation", True, cap_values, [], [*audit_tags, "executable"])
        if Capability.READ_FILE in caps or Capability.WRITE_FILE in caps:
            path = str(args.get("path", "."))
            if not self._path_is_under_root(path):
                return PolicyDecision(False, "high", f"Path escapes sandbox root: {path}", False, cap_values, [], [*audit_tags, "path_escape"])
            if Capability.WRITE_FILE in caps and self._contains_secret(str(args.get("content", ""))):
                return PolicyDecision(True, "high", "File content appears to contain a secret", True, cap_values, ["content"], [*audit_tags, "secret_in_file"])
            return PolicyDecision(True, "low", "Path is inside sandbox root", False, cap_values, [], audit_tags)
        if Capability.MCP_CALL in caps:
            return PolicyDecision(True, "high", "MCP tool execution requires confirmation", True, cap_values, [], [*audit_tags, "mcp_call"])
        return PolicyDecision(True, "low", "No special policy restrictions", False, cap_values, [], audit_tags)

    def as_tool_result(self) -> ToolResult:
        lines = [
            f"root={self.root}",
            f"workspace={self.workspace}",
            f"profile={self.config.profile}",
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

    def _profile_denied_capability(self, profile: str, capabilities: list[Capability]) -> Capability | None:
        denied_by_profile = {
            "safe": {Capability.RUN_COMMAND, Capability.RUN_PYTHON, Capability.NETWORK, Capability.MCP_CALL},
            "prod": {Capability.RUN_COMMAND, Capability.RUN_PYTHON, Capability.NETWORK, Capability.MCP_CALL, Capability.MCP_CONFIG},
        }
        denied = denied_by_profile.get(profile, set())
        for capability in capabilities:
            if capability in denied:
                return capability
        return None
