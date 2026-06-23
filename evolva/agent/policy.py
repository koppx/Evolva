from __future__ import annotations

import os
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evolva.agent.capabilities import Capability, capabilities_for_tool
from evolva.storage import append_jsonl
from evolva.tools.base import ToolResult


DEFAULT_PROFILE_RULES: dict[str, dict[str, Any]] = {
    "safe": {"deny_capabilities": [Capability.RUN_COMMAND.value, Capability.RUN_PYTHON.value, Capability.NETWORK.value, Capability.MCP_CALL.value]},
    "prod": {
        "deny_capabilities": [
            Capability.RUN_COMMAND.value,
            Capability.RUN_PYTHON.value,
            Capability.NETWORK.value,
            Capability.MCP_CALL.value,
            Capability.MCP_CONFIG.value,
        ]
    },
}


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
    policy_file: Path | None = None
    audit_file: Path | None = None
    profile_rules: dict[str, dict[str, Any]] = field(default_factory=dict)
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
        self.profile_rules = self._profile_rules()
        self.secret_patterns = list(config.secret_patterns)
        self.denied_shell_patterns = list(config.denied_shell_patterns)
        self._load_policy_file(config.policy_file)

    def check_tool(self, name: str, args: dict[str, Any], capabilities: list[str] | None = None) -> PolicyDecision:
        caps = capabilities_for_tool(name, capabilities)
        cap_values = [cap.value for cap in caps]
        profile = (self.config.profile or "dev").lower()
        audit_tags = [f"profile:{profile}", *(f"capability:{cap.value}" for cap in caps)]
        network_enabled = self._profile_bool(profile, "network_enabled", self.config.network_enabled)
        allow_shell = self._profile_bool(profile, "allow_shell", self.config.allow_shell)
        if profile in {"safe", "prod"}:
            denied = self._profile_denied_capability(profile, caps)
            if denied:
                return self._audit(
                    name,
                    PolicyDecision(
                        False,
                        "high",
                        f"Capability `{denied.value}` is disabled in {profile} profile",
                        False,
                        cap_values,
                        [],
                        [*audit_tags, "profile_denied"],
                    ),
                )
        elif profile in self.profile_rules:
            denied = self._profile_denied_capability(profile, caps)
            if denied:
                return self._audit(
                    name,
                    PolicyDecision(False, "high", f"Capability `{denied.value}` is disabled in {profile} profile", False, cap_values, [], [*audit_tags, "profile_denied"]),
                )
        if Capability.NETWORK in caps and not network_enabled:
            return self._audit(name, PolicyDecision(False, "medium", "Network access is disabled by policy", False, cap_values, [], [*audit_tags, "network_disabled"]))
        if Capability.RUN_COMMAND in caps or Capability.RUN_PYTHON in caps:
            if not allow_shell:
                return self._audit(name, PolicyDecision(False, "high", "Shell/Python execution is disabled by policy", False, cap_values, [], [*audit_tags, "shell_disabled"]))
            command = str(args.get("command") or args.get("code") or "")
            for pattern in self.denied_shell_patterns:
                if re.search(pattern, command, flags=re.I):
                    return self._audit(name, PolicyDecision(False, "critical", f"Denied dangerous pattern: {pattern}", False, cap_values, [], [*audit_tags, "dangerous_command"]))
            if self._contains_secret(command):
                return self._audit(name, PolicyDecision(True, "high", "Command/code appears to contain a secret", True, cap_values, ["command"], [*audit_tags, "secret_in_command"]))
            return self._audit(name, PolicyDecision(True, "high", "Executable tool requires confirmation", True, cap_values, [], [*audit_tags, "executable"]))
        if Capability.READ_FILE in caps or Capability.WRITE_FILE in caps:
            path = str(args.get("path", "."))
            if not self._path_is_under_root(path):
                return self._audit(name, PolicyDecision(False, "high", f"Path escapes sandbox root: {path}", False, cap_values, [], [*audit_tags, "path_escape"]))
            if Capability.WRITE_FILE in caps and self._contains_secret(str(args.get("content", ""))):
                return self._audit(name, PolicyDecision(True, "high", "File content appears to contain a secret", True, cap_values, ["content"], [*audit_tags, "secret_in_file"]))
            return self._audit(name, PolicyDecision(True, "low", "Path is inside sandbox root", False, cap_values, [], audit_tags))
        if Capability.MCP_CALL in caps:
            return self._audit(name, PolicyDecision(True, "high", "MCP tool execution requires confirmation", True, cap_values, [], [*audit_tags, "mcp_call"]))
        return self._audit(name, PolicyDecision(True, "low", "No special policy restrictions", False, cap_values, [], audit_tags))

    def as_tool_result(self) -> ToolResult:
        lines = [
            f"root={self.root}",
            f"workspace={self.workspace}",
            f"profile={self.config.profile}",
            f"network={'enabled' if self._profile_bool(self.config.profile, 'network_enabled', self.config.network_enabled) else 'disabled'}",
            f"shell={'enabled' if self._profile_bool(self.config.profile, 'allow_shell', self.config.allow_shell) else 'disabled'}",
            f"policy_file={self.config.policy_file or 'not configured'}",
            f"audit_file={self.config.audit_file or 'not configured'}",
            f"secret_patterns={len(self.secret_patterns)}",
            f"denied_shell_patterns={len(self.denied_shell_patterns)}",
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
        return any(re.search(pattern, text) for pattern in self.secret_patterns)

    def _profile_denied_capability(self, profile: str, capabilities: list[Capability]) -> Capability | None:
        rule = self.profile_rules.get(profile, {})
        denied = {str(item) for item in rule.get("deny_capabilities", [])}
        for capability in capabilities:
            if capability.value in denied:
                return capability
        return None

    def _profile_rules(self) -> dict[str, dict[str, Any]]:
        rules = {name: dict(rule) for name, rule in DEFAULT_PROFILE_RULES.items()}
        for name, rule in self.config.profile_rules.items():
            merged = dict(rules.get(str(name).lower(), {}))
            merged.update(rule)
            rules[str(name).lower()] = merged
        return rules

    def _profile_bool(self, profile: str, key: str, default: bool) -> bool:
        value = self.profile_rules.get((profile or "dev").lower(), {}).get(key, default)
        return bool(value)

    def _load_policy_file(self, path: Path | None) -> None:
        if path is None or not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        self.secret_patterns.extend(str(item) for item in data.get("secret_patterns", []) if item)
        self.denied_shell_patterns.extend(str(item) for item in data.get("denied_shell_patterns", []) if item)
        profiles = data.get("profiles", {})
        if isinstance(profiles, dict):
            for name, rule in profiles.items():
                if not isinstance(rule, dict):
                    continue
                merged = dict(self.profile_rules.get(str(name).lower(), {}))
                merged.update(rule)
                self.profile_rules[str(name).lower()] = merged

    def _audit(self, tool: str, decision: PolicyDecision) -> PolicyDecision:
        if self.config.audit_file is None:
            return decision
        append_jsonl(
            self.config.audit_file,
            {
                "ts": time.time(),
                "tool": tool,
                "allowed": decision.allowed,
                "risk": decision.risk,
                "reason": decision.reason,
                "requires_confirmation": decision.requires_confirmation,
                "capabilities": decision.capabilities,
                "redactions": decision.redactions,
                "audit_tags": decision.audit_tags,
            },
        )
        return decision
