from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LOCAL_RUNTIME_CONFIG_FILE = ROOT / "evolva" / "runtime" / "config.json"

LLM_CONFIG_KEYS = {"api_key", "model", "base_url", "temperature", "request_timeout"}


def load_runtime_config(path: Path = LOCAL_RUNTIME_CONFIG_FILE) -> dict[str, Any]:
    """Load local, git-ignored Evolva runtime settings.

    The file is intentionally separate from tracked project configuration so a
    user can configure provider credentials from the TUI without exporting env
    vars or risking a commit of secrets.
    """

    if os.getenv("EVOLVA_DISABLE_RUNTIME_CONFIG") == "1":
        return {}
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_runtime_config(updates: dict[str, Any], path: Path = LOCAL_RUNTIME_CONFIG_FILE) -> dict[str, Any]:
    """Persist allowed local runtime settings with owner-only permissions."""

    data = load_runtime_config(path)
    for key, value in updates.items():
        if key not in LLM_CONFIG_KEYS or value is None:
            continue
        data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return data


def remove_runtime_config_keys(keys: list[str], path: Path = LOCAL_RUNTIME_CONFIG_FILE) -> dict[str, Any]:
    """Remove selected keys from the local runtime settings file."""

    data = load_runtime_config(path)
    for key in keys:
        data.pop(key, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return data


def _runtime_value(key: str, env_name: str, default: str | None = None) -> str | None:
    if env_name in os.environ:
        return os.environ.get(env_name)
    value = load_runtime_config().get(key)
    if value is None:
        return default
    return str(value)


def _runtime_float(key: str, env_name: str, default: float) -> float:
    raw = _runtime_value(key, env_name, str(default))
    try:
        return float(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


def _runtime_bool(env_name: str, default: bool) -> bool:
    raw = os.getenv(env_name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _runtime_int(env_name: str, default: int) -> int:
    raw = os.getenv(env_name)
    try:
        return int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


def mask_secret(value: str | None) -> str:
    """Return a safe display form for secrets."""

    if not value:
        return "not configured"
    if len(value) <= 8:
        return "configured"
    return f"configured (...{value[-4:]})"


@dataclass(frozen=True)
class AgentConfig:
    root: Path = ROOT
    workspace: Path = ROOT / "evolva" / "workspace"
    memory_file: Path = ROOT / "evolva" / "memory" / "memory.jsonl"
    skills_dir: Path = ROOT / "evolva" / "skills"
    context_file: Path = ROOT / "evolva" / "context" / "context.json"
    todo_file: Path = ROOT / "evolva" / "todo" / "todos.json"
    traces_dir: Path = ROOT / "evolva" / "traces"
    metrics_file: Path = ROOT / "evolva" / "metrics" / "metrics.jsonl"
    alerts_file: Path = ROOT / "evolva" / "metrics" / "alerts.jsonl"
    artifacts_file: Path = ROOT / "evolva" / "artifacts" / "manifest.jsonl"
    eval_results_dir: Path = ROOT / "evolva" / "eval_results"
    dreams_dir: Path = ROOT / "evolva" / "dreams"
    workflows_dir: Path = ROOT / "evolva" / "workflows"
    loops_dir: Path = ROOT / "evolva" / "loops"
    loop_runs_dir: Path = ROOT / "evolva" / "loop_runs"
    runtime_config_file: Path = LOCAL_RUNTIME_CONFIG_FILE
    mcp_config_file: Path = ROOT / "evolva" / "mcp" / "servers.json"
    repo_index_file: Path = ROOT / "evolva" / "repo_index" / "index.json"
    sandbox_allow_shell: bool = os.getenv("EVOLVA_SANDBOX_ALLOW_SHELL", "1") != "0"
    sandbox_backend: str = os.getenv("EVOLVA_SANDBOX_BACKEND", "local")
    sandbox_container_image: str = os.getenv("EVOLVA_SANDBOX_CONTAINER_IMAGE", "python:3.12-slim")
    sandbox_container_network: str = os.getenv("EVOLVA_SANDBOX_CONTAINER_NETWORK", "none")
    sandbox_container_read_only: bool = _runtime_bool("EVOLVA_SANDBOX_CONTAINER_READ_ONLY", True)
    sandbox_container_memory: str = os.getenv("EVOLVA_SANDBOX_CONTAINER_MEMORY", "512m")
    sandbox_container_cpus: str = os.getenv("EVOLVA_SANDBOX_CONTAINER_CPUS", "1")
    sandbox_container_pids_limit: int = _runtime_int("EVOLVA_SANDBOX_CONTAINER_PIDS_LIMIT", 128)
    sandbox_container_user: str = os.getenv("EVOLVA_SANDBOX_CONTAINER_USER", "")
    tracing_enabled: bool = os.getenv("EVOLVA_TRACING", "1") != "0"
    observability_enabled: bool = os.getenv("EVOLVA_OBSERVABILITY", "1") != "0"
    profile: str = os.getenv("EVOLVA_PROFILE", "dev")
    model: str = field(default_factory=lambda: _runtime_value("model", "OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini")
    api_key: str | None = field(default_factory=lambda: _runtime_value("api_key", "OPENAI_API_KEY", None))
    base_url: str = field(default_factory=lambda: _runtime_value("base_url", "OPENAI_BASE_URL", "https://api.openai.com/v1") or "https://api.openai.com/v1")
    temperature: float = field(default_factory=lambda: _runtime_float("temperature", "OPENAI_TEMPERATURE", 0.2))
    request_timeout: int = int(os.getenv("OPENAI_REQUEST_TIMEOUT", "180"))
    max_steps: int = int(os.getenv("EVOLVA_MAX_STEPS", "8"))
    auto_evolve: bool = os.getenv("EVOLVA_AUTO_EVOLVE", "1") != "0"

    def __post_init__(self) -> None:
        # Keep backward-compatible tests/callers that construct a temp-root
        # config without passing newly added paths.
        if self.root != ROOT and self.artifacts_file == ROOT / "evolva" / "artifacts" / "manifest.jsonl":
            object.__setattr__(self, "artifacts_file", self.root / "evolva" / "artifacts" / "manifest.jsonl")
        if self.root != ROOT and self.metrics_file == ROOT / "evolva" / "metrics" / "metrics.jsonl":
            object.__setattr__(self, "metrics_file", self.root / "evolva" / "metrics" / "metrics.jsonl")
        if self.root != ROOT and self.alerts_file == ROOT / "evolva" / "metrics" / "alerts.jsonl":
            object.__setattr__(self, "alerts_file", self.root / "evolva" / "metrics" / "alerts.jsonl")
        if self.root != ROOT and self.runtime_config_file == LOCAL_RUNTIME_CONFIG_FILE:
            object.__setattr__(self, "runtime_config_file", self.root / "evolva" / "runtime" / "config.json")

    def ensure_dirs(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.context_file.parent.mkdir(parents=True, exist_ok=True)
        self.todo_file.parent.mkdir(parents=True, exist_ok=True)
        self.traces_dir.mkdir(parents=True, exist_ok=True)
        self.metrics_file.parent.mkdir(parents=True, exist_ok=True)
        self.alerts_file.parent.mkdir(parents=True, exist_ok=True)
        self.artifacts_file.parent.mkdir(parents=True, exist_ok=True)
        self.eval_results_dir.mkdir(parents=True, exist_ok=True)
        self.dreams_dir.mkdir(parents=True, exist_ok=True)
        self.workflows_dir.mkdir(parents=True, exist_ok=True)
        self.loops_dir.mkdir(parents=True, exist_ok=True)
        self.loop_runs_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_config_file.parent.mkdir(parents=True, exist_ok=True)
        self.mcp_config_file.parent.mkdir(parents=True, exist_ok=True)
        self.repo_index_file.parent.mkdir(parents=True, exist_ok=True)
