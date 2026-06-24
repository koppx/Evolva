from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT_ENV = "EVOLVA_ROOT"
RUNTIME_HOME_ENV = "EVOLVA_RUNTIME_HOME"

LLM_CONFIG_KEYS = {"api_key", "model", "base_url", "temperature", "request_timeout", "llm_retry_backoff", "memory_context_min_confidence"}


def default_root() -> Path:
    raw = os.getenv(ROOT_ENV)
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd().resolve()


def default_runtime_home(root: Path | None = None) -> Path:
    root = (root or default_root()).resolve()
    raw = os.getenv(RUNTIME_HOME_ENV)
    if raw:
        candidate = Path(raw).expanduser()
        return candidate if candidate.is_absolute() else (root / candidate).resolve()
    return root / ".evolva"


def default_runtime_path(*parts: str, root: Path | None = None) -> Path:
    return default_runtime_home(root) / Path(*parts)


def load_runtime_config(path: Path | None = None) -> dict[str, Any]:
    """Load local, git-ignored Evolva runtime settings.

    The file is intentionally separate from tracked project configuration so a
    user can configure provider credentials from the TUI without exporting env
    vars or risking a commit of secrets.
    """

    path = path or default_runtime_path("runtime", "config.json")
    if os.getenv("EVOLVA_DISABLE_RUNTIME_CONFIG") == "1":
        return {}
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_runtime_config(updates: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    """Persist allowed local runtime settings with owner-only permissions."""

    path = path or default_runtime_path("runtime", "config.json")
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


def remove_runtime_config_keys(keys: list[str], path: Path | None = None) -> dict[str, Any]:
    """Remove selected keys from the local runtime settings file."""

    path = path or default_runtime_path("runtime", "config.json")
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


def _runtime_int_value(key: str, env_name: str, default: int) -> int:
    raw = _runtime_value(key, env_name, str(default))
    try:
        return int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


def _runtime_paths(env_name: str) -> tuple[Path, ...]:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return ()
    return tuple(Path(item).expanduser() for item in raw.split(os.pathsep) if item.strip())


def mask_secret(value: str | None) -> str:
    """Return a safe display form for secrets."""

    if not value:
        return "not configured"
    if len(value) <= 8:
        return "configured"
    return f"configured (...{value[-4:]})"


@dataclass(frozen=True)
class AgentConfig:
    root: Path = field(default_factory=default_root)
    runtime_home: Path = field(default_factory=default_runtime_home)
    workspace: Path = field(default_factory=lambda: default_runtime_path("workspace"))
    memory_file: Path = field(default_factory=lambda: default_runtime_path("memory", "memory.jsonl"))
    skills_dir: Path = field(default_factory=lambda: default_runtime_path("skills"))
    context_file: Path = field(default_factory=lambda: default_runtime_path("context", "context.json"))
    todo_file: Path = field(default_factory=lambda: default_runtime_path("todo", "todos.json"))
    traces_dir: Path = field(default_factory=lambda: default_runtime_path("traces"))
    metrics_file: Path = field(default_factory=lambda: default_runtime_path("metrics", "metrics.jsonl"))
    alerts_file: Path = field(default_factory=lambda: default_runtime_path("metrics", "alerts.jsonl"))
    artifacts_file: Path = field(default_factory=lambda: default_runtime_path("artifacts", "manifest.jsonl"))
    policy_audit_file: Path = field(default_factory=lambda: default_runtime_path("policy", "audit.jsonl"))
    eval_results_dir: Path = field(default_factory=lambda: default_runtime_path("eval_results"))
    dreams_dir: Path = field(default_factory=lambda: default_runtime_path("dreams"))
    workflows_dir: Path = field(default_factory=lambda: default_runtime_path("workflows"))
    loops_dir: Path = field(default_factory=lambda: default_runtime_path("loops"))
    loop_runs_dir: Path = field(default_factory=lambda: default_runtime_path("loop_runs"))
    runtime_config_file: Path = field(default_factory=lambda: default_runtime_path("runtime", "config.json"))
    mcp_config_file: Path = field(default_factory=lambda: default_runtime_path("mcp", "servers.json"))
    mcp_tools_cache_file: Path = field(default_factory=lambda: default_runtime_path("mcp", "tools-cache.json"))
    repo_index_file: Path = field(default_factory=lambda: default_runtime_path("repo_index", "index.json"))
    sandbox_allow_shell: bool = os.getenv("EVOLVA_SANDBOX_ALLOW_SHELL", "1") != "0"
    sandbox_backend: str = os.getenv("EVOLVA_SANDBOX_BACKEND", "local")
    sandbox_container_image: str = os.getenv("EVOLVA_SANDBOX_CONTAINER_IMAGE", "python:3.12-slim")
    sandbox_container_network: str = os.getenv("EVOLVA_SANDBOX_CONTAINER_NETWORK", "none")
    sandbox_container_read_only: bool = _runtime_bool("EVOLVA_SANDBOX_CONTAINER_READ_ONLY", True)
    sandbox_container_memory: str = os.getenv("EVOLVA_SANDBOX_CONTAINER_MEMORY", "512m")
    sandbox_container_cpus: str = os.getenv("EVOLVA_SANDBOX_CONTAINER_CPUS", "1")
    sandbox_container_pids_limit: int = _runtime_int("EVOLVA_SANDBOX_CONTAINER_PIDS_LIMIT", 128)
    sandbox_container_user: str = os.getenv("EVOLVA_SANDBOX_CONTAINER_USER", "")
    sandbox_writable_roots: tuple[Path, ...] = field(default_factory=lambda: _runtime_paths("EVOLVA_SANDBOX_WRITABLE_ROOTS"))
    sandbox_rollback_on_failure: bool = field(default_factory=lambda: _runtime_bool("EVOLVA_SANDBOX_ROLLBACK_ON_FAILURE", True))
    sandbox_snapshot_roots: tuple[Path, ...] = field(default_factory=lambda: _runtime_paths("EVOLVA_SANDBOX_SNAPSHOT_ROOTS"))
    sandbox_max_snapshot_bytes: int = field(default_factory=lambda: _runtime_int("EVOLVA_SANDBOX_MAX_SNAPSHOT_BYTES", 5_000_000))
    tracing_enabled: bool = os.getenv("EVOLVA_TRACING", "1") != "0"
    observability_enabled: bool = os.getenv("EVOLVA_OBSERVABILITY", "1") != "0"
    policy_file: Path | None = field(default_factory=lambda: Path(os.environ["EVOLVA_POLICY_FILE"]).expanduser() if os.getenv("EVOLVA_POLICY_FILE") else None)
    profile: str = os.getenv("EVOLVA_PROFILE", "dev")
    model: str = field(default_factory=lambda: _runtime_value("model", "OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini")
    api_key: str | None = field(default_factory=lambda: _runtime_value("api_key", "OPENAI_API_KEY", None))
    base_url: str = field(default_factory=lambda: _runtime_value("base_url", "OPENAI_BASE_URL", "https://api.openai.com/v1") or "https://api.openai.com/v1")
    temperature: float = field(default_factory=lambda: _runtime_float("temperature", "OPENAI_TEMPERATURE", 0.2))
    request_timeout: int = field(default_factory=lambda: _runtime_int_value("request_timeout", "OPENAI_REQUEST_TIMEOUT", 180))
    llm_max_retries: int = field(default_factory=lambda: _runtime_int("EVOLVA_LLM_MAX_RETRIES", 2))
    llm_retry_backoff: float = field(default_factory=lambda: _runtime_float("llm_retry_backoff", "EVOLVA_LLM_RETRY_BACKOFF", 0.25))
    mcp_tools_cache_ttl: int = field(default_factory=lambda: _runtime_int("EVOLVA_MCP_TOOLS_CACHE_TTL", 300))
    memory_context_min_confidence: float = field(default_factory=lambda: _runtime_float("memory_context_min_confidence", "EVOLVA_MEMORY_CONTEXT_MIN_CONFIDENCE", 0.5))
    multi_agent_max_roles: int = field(default_factory=lambda: _runtime_int("EVOLVA_MULTI_AGENT_MAX_ROLES", 4))
    multi_agent_tool_steps: int = field(default_factory=lambda: _runtime_int("EVOLVA_MULTI_AGENT_TOOL_STEPS", 2))
    multi_agent_auto_route: bool = field(default_factory=lambda: _runtime_bool("EVOLVA_MULTI_AGENT_AUTO_ROUTE", False))
    multi_agent_auto_route_max_roles: int = field(default_factory=lambda: _runtime_int("EVOLVA_MULTI_AGENT_AUTO_ROUTE_MAX_ROLES", 4))
    dream_require_verification: bool = field(default_factory=lambda: _runtime_bool("EVOLVA_DREAM_REQUIRE_VERIFICATION", True))
    max_steps: int = int(os.getenv("EVOLVA_MAX_STEPS", "8"))
    auto_evolve: bool = os.getenv("EVOLVA_AUTO_EVOLVE", "1") != "0"

    def __post_init__(self) -> None:
        root = Path(self.root).expanduser().resolve()
        object.__setattr__(self, "root", root)
        default_config_root = default_root()
        if self.runtime_home == default_runtime_home(default_config_root) and root != default_config_root:
            object.__setattr__(self, "runtime_home", default_runtime_home(self.root))
        self._relocate_default_path("workspace", "workspace")
        self._relocate_default_path("memory_file", "memory", "memory.jsonl")
        self._relocate_default_path("skills_dir", "skills")
        self._relocate_default_path("context_file", "context", "context.json")
        self._relocate_default_path("todo_file", "todo", "todos.json")
        self._relocate_default_path("traces_dir", "traces")
        self._relocate_default_path("metrics_file", "metrics", "metrics.jsonl")
        self._relocate_default_path("alerts_file", "metrics", "alerts.jsonl")
        self._relocate_default_path("artifacts_file", "artifacts", "manifest.jsonl")
        self._relocate_default_path("policy_audit_file", "policy", "audit.jsonl")
        self._relocate_default_path("eval_results_dir", "eval_results")
        self._relocate_default_path("dreams_dir", "dreams")
        self._relocate_default_path("workflows_dir", "workflows")
        self._relocate_default_path("loops_dir", "loops")
        self._relocate_default_path("loop_runs_dir", "loop_runs")
        self._relocate_default_path("runtime_config_file", "runtime", "config.json")
        self._relocate_default_path("mcp_config_file", "mcp", "servers.json")
        self._relocate_default_path("mcp_tools_cache_file", "mcp", "tools-cache.json")
        self._relocate_default_path("repo_index_file", "repo_index", "index.json")

    def _relocate_default_path(self, attr: str, *parts: str) -> None:
        current = getattr(self, attr)
        if current == default_runtime_path(*parts):
            object.__setattr__(self, attr, Path(self.runtime_home) / Path(*parts))

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
        self.policy_audit_file.parent.mkdir(parents=True, exist_ok=True)
        self.eval_results_dir.mkdir(parents=True, exist_ok=True)
        self.dreams_dir.mkdir(parents=True, exist_ok=True)
        self.workflows_dir.mkdir(parents=True, exist_ok=True)
        self.loops_dir.mkdir(parents=True, exist_ok=True)
        self.loop_runs_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_config_file.parent.mkdir(parents=True, exist_ok=True)
        self.mcp_config_file.parent.mkdir(parents=True, exist_ok=True)
        self.mcp_tools_cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.repo_index_file.parent.mkdir(parents=True, exist_ok=True)
