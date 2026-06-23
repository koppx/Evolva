from __future__ import annotations

import json
import subprocess

import pytest

from evolva.agent.capabilities import Capability
from evolva.agent.context import ContextStore
from evolva.agent.memory import MemoryStore
from evolva.agent.policy import PolicyConfig, PolicyEngine
from evolva.agent.sandbox import DockerWorkspaceBackend, Sandbox, SandboxPolicy, build_backend, parse_command
from evolva.agent.skills import SkillStore
from evolva.agent.todo import TodoStore
from evolva.storage import read_jsonl
from evolva.tools.base import Tool, ToolRegistry, ToolResult
from evolva.tools.builtin import build_registry


def make_registry(tmp_path):
    sandbox = Sandbox(SandboxPolicy(tmp_path, tmp_path / "workspace"))
    memory = MemoryStore(tmp_path / "memory.jsonl")
    skills = SkillStore(tmp_path / "skills")
    context = ContextStore(tmp_path / "context.json")
    todos = TodoStore(tmp_path / "todos.json")
    return build_registry(sandbox, memory, skills, context, todos), context


def test_sandbox_resolve_and_describe(tmp_path):
    sandbox = Sandbox(SandboxPolicy(tmp_path, tmp_path / "workspace"))
    assert sandbox.resolve("workspace/a.txt") == (tmp_path / "workspace" / "a.txt").resolve()
    assert "shell=enabled" in sandbox.describe()
    assert "backend=local" in sandbox.describe()
    with pytest.raises(ValueError, match="escapes"):
        sandbox.resolve("../escape.txt")


def test_sandbox_shell_disabled_dangerous_timeout_and_python(tmp_path):
    disabled = Sandbox(SandboxPolicy(tmp_path, tmp_path / "workspace", allow_shell=False))
    assert not disabled.run_shell("echo hi").ok

    sandbox = Sandbox(SandboxPolicy(tmp_path, tmp_path / "workspace"))
    assert not sandbox.run_shell("git reset --hard").ok
    assert not sandbox.run_shell("echo hi && echo bye").ok
    assert not sandbox.run_shell("echo hi", cwd="missing").ok
    ok = sandbox.run_shell("printf hello", cwd=".")
    assert ok.ok and ok.output == "hello"
    assert ok.data["argv"] == ["printf", "hello"]
    assert ok.data["backend"] == "local"
    py_ok = sandbox.run_python("print('py')")
    assert py_ok.ok and py_ok.output == "py"
    py_bad = sandbox.run_python("raise SystemExit(3)")
    assert not py_bad.ok and py_bad.data["returncode"] == 3
    smoke = sandbox.smoke_check()
    assert smoke.ok
    assert "evolva-sandbox-ok" in smoke.output
    assert smoke.data["backend"] == "local"


