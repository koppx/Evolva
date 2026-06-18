from __future__ import annotations

from enum import Enum
from typing import Iterable


class Capability(str, Enum):
    """Tool capabilities used by policy and audit decisions."""

    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    RUN_COMMAND = "run_command"
    RUN_PYTHON = "run_python"
    NETWORK = "network"
    MEMORY = "memory"
    SKILL = "skill"
    CONTEXT = "context"
    TODO = "todo"
    POLICY = "policy"
    SANDBOX_INFO = "sandbox_info"
    REPO_INDEX = "repo_index"
    MCP_CONFIG = "mcp_config"
    MCP_CALL = "mcp_call"
    DELEGATE = "delegate"
    DREAM = "dream"


DEFAULT_TOOL_CAPABILITIES: dict[str, list[Capability]] = {
    "list_files": [Capability.READ_FILE],
    "read_file": [Capability.READ_FILE],
    "write_file": [Capability.WRITE_FILE],
    "shell": [Capability.RUN_COMMAND],
    "python_exec": [Capability.RUN_PYTHON],
    "web_search": [Capability.NETWORK],
    "remember": [Capability.MEMORY],
    "recall": [Capability.MEMORY],
    "list_skills": [Capability.SKILL],
    "save_skill": [Capability.SKILL, Capability.WRITE_FILE],
    "context_add": [Capability.CONTEXT],
    "context_view": [Capability.CONTEXT],
    "context_compact": [Capability.CONTEXT],
    "todo_add": [Capability.TODO],
    "todo_list": [Capability.TODO],
    "todo_update": [Capability.TODO],
    "todo_clear": [Capability.TODO],
    "sandbox_info": [Capability.SANDBOX_INFO],
    "policy_info": [Capability.POLICY],
    "policy_check": [Capability.POLICY],
    "repo_index_build": [Capability.REPO_INDEX, Capability.READ_FILE, Capability.WRITE_FILE],
    "repo_index_search": [Capability.REPO_INDEX, Capability.READ_FILE],
    "mcp_servers": [Capability.MCP_CONFIG],
    "mcp_add_server": [Capability.MCP_CONFIG, Capability.WRITE_FILE],
    "mcp_remove_server": [Capability.MCP_CONFIG, Capability.WRITE_FILE],
    "mcp_tools": [Capability.MCP_CALL],
    "mcp_call": [Capability.MCP_CALL],
    "delegate_agent": [Capability.DELEGATE],
    "collaborate": [Capability.DELEGATE],
    "dream_report": [Capability.DREAM],
}


def normalize_capabilities(values: Iterable[str | Capability] | None) -> list[Capability]:
    capabilities: list[Capability] = []
    for value in values or []:
        try:
            capability = value if isinstance(value, Capability) else Capability(str(value))
        except ValueError:
            continue
        if capability not in capabilities:
            capabilities.append(capability)
    return capabilities


def capabilities_for_tool(tool_name: str, declared: Iterable[str | Capability] | None = None) -> list[Capability]:
    normalized = normalize_capabilities(declared)
    if normalized:
        return normalized
    return list(DEFAULT_TOOL_CAPABILITIES.get(tool_name, []))
