from __future__ import annotations

import stat
from pathlib import Path

from evolva.config import AgentConfig, default_root, default_runtime_home, default_runtime_path, load_runtime_config, remove_runtime_config_keys, save_runtime_config


def test_agent_config_defaults_runtime_state_under_dot_evolva():
    cfg = AgentConfig()

    assert cfg.root == Path.cwd().resolve()
    assert cfg.runtime_home == cfg.root / ".evolva"
    assert cfg.workspace == cfg.runtime_home / "workspace"
    assert cfg.memory_file == cfg.runtime_home / "memory" / "memory.jsonl"
    assert cfg.context_file == cfg.runtime_home / "context" / "context.json"
    assert cfg.todo_file == cfg.runtime_home / "todo" / "todos.json"
    assert cfg.traces_dir == cfg.runtime_home / "traces"
    assert cfg.metrics_file == cfg.runtime_home / "metrics" / "metrics.jsonl"
    assert cfg.alerts_file == cfg.runtime_home / "metrics" / "alerts.jsonl"
    assert cfg.artifacts_file == cfg.runtime_home / "artifacts" / "manifest.jsonl"
    assert cfg.policy_audit_file == cfg.runtime_home / "policy" / "audit.jsonl"
    assert cfg.eval_results_dir == cfg.runtime_home / "eval_results"
    assert cfg.dreams_dir == cfg.runtime_home / "dreams"
    assert cfg.workflows_dir == cfg.runtime_home / "workflows"
    assert cfg.loops_dir == cfg.runtime_home / "loops"
    assert cfg.loop_runs_dir == cfg.runtime_home / "loop_runs"
    assert cfg.runtime_config_file == cfg.runtime_home / "runtime" / "config.json"
    assert cfg.mcp_config_file == cfg.runtime_home / "mcp" / "servers.json"
    assert cfg.mcp_tools_cache_file == cfg.runtime_home / "mcp" / "tools-cache.json"
    assert cfg.repo_index_file == cfg.runtime_home / "repo_index" / "index.json"
    assert cfg.multi_agent_auto_route is False


def test_agent_config_reads_root_env(monkeypatch, tmp_path):
    monkeypatch.setenv("EVOLVA_ROOT", str(tmp_path))

    assert default_root() == tmp_path.resolve()
    cfg = AgentConfig()
    assert cfg.root == tmp_path.resolve()
    assert cfg.runtime_home == tmp_path / ".evolva"


def test_agent_config_temp_root_relocates_default_runtime_paths(tmp_path):
    cfg = AgentConfig(root=tmp_path)

    assert cfg.runtime_home == tmp_path / ".evolva"
    assert cfg.workspace == tmp_path / ".evolva" / "workspace"
    assert cfg.runtime_config_file == tmp_path / ".evolva" / "runtime" / "config.json"
    assert cfg.mcp_config_file == tmp_path / ".evolva" / "mcp" / "servers.json"
    assert cfg.mcp_tools_cache_file == tmp_path / ".evolva" / "mcp" / "tools-cache.json"
    assert cfg.repo_index_file == tmp_path / ".evolva" / "repo_index" / "index.json"


def test_agent_config_preserves_explicit_runtime_paths(tmp_path):
    cfg = AgentConfig(
        root=tmp_path,
        runtime_home=tmp_path / "runtime-home",
        workspace=tmp_path / "custom-workspace",
        memory_file=tmp_path / "custom-memory.jsonl",
    )

    assert cfg.runtime_home == tmp_path / "runtime-home"
    assert cfg.workspace == tmp_path / "custom-workspace"
    assert cfg.memory_file == tmp_path / "custom-memory.jsonl"
    assert cfg.context_file == tmp_path / "runtime-home" / "context" / "context.json"


def test_runtime_config_helpers_use_runtime_home_env(monkeypatch, tmp_path):
    runtime_home = tmp_path / "runtime"
    monkeypatch.setenv("EVOLVA_RUNTIME_HOME", str(runtime_home))
    monkeypatch.setenv("EVOLVA_DISABLE_RUNTIME_CONFIG", "0")

    assert default_runtime_home() == runtime_home
    assert default_runtime_path("runtime", "config.json") == runtime_home / "runtime" / "config.json"

    saved = save_runtime_config({"api_key": "sk-test-value", "model": "demo", "unknown": "ignored"})
    path = runtime_home / "runtime" / "config.json"

    assert saved == {"api_key": "sk-test-value", "model": "demo"}
    assert load_runtime_config() == {"api_key": "sk-test-value", "model": "demo"}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    remaining = remove_runtime_config_keys(["api_key"])
    assert remaining == {"model": "demo"}
    assert load_runtime_config() == {"model": "demo"}


def test_agent_config_reads_request_timeout_from_runtime_config(monkeypatch, tmp_path):
    runtime_home = tmp_path / "runtime"
    monkeypatch.setenv("EVOLVA_RUNTIME_HOME", str(runtime_home))
    monkeypatch.setenv("EVOLVA_DISABLE_RUNTIME_CONFIG", "0")
    monkeypatch.delenv("OPENAI_REQUEST_TIMEOUT", raising=False)

    save_runtime_config({"request_timeout": 37, "memory_context_min_confidence": 0.8})

    assert AgentConfig().request_timeout == 37
    assert AgentConfig().memory_context_min_confidence == 0.8


def test_agent_config_reads_sandbox_isolation_env(monkeypatch):
    monkeypatch.setenv("EVOLVA_SANDBOX_WRITABLE_ROOTS", "workspace:tmp")
    monkeypatch.setenv("EVOLVA_SANDBOX_SNAPSHOT_ROOTS", "workspace")
    monkeypatch.setenv("EVOLVA_SANDBOX_ROLLBACK_ON_FAILURE", "0")
    monkeypatch.setenv("EVOLVA_SANDBOX_MAX_SNAPSHOT_BYTES", "1234")

    cfg = AgentConfig()

    assert cfg.sandbox_writable_roots == (Path("workspace"), Path("tmp"))
    assert cfg.sandbox_snapshot_roots == (Path("workspace"),)
    assert cfg.sandbox_rollback_on_failure is False
    assert cfg.sandbox_max_snapshot_bytes == 1234


def test_agent_config_reads_policy_file_env(monkeypatch, tmp_path):
    policy_file = tmp_path / "policy.json"
    monkeypatch.setenv("EVOLVA_POLICY_FILE", str(policy_file))

    cfg = AgentConfig()

    assert cfg.policy_file == policy_file