def test_sandbox_rolls_back_workspace_on_failed_python(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    existing = workspace / "state.txt"
    existing.write_text("before", encoding="utf-8")
    sandbox = Sandbox(SandboxPolicy(tmp_path, workspace))

    result = sandbox.run_python(
        "from pathlib import Path\n"
        "Path('workspace/state.txt').write_text('after')\n"
        "Path('workspace/new.txt').write_text('new')\n"
        "raise SystemExit(3)"
    )

    assert not result.ok
    assert "Rolled back sandbox snapshot" in result.output
    assert existing.read_text(encoding="utf-8") == "before"
    assert not (workspace / "new.txt").exists()
    assert result.data["rollback"]["restored"] == 1
    assert result.data["rollback"]["removed"] == 1


def test_sandbox_keeps_workspace_changes_on_success(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sandbox = Sandbox(SandboxPolicy(tmp_path, workspace))

    result = sandbox.run_python("from pathlib import Path\nPath('workspace/success.txt').write_text('ok')")

    assert result.ok
    assert (workspace / "success.txt").read_text(encoding="utf-8") == "ok"
    assert "rollback" not in result.data


def test_sandbox_writable_roots_restrict_file_tools(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sandbox = Sandbox(SandboxPolicy(tmp_path, workspace, writable_roots=(workspace,)))
    assert sandbox.resolve_write("workspace/ok.txt") == (workspace / "ok.txt").resolve()
    with pytest.raises(ValueError, match="outside sandbox writable roots"):
        sandbox.resolve_write("outside.txt")

    memory = MemoryStore(tmp_path / "memory.jsonl")
    skills = SkillStore(tmp_path / "skills")
    context = ContextStore(tmp_path / "context.json")
    todos = TodoStore(tmp_path / "todos.json")
    reg = build_registry(sandbox, memory, skills, context, todos)

    assert reg.call("write_file", {"path": "workspace/ok.txt", "content": "ok"}).ok
    denied = reg.call("write_file", {"path": "outside.txt", "content": "nope"})
    assert not denied.ok
    assert "outside sandbox writable roots" in denied.output
    assert not (tmp_path / "outside.txt").exists()


def test_parse_command_rejects_shell_control_operators(tmp_path):
    spec = parse_command("python3 -m pytest -q", cwd=tmp_path, timeout=5)
    assert spec.argv == ["python3", "-m", "pytest", "-q"]
    assert spec.executable == "python3"
    for command in ["echo ok | sh", "echo ok; rm file", "echo $(pwd)", "echo ok > out"]:
        with pytest.raises(ValueError, match="not allowed"):
            parse_command(command, cwd=tmp_path, timeout=5)


def test_docker_backend_builds_isolated_argv_without_shell(tmp_path):
    calls = []

    def fake_runner(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="inside\n", stderr="")

    backend = DockerWorkspaceBackend(
        root=tmp_path,
        image="python:3.12-slim",
        network="none",
        read_only=True,
        memory="256m",
        cpus="0.5",
        pids_limit=64,
        user="123:456",
        runner=fake_runner,
    )
    spec = parse_command("python3 -c 'print(42)'", cwd=tmp_path, timeout=7)

    result = backend.run_command(spec)

    assert result.ok
    assert result.output == "inside"
    docker_args, kwargs = calls[0]
    assert kwargs["shell"] is False
    assert docker_args[:3] == ["docker", "run", "--rm"]
    assert ["--network", "none"] == docker_args[3:5]
    assert ["--memory", "256m"] == docker_args[5:7]
    assert ["--cpus", "0.5"] == docker_args[7:9]
    assert ["--pids-limit", "64"] == docker_args[9:11]
    assert ["--user", "123:456"] == docker_args[11:13]
    assert "--read-only" in docker_args
    assert "--tmpfs" in docker_args
    assert f"type=bind,src={tmp_path.resolve()},dst={tmp_path.resolve()}" in docker_args
    assert docker_args[-4:] == ["python:3.12-slim", "python3", "-c", "print(42)"]
    assert result.data["backend"] == "docker"
    assert result.data["read_only"] is True
    assert result.data["memory"] == "256m"
    assert result.data["cpus"] == "0.5"
    assert result.data["pids_limit"] == 64
    assert result.data["user"] == "123:456"


def test_docker_backend_reports_missing_docker(tmp_path):
    def missing_runner(*args, **kwargs):
        raise FileNotFoundError("docker")

    backend = DockerWorkspaceBackend(root=tmp_path, runner=missing_runner)
    spec = parse_command("python3 --version", cwd=tmp_path, timeout=5)

    result = backend.run_command(spec)

    assert not result.ok
    assert "Docker executable not found" in result.output
    assert result.data["backend"] == "docker"


def test_sandbox_backend_selection_and_describe(tmp_path):
    local = Sandbox(SandboxPolicy(tmp_path, tmp_path / "workspace", backend="local"))
    assert local.backend.name == "local"

    docker_backend = build_backend(
        SandboxPolicy(
            tmp_path,
            tmp_path / "workspace",
            backend="container",
            container_image="python:test",
            container_memory="128m",
            container_cpus="0.25",
            container_pids_limit=32,
            container_user="1000:1000",
        )
    )
    assert isinstance(docker_backend, DockerWorkspaceBackend)
    assert docker_backend.image == "python:test"
    assert docker_backend.memory == "128m"
    assert docker_backend.cpus == "0.25"
    assert docker_backend.pids_limit == 32

    docker = Sandbox(SandboxPolicy(tmp_path, tmp_path / "workspace", backend="docker", container_image="python:test"))
    rendered = docker.describe()
    assert "backend=docker" in rendered
    assert "image=python:test" in rendered
    assert "pids_limit=128" in rendered
    with pytest.raises(ValueError, match="Unknown sandbox backend"):
        build_backend(SandboxPolicy(tmp_path, tmp_path / "workspace", backend="bogus"))


def test_policy_decisions_for_network_shell_paths_and_secrets(tmp_path):
    policy = PolicyEngine(PolicyConfig(root=tmp_path, workspace=tmp_path / "workspace", network_enabled=False))
    assert not policy.check_tool("web_search", {"query": "x"}).allowed
    assert not policy.check_tool("shell", {"command": "rm -rf /"}).allowed
    secret = policy.check_tool("write_file", {"path": "a.txt", "content": "api_key='1234567890'"})
    assert secret.allowed and secret.requires_confirmation and secret.risk == "high"
    assert secret.capabilities == ["write_file"]
    assert "secret_in_file" in secret.audit_tags
    assert not policy.check_tool("read_file", {"path": "../secret"}).allowed
    assert policy.check_tool("list_files", {"path": "."}).allowed
    assert "denied_shell_patterns" in policy.as_tool_result().output


def test_policy_profiles_deny_high_risk_capabilities(tmp_path):
    safe_policy = PolicyEngine(PolicyConfig(root=tmp_path, workspace=tmp_path / "workspace", profile="safe"))
    decision = safe_policy.check_tool("shell", {"command": "echo hi"}, capabilities=[Capability.RUN_COMMAND.value])
    assert not decision.allowed
    assert "disabled in safe profile" in decision.reason
    assert decision.capabilities == ["run_command"]

    dev_policy = PolicyEngine(PolicyConfig(root=tmp_path, workspace=tmp_path / "workspace", profile="dev"))
    allowed = dev_policy.check_tool("shell", {"command": "echo hi"}, capabilities=[Capability.RUN_COMMAND.value])
    assert allowed.allowed and allowed.requires_confirmation


def test_policy_custom_profile_rules_and_audit_log(tmp_path):
    audit_file = tmp_path / "policy" / "audit.jsonl"
    policy = PolicyEngine(
        PolicyConfig(
            root=tmp_path,
            workspace=tmp_path / "workspace",
            profile="ci",
            audit_file=audit_file,
            profile_rules={"ci": {"deny_capabilities": [Capability.WRITE_FILE.value], "network_enabled": False}},
        )
    )

    denied = policy.check_tool("write_file", {"path": "a.txt", "content": "ok"}, capabilities=[Capability.WRITE_FILE.value])
    network = policy.check_tool("web_search", {"query": "x"}, capabilities=[Capability.NETWORK.value])

    assert not denied.allowed
    assert "disabled in ci profile" in denied.reason
    assert not network.allowed
    rows = read_jsonl(audit_file)
    assert [row["tool"] for row in rows] == ["write_file", "web_search"]
    assert rows[0]["allowed"] is False
    assert rows[0]["capabilities"] == [Capability.WRITE_FILE.value]
    assert "profile_denied" in rows[0]["audit_tags"]
    assert "content" not in rows[0]


def test_policy_file_extends_profiles_and_patterns(tmp_path):
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(
        json.dumps(
            {
                "denied_shell_patterns": [r"\bcurl\b"],
                "profiles": {
                    "prod-lite": {
                        "deny_capabilities": [Capability.MCP_CALL.value],
                        "allow_shell": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    policy = PolicyEngine(PolicyConfig(root=tmp_path, workspace=tmp_path / "workspace", profile="prod-lite", policy_file=policy_file))

    shell = policy.check_tool("shell", {"command": "curl https://example.com"}, capabilities=[Capability.RUN_COMMAND.value])
    mcp = policy.check_tool("mcp_call", {"server": "x"}, capabilities=[Capability.MCP_CALL.value])

    assert not shell.allowed and "Denied dangerous pattern" in shell.reason
    assert not mcp.allowed and "disabled in prod-lite profile" in mcp.reason
    info = policy.as_tool_result().output
    assert f"policy_file={policy_file}" in info
    assert "denied_shell_patterns=9" in info


def test_tool_registry_register_get_call_describe_errors():
    reg = ToolRegistry()
    reg.register(Tool("ok", "demo", {"x": "int"}, lambda x: ToolResult(True, str(x))))
    assert reg.names() == ["ok"]
    assert "demo" in reg.describe()
    assert reg.call("ok", {"x": 7}).output == "7"
    with pytest.raises(KeyError, match="Unknown tool"):
        reg.get("missing")


def test_builtin_file_memory_context_todo_and_policy_tools(tmp_path):
    reg, context = make_registry(tmp_path)
    assert "write_file" in reg.names()
    assert "capabilities=['write_file']" in reg.describe()
    assert reg.call("write_file", {"path": "workspace/a.txt", "content": "hello"}).ok
    assert reg.call("write_file", {"path": "workspace/a.txt", "content": " world", "append": True}).ok
    read = reg.call("read_file", {"path": "workspace/a.txt"})
    assert read.ok and read.output == "hello world"
    assert "Wrote file" in context.render("a.txt")
    assert "file\tworkspace/a.txt" in reg.call("list_files", {"path": "workspace"}).output
    assert not reg.call("read_file", {"path": "missing.txt"}).ok

    assert reg.call("remember", {"kind": "fact", "content": "pytest matters"}).ok
    low = reg.call("remember", {"kind": "fact", "content": "low confidence note", "confidence": 0.1})
    assert low.ok and "low confidence note" not in reg.call("recall", {"query": "confidence"}).output
    assert "pytest" in reg.call("recall", {"query": "pytest"}).output
    assert "low_confidence_active" in reg.call("memory_audit", {}).output
    assert reg.call("memory_status", {"item_id": low.data["id"], "status": "quarantined", "reason": "not verified"}).ok
    assert reg.call("save_skill", {"name": "Testing", "content": "Run pytest"}).ok
    assert reg.call("save_skill", {"name": "Draft Testing", "content": "Do not inject", "status": "draft", "triggers": ["draft"]}).ok
    assert "testing" in reg.call("list_skills", {}).output
    assert "Do not inject" not in reg.call("recall", {"query": "draft"}).output
    assert "active_missing" in reg.call("skill_audit", {}).output
    assert reg.call("skill_status", {"name": "Draft Testing", "status": "active", "reason": "reviewed"}).ok
    assert reg.call("context_add", {"kind": "note", "content": "note"}).ok
    assert "note" in reg.call("context_view", {"query": "note"}).output
    assert "Compacted" in reg.call("context_compact", {"title": "summary"}).output
    todo = reg.call("todo_add", {"title": "task"})
    assert todo.ok and "#1" in todo.output
    assert "task" in reg.call("todo_list", {}).output
    assert "done" in reg.call("todo_update", {"todo_id": 1, "status": "done"}).output
    assert "Cleared 1" in reg.call("todo_clear", {}).output


def test_builtin_shell_python_policy_mcp_and_delegate_absent(tmp_path):
    reg, _ = make_registry(tmp_path)
    assert "Sandbox root" in reg.call("sandbox_info", {}).output
    assert not reg.call("policy_info", {}).ok
    assert not reg.call("mcp_servers", {}).ok
    assert not reg.call("mcp_tools", {"server": "x"}).ok
    assert not reg.call("mcp_call", {"server": "x", "tool": "y"}).ok
    assert not reg.call("delegate_agent", {"role": "planner", "task": "x"}).ok
    assert not reg.call("collaborate", {"task": "x"}).ok


def test_builtin_multi_agent_tools_return_structured_reports(tmp_path):
    class FallbackCoordinator:
        def delegate_report(self, role, task, context=""):
            from evolva.agent.multi_agent import AgentRoleResult

            return AgentRoleResult(role=role, ok=True, output=f"{role}:{task}:{context}", status="fallback", latency_ms=1, fallback=True)

        def collaborate_report(self, task, roles=None, context=""):
            from evolva.agent.multi_agent import AgentRoleResult, MultiAgentRun

            chosen = roles or ["planner"]
            return MultiAgentRun(
                run_id="multi_test",
                task=task,
                roles=chosen,
                status="completed",
                started_at=1,
                ended_at=2,
                max_roles=4,
                results=[AgentRoleResult(role=chosen[0], ok=True, output="ok", status="fallback", latency_ms=1, fallback=True)],
            )

    reg, _ = make_registry(tmp_path)
    # Rebuild with a coordinator because the default make_registry omits it.
    from evolva.agent.context import ContextStore
    from evolva.agent.memory import MemoryStore
    from evolva.agent.sandbox import Sandbox, SandboxPolicy
    from evolva.agent.skills import SkillStore
    from evolva.agent.todo import TodoStore

    sandbox = Sandbox(SandboxPolicy(tmp_path, tmp_path / "workspace"))
    registry = build_registry(sandbox, MemoryStore(tmp_path / "m.jsonl"), SkillStore(tmp_path / "skills2"), ContextStore(tmp_path / "c.json"), TodoStore(tmp_path / "t.json"), FallbackCoordinator())

    delegated = registry.call("delegate_agent", {"role": "planner", "task": "plan", "context_text": "ctx"})
    assert delegated.ok
    assert delegated.data["delegate"]["role"] == "planner"
    assert delegated.data["delegate"]["tool_calls"] == []
    collab = registry.call("collaborate", {"task": "ship", "roles": ["planner"], "context_text": "ctx"})
    assert collab.ok
    assert collab.data["multi_agent"]["run_id"] == "multi_test"
    assert collab.data["multi_agent"]["results"][0]["tool_calls"] == []
    py = reg.call("python_exec", {"code": "print(2 + 3)"})
    assert py.ok and py.output == "5"
