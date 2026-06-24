from __future__ import annotations

import json
import sys
import threading
import time
from argparse import Namespace
from dataclasses import replace
from pathlib import Path

import pytest

from evolva.agent.core import EvolvaAgent, SYSTEM_PROMPT
from evolva.agent.llm import LLMResponse
from evolva.agent.mcp import MCPClient, MCPManager, MCPServerConfig, render_mcp_result
from evolva.agent.mcp_presets import get_mcp_preset, list_mcp_presets, parse_env_pairs
from evolva.agent.tracing import TraceRecorder
from evolva.cli import build_parser, dream_cmd, evolve_cmd, handle_command, loop_cmd, main, mcp_cmd, metrics_cmd, once, optimize_cmd, sandbox_cmd
from evolva.eval.harness import EvalHarness, EvalResult, render_gate, render_results
from evolva.eval.scorers import ScoreCheck, ScorerRegistry
import evolva.tui as tui_module
from evolva.tui import EvolvaInlineTUI, EvolvaTUI, TUIConfirmation
from evolva.workflow.engine import WorkflowEngine


def test_agent_fallback_remember_read_list_and_image(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    assert "Evolva" in SYSTEM_PROMPT
    assert agent.set_model("test-switch-model") == "test-switch-model"
    assert agent.config.model == "test-switch-model"
    assert agent.coordinator.llm is agent.llm
    assert agent.chat("remember Use pytest").answer == "已记住。"
    assert "pytest" in agent.memory.context("pytest")
    (temp_config.root / "note.txt").write_text("hello")
    assert agent.chat("read note.txt").answer == "hello"
    assert "note.txt" in agent.chat("list files").answer
    assert "规则模式" in agent.chat("describe", image_sources=["x.png"]).answer


def test_agent_call_tool_policy_confirmation_and_unknown(temp_config):
    denied = EvolvaAgent(temp_config, assume_yes=False, confirmer=type("No", (), {"ask": lambda self, name, args: False})())
    result = denied._call_tool("shell", {"command": "printf hi"})
    assert not result.ok and "User denied" in result.output

    yes = EvolvaAgent(temp_config, assume_yes=True)
    ok = yes._call_tool("shell", {"command": "printf hi"})
    assert ok.ok and ok.output == "hi"
    bad = yes._call_tool("shell", {"command": "git reset --hard"})
    assert not bad.ok and "Policy denied" in bad.output
    missing = yes._call_tool("missing", {})
    assert not missing.ok and "Tool error" in missing.output


def test_agent_uses_langgraph_runtime_for_llm_tool_loop(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    responses = iter([
        {"thought": "write file", "tool": {"name": "write_file", "args": {"path": "evolva/workspace/langgraph.txt", "content": "ok"}}, "final": None},
        {"thought": "done", "tool": None, "final": "LangGraph completed"},
    ])

    class FakeLLM:
        available = True

        def chat(self, messages, *, timeout=None):
            assert timeout == temp_config.request_timeout
            return type("Resp", (), {"content": json.dumps(next(responses))})()

    agent.llm = FakeLLM()
    result = agent.chat("create langgraph file")

    assert result.answer == "LangGraph completed"
    assert not result.failed_tools
    assert any("TOOL write_file" in log for log in result.tool_logs)
    assert (temp_config.workspace / "langgraph.txt").read_text() == "ok"
    run_id = agent.tracer.list_runs(limit=1)[0]["run_id"]
    trace = agent.tracer.load(run_id)
    meta_events = [event for event in trace["events"] if event["kind"] == "run_meta"]
    assert meta_events[-1]["data"]["runtime"] == "langgraph"
    assert meta_events[-1]["data"]["graph_nodes"] == agent.graph_nodes()
    assert {event["data"].get("node") for event in trace["events"] if event["kind"] == "langgraph_node"} >= {"prepare", "llm", "tool", "observe", "persist", "auto_evolve"}

def test_agent_auto_evolve_records_report_in_trace_and_context(temp_config):
    agent = EvolvaAgent(replace(temp_config, max_steps=1), assume_yes=True)
    agent.llm = type(
        "FakeLLM",
        (),
        {"available": True, "chat": lambda self, messages: type("Resp", (), {"content": json.dumps({"tool": {"name": "missing", "args": {}}, "final": None})})()},
    )()
    result = agent.chat("run missing tool")

    assert result.failed_tools == ["missing"]
    assert result.stopped_by_limit
    run_id = agent.tracer.list_runs(limit=1)[0]["run_id"]
    trace = agent.tracer.load(run_id)
    events = [event for event in trace["events"] if event["kind"] == "auto_evolve"]
    assert events and events[-1]["data"]["report"]["trigger"] == "tool_failure"
    assert "tool_failure" in agent.context.render("evolution")


def test_agent_messages_include_context_memory_todos_skills_and_images(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    agent.memory.add("fact", "pytest matters")
    agent.context.add("decision", "Use sandbox")
    agent.todos.add("Write tests")
    agent.skills.upsert("Testing", "Run pytest")
    image = temp_config.root / "tiny.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    messages = agent._messages("pytest", "scratch", image_sources=["tiny.png"])
    system = messages[0]["content"]
    assert "pytest matters" in system
    assert "Use sandbox" in system
    assert "Write tests" in system
    assert "Run pytest" in system
    assert "scratch" in system
    assert isinstance(messages[-1]["content"], list)


def test_multi_agent_roles_fallback_and_errors(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    coord = agent.coordinator
    assert "planner" in coord.list_roles()
    assert "Planner fallback" in coord.delegate("planner", "plan tests")
    assert "Reviewer fallback" in coord.delegate("reviewer", "review tests")
    assert "Coder fallback" in coord.delegate("coder", "edit")
    out = json.loads(coord.collaborate("ship", roles=["planner", "reviewer"]))
    assert set(out) == {"planner", "reviewer"}
    with pytest.raises(KeyError):
        coord.delegate("missing", "x")
    with pytest.raises(ValueError):
        coord.delegate("planner", " ")


def test_multi_agent_reports_budget_and_llm_failure_fallback(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    coord = agent.coordinator
    coord.max_roles_per_run = 2
    report = coord.collaborate_report("ship safely", roles=["planner", "planner", "reviewer"])
    assert report.status == "completed"
    assert report.roles == ["planner", "reviewer"]
    assert report.results[0].fallback
    assert report.run_id.startswith("multi_")
    assert "Multi-agent run" in report.render()

    with pytest.raises(ValueError, match="too many roles"):
        coord.collaborate_report("ship", roles=["planner", "researcher", "coder"])
    with pytest.raises(KeyError):
        coord.collaborate_report("ship", roles=["missing"])

    class FailingLLM:
        available = True

        def chat(self, messages, **kwargs):
            raise RuntimeError("llm down")

    coord.llm = FailingLLM()
    failed = coord.delegate_report("reviewer", "review")
    assert not failed.ok
    assert failed.fallback
    assert failed.status == "failed_fallback"
    assert "llm down" in failed.error


def test_task_router_selects_roles_for_task_types(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    router = agent.coordinator

    assert router.route_task("hello").label == "simple"
    assert router.route_task("read README").label == "tool_task"
    assert router.route_task("调研 MCP 接入方案").roles == ["researcher", "reviewer"]
    assert router.route_task("实现一个 task router 并补测试").roles == ["planner", "coder", "reviewer"]
    assert router.route_task("review 这次改动有没有风险").roles == ["reviewer"]
    complex_route = router.route_task("设计技术方案，完成实现和测试，并评审生产化风险")
    assert complex_route.label == "complex"
    assert complex_route.roles == ["planner", "researcher", "coder", "reviewer"]
    capped = router.route_task("设计技术方案，完成实现和测试，并评审生产化风险", max_roles=2)
    assert capped.roles == ["planner", "reviewer"]


def test_collaborate_uses_task_router_when_roles_are_omitted(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    report = agent.coordinator.collaborate_report("调研 MCP 接入方案")

    assert report.route
    assert report.route["label"] == "research"
    assert report.roles == ["researcher", "reviewer"]


def test_agent_chat_auto_routes_complex_tasks_into_context_and_trace(temp_config):
    config = replace(temp_config, multi_agent_auto_route=True)
    agent = EvolvaAgent(config, assume_yes=True)

    class RoutedLLM:
        available = True

        def chat(self, messages, **kwargs):
            return LLMResponse(content=json.dumps({"thought": "done", "tool": None, "final": "routed answer"}))

    agent.llm = RoutedLLM()
    agent.coordinator.llm = agent.llm

    result = agent.chat("设计技术方案，完成实现和测试，并评审生产化风险")
    trace = agent.tracer.load(agent.tracer.list_runs(limit=1)[0]["run_id"])
    kinds = [event["kind"] for event in trace["events"]]

    assert result.answer == "routed answer"
    assert "task_route" in kinds
    assert "multi_agent_auto_route" in kinds
    assert "Auto task route `complex`" in agent.context.render("task route")


def test_agent_chat_can_disable_auto_task_router(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)

    class SimpleLLM:
        available = True

        def chat(self, messages, **kwargs):
            return LLMResponse(content=json.dumps({"thought": "done", "tool": None, "final": "plain answer"}))

    agent.llm = SimpleLLM()
    agent.coordinator.llm = agent.llm

    result = agent.chat("设计技术方案，完成实现和测试，并评审生产化风险")
    trace = agent.tracer.load(agent.tracer.list_runs(limit=1)[0]["run_id"])

    assert result.answer == "plain answer"
    assert "task_route" not in [event["kind"] for event in trace["events"]]


def test_sub_agent_can_call_allowed_tools_through_governed_runner(temp_config):
    (temp_config.root / "brief.md").write_text("production notes", encoding="utf-8")
    agent = EvolvaAgent(temp_config, assume_yes=True)

    class ToolCallingLLM:
        available = True

        def __init__(self):
            self.calls = 0

        def chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    content=json.dumps(
                        {
                            "thought": "Need to inspect the file.",
                            "tool": {"name": "read_file", "args": {"path": "brief.md"}},
                            "final": None,
                        }
                    )
                )
            assert "production notes" in messages[-1]["content"]
            return LLMResponse(content=json.dumps({"thought": "Enough evidence.", "tool": None, "final": "Found production notes."}))

    agent.coordinator.llm = ToolCallingLLM()
    result = agent.coordinator.delegate_report("researcher", "inspect brief")

    assert result.ok
    assert result.status == "completed"
    assert result.output == "Found production notes."
    assert result.tool_calls[0]["tool"] == "read_file"
    assert result.tool_calls[0]["ok"] is True


def test_sub_agent_rejects_tools_outside_role_scope(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)

    class WriteAttemptLLM:
        available = True

        def chat(self, messages, **kwargs):
            return LLMResponse(
                content=json.dumps(
                    {
                        "thought": "Try an unsafe write.",
                        "tool": {"name": "write_file", "args": {"path": "denied.txt", "content": "nope"}},
                        "final": None,
                    }
                )
            )

    agent.coordinator.llm = WriteAttemptLLM()
    result = agent.coordinator.delegate_report("researcher", "write a file")

    assert not result.ok
    assert result.status == "tool_denied"
    assert "not allowed" in result.error
    assert result.tool_calls[0]["tool"] == "write_file"
    assert result.tool_calls[0]["status"] == "denied"
    assert not (temp_config.root / "denied.txt").exists()


def test_sub_agent_default_roles_do_not_allow_python_write_bypass(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)

    class PythonWriteAttemptLLM:
        available = True

        def chat(self, messages, **kwargs):
            return LLMResponse(
                content=json.dumps(
                    {
                        "thought": "Try a write through python.",
                        "tool": {"name": "python_exec", "args": {"code": "from pathlib import Path; Path('bypass.txt').write_text('nope')"}},
                        "final": None,
                    }
                )
            )

    agent.coordinator.llm = PythonWriteAttemptLLM()
    result = agent.coordinator.delegate_report("coder", "write through python")

    assert not result.ok
    assert result.status == "tool_denied"
    assert "not allowed" in result.error
    assert result.tool_calls[0]["tool"] == "python_exec"
    assert not (temp_config.workspace / "bypass.txt").exists()


def test_trace_recorder_list_load_render_disabled_and_path_sanitization(tmp_path):
    traces = TraceRecorder(tmp_path / "traces")
    run_id = traces.start("hello", meta={"a": 1})
    traces.event("tool_call", {"tool": "noop"})
    path = traces.end("done")
    assert path and path.exists()
    assert traces.list_runs(limit=1)[0]["run_id"] == run_id
    assert traces.list_runs(limit=1)[0]["schema_version"] == "trace.v1"
    assert traces.load(run_id)["final_answer"] == "done"
    assert traces.load(run_id)["summary"]["event_count"] == 2
    assert "tool_call" in traces.render(run_id)
    assert traces.replay_prompt(run_id) == "hello"
    assert traces.path_for("../bad.json").name == "__bad.json"

    disabled = TraceRecorder(tmp_path / "disabled", enabled=False)
    disabled.start("x")
    disabled.event("ignored", {})
    assert disabled.end("y") is None


def test_workflow_engine_tool_role_agent_templates_and_errors(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    wf = WorkflowEngine(agent)
    result = wf.run(
        {
            "id": "demo",
            "nodes": [
                {"id": "write", "type": "tool", "tool": "write_file", "args": {"path": "evolva/workspace/a.txt", "content": "hello"}},
                {"id": "read", "type": "tool", "tool": "read_file", "args": {"path": "evolva/workspace/a.txt"}},
                {"id": "role", "type": "role", "role": "reviewer", "task": "Review {{read}}"},
                {"id": "agent", "type": "agent", "prompt": "remember workflow lesson"},
            ],
        }
    )
    assert result.ok
    assert result.outputs["read"] == "hello"
    assert "Reviewer fallback" in result.outputs["role"]
    assert result.outputs["agent"] == "已记住。"

    bad = wf.run({"id": "bad", "nodes": [{"id": "x", "type": "unknown"}]})
    assert not bad.ok and "Unknown workflow" in bad.outputs["x"]
    continued = wf.run({"id": "cont", "nodes": [{"id": "x", "type": "unknown", "continue_on_error": True}, {"id": "y", "type": "tool", "tool": "sandbox_info"}]})
    assert continued.ok and "Sandbox root" in continued.outputs["y"]


def test_workflow_engine_runs_explicit_dag_and_rejects_cycles(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    wf = WorkflowEngine(agent)
    result = wf.run(
        {
            "id": "dag",
            "nodes": [
                {"id": "read", "depends_on": ["write"], "type": "tool", "tool": "read_file", "args": {"path": "evolva/workspace/dag.txt"}},
                {"id": "write", "depends_on": [], "type": "tool", "tool": "write_file", "args": {"path": "evolva/workspace/dag.txt", "content": "dag-ok"}},
            ],
        }
    )
    assert result.ok
    assert list(result.outputs) == ["write", "read"]
    assert result.outputs["read"] == "dag-ok"
    assert "depends_on=write" in "\n".join(result.logs)

    cycle = wf.run({"id": "cycle", "nodes": [{"id": "a", "depends_on": ["b"]}, {"id": "b", "depends_on": ["a"]}]})
    assert not cycle.ok and "cycle" in cycle.logs[0]

    missing = wf.run({"id": "missing", "nodes": [{"id": "a", "depends_on": ["b"]}]})
    assert not missing.ok and "missing node" in missing.logs[0]


def test_workflow_engine_persists_and_resumes_successful_nodes(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    wf = WorkflowEngine(agent)
    first = wf.run(
        {
            "id": "resume-wf",
            "nodes": [
                {"id": "write", "type": "tool", "tool": "write_file", "args": {"path": "evolva/workspace/resume.txt", "content": "resume-ok"}},
                {"id": "bad", "type": "unknown"},
            ],
        }
    )
    assert not first.ok
    assert first.status == "failed"
    assert first.path and Path(first.path).exists()

    resumed = wf.run(
        {
            "id": "resume-wf",
            "nodes": [
                {"id": "write", "type": "tool", "tool": "write_file", "args": {"path": "evolva/workspace/resume.txt", "content": "resume-ok"}},
                {"id": "read", "type": "tool", "tool": "read_file", "args": {"path": "evolva/workspace/resume.txt"}},
            ],
        },
        resume=True,
    )

    assert resumed.ok
    assert resumed.status == "completed"
    assert "[resume] reused nodes=write" in resumed.logs[0]
    assert "resumed=True" in "\n".join(resumed.logs)
    assert resumed.outputs["read"] == "resume-ok"
    data = json.loads(Path(resumed.path).read_text(encoding="utf-8"))
    assert data["status"] == "completed"
    assert data["outputs"]["write"].startswith("Wrote")


def test_eval_harness_score_summary_report_and_run_file(temp_config, tmp_path):
    harness = EvalHarness(temp_config, assume_yes=True)
    harness.agent.memory.add("fact", "Eval remembers memory state")
    harness.agent.context.add("decision", "Eval checks context state")
    out = temp_config.workspace / "out.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("artifact ok", encoding="utf-8")
    corrupt = temp_config.workspace / "state.json.corrupt.1"
    corrupt.write_text("{bad json", encoding="utf-8")
    harness.agent.observability.record("mcp.timeout", tags={"tool": "mcp_tools"})
    harness.agent.observability.record("sandbox.rollback", tags={"tool": "python_exec"}, fields={"restored": 1, "removed": 1})
    harness.agent.policy.check_tool("shell", {"command": "rm -rf /"})
    report = harness.score_report(
        {
            "expected_contains": ["ok"],
            "forbidden_contains": ["bad"],
            "expected_regex": ["^ok$"],
            "expected_artifacts": ["evolva/workspace/out.txt", "../escape.txt"],
            "expected_file_globs": ["evolva/workspace/state.json.corrupt.*"],
            "expected_artifact_contains": [{"path": "evolva/workspace/out.txt", "contains": ["artifact"]}],
            "expected_memory": ["memory state"],
            "expected_context": ["context state"],
            "expected_metrics": [
                {"name": "mcp.timeout", "tags": {"tool": "mcp_tools"}},
                {"name": "sandbox.rollback", "tags": {"tool": "python_exec"}, "fields": {"restored": 1, "removed": 1}},
            ],
            "expected_policy_audit": [{"tool": "shell", "allowed": False, "risk": "critical", "audit_tags": ["dangerous_command"]}],
            "max_duration_ms": 500,
            "scorers": ["no_tool_error"],
        },
        "ok",
        [],
        duration_ms=10,
    )
    checks = report.booleans()
    assert checks["contains:ok"]
    assert checks["not_contains:bad"]
    assert checks["regex:^ok$"]
    assert checks["artifact_exists:evolva/workspace/out.txt"]
    assert checks["file_glob:evolva/workspace/state.json.corrupt.*"]
    assert checks["artifact_contains:evolva/workspace/out.txt:artifact"]
    assert not checks["artifact_inside_root:../escape.txt"]
    assert checks["memory:memory state"]
    assert checks["context:context state"]
    assert checks["metric:mcp.timeout"]
    assert checks["metric:sandbox.rollback"]
    assert checks["policy_audit:shell"]
    assert checks["duration<=500ms"]
    assert checks["no_tool_error"]
    assert report.dimensions()["artifact"] < 1.0

    results = [EvalResult("a", True, 1.0, {}, "ok"), EvalResult("b", False, 0.0, {}, "bad")]
    assert harness.summary(results) == {"total": 2, "passed": 1, "failed": 1, "avg_score": 0.5}
    report = harness.write_report(results, "unit")
    assert report.exists()
    assert "PASS a" in render_results(results)
    gate = harness.gate(results, min_score=0.4)
    assert not gate.ok and "eval task" in "\n".join(gate.regressions)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(harness.report_payload([EvalResult("a", True, 1.0, {}, "ok")], name="unit")))
    regression = harness.gate([EvalResult("a", False, 0.0, {}, "bad")], baseline_path=baseline, no_regression=True)
    assert not regression.ok and "regressed" in render_gate(regression)

    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text('\n# comment\n{"id":"fallback","input":"remember eval","expected_contains":["已记住"],"scorers":["no_tool_error"]}\n')
    run_results = harness.run_file(tasks)
    assert len(run_results) == 1 and run_results[0].passed


def test_eval_harness_custom_scorer_registry(temp_config):
    registry = ScorerRegistry()

    def custom(task, context):
        yield ScoreCheck("custom:ok", "needle" in context.text, dimension="business", evidence="domain-specific check")

    registry.register("business_rule", custom)
    harness = EvalHarness(temp_config, assume_yes=True, scorer_registry=registry)
    report = harness.score_report({"scorers": ["business_rule"]}, "needle", [])
    assert report.score == 1.0
    assert report.dimensions() == {"business": 1.0}


def test_mcp_manager_config_render_and_fake_client(monkeypatch, tmp_path):
    cfg = tmp_path / "servers.json"
    cfg.write_text(json.dumps({"servers": {"off": {"enabled": False, "command": "x"}, "demo": {"command": "python3", "args": ["s.py"], "env": {"A": "B"}}}}))
    manager = MCPManager(cfg, root=tmp_path)
    assert manager.list_servers() == ["demo"]

    class FakeClient:
        def list_tools(self):
            return [{"name": "ping", "description": "Ping"}]

        def call_tool(self, tool, arguments=None):
            return {"content": [{"type": "text", "text": f"{tool}:{arguments['x']}"}]}

        def close(self):
            self.closed = True

    fake = FakeClient()
    monkeypatch.setattr(manager, "client", lambda server: fake)
    assert manager.list_tools() == [{"name": "ping", "description": "Ping", "server": "demo"}]
    assert render_mcp_result(manager.call_tool("demo", "ping", {"x": 1})) == "ping:1"
    assert render_mcp_result({"content": [{"type": "image", "data": "x"}]}) == '{"type": "image", "data": "x"}'
    assert render_mcp_result({"plain": True}) == json.dumps({"plain": True}, ensure_ascii=False, indent=2)
    manager.clients["demo"] = fake
    manager.close()
    assert manager.clients == {}

    with pytest.raises(KeyError):
        MCPManager(tmp_path / "missing.json", root=tmp_path).client("missing")


def test_mcp_manager_tool_cache_and_health(monkeypatch, tmp_path):
    cfg = tmp_path / "servers.json"
    cache = tmp_path / "tools-cache.json"
    cfg.write_text(json.dumps({"servers": {"demo": {"command": "python3", "args": ["s.py"]}}}))
    manager = MCPManager(cfg, root=tmp_path, tool_cache_file=cache, tool_cache_ttl=600)

    class FakeClient:
        def __init__(self):
            self.calls = 0

        def list_tools(self):
            self.calls += 1
            return [{"name": "ping", "description": "Ping"}]

    fake = FakeClient()
    monkeypatch.setattr(manager, "client", lambda server: fake)
    rows = manager.list_tools()
    assert rows == [{"name": "ping", "description": "Ping", "server": "demo"}]
    assert fake.calls == 1
    assert json.loads(cache.read_text())["servers"]["demo"]["status"] == "ok"

    class FailingClient:
        def list_tools(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(manager, "client", lambda server: FailingClient())
    assert manager.list_tools() == rows
    health = manager.health("demo", refresh=True)
    assert health[0]["status"] == "degraded"
    assert health[0]["cached"] is True
    assert health[0]["tool_count"] == 1
    assert "boom" in health[0]["error"]


def test_mcp_client_framing_with_fake_process(tmp_path):
    client = MCPClient(MCPServerConfig("demo", "cmd"), root=tmp_path)
    written = []

    class FakeStdin:
        def write(self, data):
            written.append(data)

        def flush(self):
            pass

    client.proc = type("Proc", (), {"stdin": FakeStdin()})()
    client._write({"jsonrpc": "2.0", "id": 1, "result": "ok"})
    assert written[0].startswith(b"Content-Length: ")
    assert b'"result": "ok"' in written[0]


def test_mcp_client_request_timeout(tmp_path):
    script = tmp_path / "sleep_server.py"
    script.write_text("import time\nwhile True:\n    time.sleep(1)\n", encoding="utf-8")
    client = MCPClient(MCPServerConfig("slow", sys.executable, [str(script)], request_timeout=1), root=tmp_path)
    try:
        with pytest.raises(RuntimeError, match="timed out"):
            client.request("tools/list", {})
    finally:
        client.close()


def test_mcp_client_rejects_oversized_message(tmp_path):
    script = tmp_path / "huge_server.py"
    script.write_text(
        "import sys, time\n"
        "sys.stdout.buffer.write(b'Content-Length: 999\\r\\n\\r\\n')\n"
        "sys.stdout.buffer.flush()\n"
        "time.sleep(2)\n",
        encoding="utf-8",
    )
    client = MCPClient(MCPServerConfig("huge", sys.executable, [str(script)], request_timeout=2, max_message_bytes=10), root=tmp_path)
    try:
        with pytest.raises(RuntimeError, match="message too large"):
            client.request("tools/list", {})
    finally:
        client.close()


def test_cli_parser_main_once_and_handle_commands(monkeypatch, capsys, temp_config):
    parser = build_parser()
    assert parser.prog == "evolva"
    assert parser.parse_args(["--root", str(temp_config.root), "ask", "hi"]).root == temp_config.root
    assert parser.parse_args(["ask", "hi", "--image", "a.png", "--yes"]).image == ["a.png"]
    root_args = parser.parse_args([])
    assert root_args.cmd is None and root_args.chat is False
    tui_args = parser.parse_args(["tui", "--yes", "--no-tools"])
    assert tui_args.cmd == "tui" and tui_args.yes and tui_args.no_tools
    assert parser.parse_args(["tui", "--fullscreen"]).fullscreen
    assert parser.parse_args(["--fullscreen"]).fullscreen
    chat_args = parser.parse_args(["--chat", "--yes"])
    assert chat_args.cmd is None and chat_args.chat and chat_args.yes
    assert parser.parse_args(["mcp", "call", "s", "t", "{}", "--yes"]).mcp_cmd == "call"
    parsed_mcp_health = parser.parse_args(["mcp", "health", "s", "--refresh", "--yes"])
    assert parsed_mcp_health.mcp_cmd == "health" and parsed_mcp_health.refresh is True
    assert parser.parse_args(["metrics", "prometheus"]).metrics_cmd == "prometheus"
    assert parser.parse_args(["sandbox", "smoke", "--timeout", "3"]).sandbox_cmd == "smoke"
    parsed_eval = parser.parse_args(["eval", "evals/tasks/smoke.jsonl", "--baseline", "evals/baselines/smoke.json", "--min-score", "1.0", "--no-regression"])
    assert parsed_eval.no_regression and parsed_eval.min_score == 1.0
    parsed_mcp_add = parser.parse_args(["mcp", "add", "fs", "npx", "-y", "server", "."])
    assert parsed_mcp_add.mcp_cmd == "add" and parsed_mcp_add.args == ["-y", "server", "."]
    parsed_mcp_add_env = parser.parse_args(["mcp", "add", "search", "npx", "--env", "BRAVE_API_KEY=x", "server"])
    assert parsed_mcp_add_env.args == ["--env", "BRAVE_API_KEY=x", "server"]
    parsed_preset = parser.parse_args(["mcp", "add-preset", "playwright", "--name", "browser", "--yes"])
    assert parsed_preset.mcp_cmd == "add-preset" and parsed_preset.name == "browser"
    assert parser.parse_args(["evolve", "trace", "--apply"]).evolve_cmd == "trace"
    assert parser.parse_args(["optimize", "--apply"]).apply
    assert parser.parse_args(["dream", "--apply", "--limit", "3"]).apply
    assert parser.parse_args(["dream", "--min-confidence", "0.8", "--json"]).json
    assert parser.parse_args(["dream", "backlog", "--limit", "3"]).dream_cmd == "backlog"
    assert parser.parse_args(["dream", "verify", "--promote", "--json"]).dream_cmd == "verify"
    assert parser.parse_args(["loop", "list"]).loop_cmd == "list"
    assert parser.parse_args(["loop", "--yes", "run", "dream-loop", "--json"]).json

    monkeypatch.setattr("evolva.cli.AgentConfig", lambda: temp_config)
    assert once(Namespace(message="remember cli", image=None, yes=True, show_tools=False)) == 0
    assert "已记住" in capsys.readouterr().out
    assert main(["ask", "remember main", "--yes"]) == 0
    assert "已记住" in capsys.readouterr().out

    called = {}

    def fake_run_tui(assume_yes=False, show_tools=True, config=None):
        called["tui"] = (assume_yes, show_tools, config.root)
        return 0

    monkeypatch.setattr("evolva.cli.run_tui", fake_run_tui)
    assert main([]) == 0
    assert called["tui"] == (False, True, temp_config.root)

    def fake_fullscreen_tui(assume_yes=False, show_tools=True, config=None):
        called["fullscreen"] = (assume_yes, show_tools, config.root)
        return 0

    monkeypatch.setattr("evolva.cli.run_fullscreen_tui", fake_fullscreen_tui)
    assert main(["tui", "--fullscreen", "--yes", "--no-tools"]) == 0
    assert called["fullscreen"] == (True, False, temp_config.root)

    def fake_chat(args):
        called["chat"] = (args.yes, args.show_tools)
        return 0

    monkeypatch.setattr("evolva.cli.chat", fake_chat)
    assert main(["--chat", "--yes"]) == 0
    assert called["chat"] == (True, False)

    agent = EvolvaAgent(temp_config, assume_yes=True)
    run_id = agent.tracer.start("cli context")
    agent.tracer.event("prompt", {"message_count": 1})
    agent.tracer.end("ok")
    agent.observability.record("policy.denied", tags={"tool": "shell", "risk": "critical"})
    for line in ["/help", "/tools", "/skills", "/memory", "/memory stats", "/memory recent 2", "/memory search cli", "/context", "/todo", "/todo add task", "/todo done 1", "/agents", "/trace list", f"/trace context {run_id}", "/metrics", "/metrics alerts", "/metrics prometheus", "/sandbox", "/sandbox smoke", "/model", "/model cli-test-model", "/policy", "/mcp", "/mcp add cli-demo python3 server.py --flag", "/mcp remove cli-demo", "/mcp tools", "/evolve feedback", "/evolve status", "/evolve audit", "/evolve trace", "/evolve apply-trace", "/evolve eval", "/dream", "/dream status", "/dream backlog", "/dream verify", "/dream apply --limit 2 --min-confidence 0.8", "/loop list", "/loop show dream-loop", "/workflow", "/run sandbox_info {}", "/unknown"]:
        assert handle_command(agent, line) is True
    assert handle_command(agent, "/exit") is False
    output = capsys.readouterr().out
    assert "Commands:" in output and "Sandbox root" in output and "Evolution audit" in output and "Dream report" in output and "Dream status" in output and "Evolution status" in output and "evolva_policy_denied_total" in output and "Unknown command" in output

    assert metrics_cmd(Namespace(metrics_cmd="list", limit=5)) == 0
    assert "policy.denied" in capsys.readouterr().out
    assert metrics_cmd(Namespace(metrics_cmd="alerts", limit=5)) == 0
    assert "policy-denied-any" in capsys.readouterr().out
    assert metrics_cmd(Namespace(metrics_cmd="prometheus")) == 0
    assert "evolva_policy_denied_total" in capsys.readouterr().out
    assert sandbox_cmd(Namespace(sandbox_cmd="info")) == 0
    assert "Sandbox root" in capsys.readouterr().out
    assert sandbox_cmd(Namespace(sandbox_cmd="smoke", timeout=5)) == 0
    assert "Sandbox smoke ok" in capsys.readouterr().out


def test_cli_mcp_cmd_json_error_and_success(monkeypatch, capsys, temp_config):
    monkeypatch.setattr("evolva.cli.AgentConfig", lambda: temp_config)
    assert mcp_cmd(Namespace(mcp_cmd="presets", yes=True)) == 0
    assert "playwright" in capsys.readouterr().out
    assert mcp_cmd(Namespace(mcp_cmd="add-preset", preset="playwright", name="browser", env=[], yes=True)) == 0
    assert "Added MCP preset" in capsys.readouterr().out
    assert mcp_cmd(Namespace(mcp_cmd="servers", yes=True)) == 0
    assert "browser" in capsys.readouterr().out
    assert mcp_cmd(Namespace(mcp_cmd="add", name="fs", command="python3", args=["server.py"], env=["A=B"], yes=True)) == 0
    assert "Added MCP server" in capsys.readouterr().out
    assert mcp_cmd(Namespace(mcp_cmd="remove", name="fs", yes=True)) == 0
    assert "Removed MCP server" in capsys.readouterr().out
    assert mcp_cmd(Namespace(mcp_cmd="call", server="s", tool="t", arguments="{", yes=True)) == 2
    assert mcp_cmd(Namespace(mcp_cmd="health", server="", refresh=False, yes=True)) == 0
    assert "JSON error" in capsys.readouterr().out


def test_mcp_manager_add_remove_persists_config(tmp_path):
    cfg = tmp_path / "mcp" / "servers.json"
    manager = MCPManager(cfg, root=tmp_path)
    added = manager.add_server(
        "filesystem",
        "npx",
        ["-y", "@modelcontextprotocol/server-filesystem", "."],
        request_timeout=7,
        max_message_bytes=12345,
    )

    assert added.name == "filesystem"
    assert added.request_timeout == 7
    assert added.max_message_bytes == 12345
    assert manager.list_servers() == ["filesystem"]
    data = json.loads(cfg.read_text())
    assert data["servers"]["filesystem"]["command"] == "npx"
    assert data["servers"]["filesystem"]["args"][-1] == "."
    assert data["servers"]["filesystem"]["request_timeout"] == 7
    assert data["servers"]["filesystem"]["max_message_bytes"] == 12345
    reloaded = MCPManager(cfg, root=tmp_path)
    assert reloaded.servers["filesystem"].request_timeout == 7
    assert reloaded.servers["filesystem"].max_message_bytes == 12345

    assert manager.remove_server("filesystem") is True
    assert manager.list_servers() == []
    assert json.loads(cfg.read_text())["servers"] == {}
    assert manager.remove_server("filesystem") is False


def test_mcp_presets_and_env_parser():
    presets = list_mcp_presets()
    assert {item["name"] for item in presets} >= {"playwright", "brave-search", "fetch"}
    playwright = get_mcp_preset("playwright").to_server_config(name="browser")
    assert playwright["name"] == "browser"
    assert playwright["command"] == "npx"
    assert "playwright" in " ".join(playwright["args"])
    assert parse_env_pairs(["BRAVE_API_KEY=secret"]) == {"BRAVE_API_KEY": "secret"}
    with pytest.raises(ValueError):
        parse_env_pairs(["BROKEN"])


def test_cli_evolve_cmd_status_trace_eval_and_feedback(monkeypatch, capsys, temp_config, tmp_path):
    monkeypatch.setattr("evolva.cli.AgentConfig", lambda: temp_config)
    assert evolve_cmd(Namespace(evolve_cmd="status")) == 0
    assert "Evolution status" in capsys.readouterr().out
    assert evolve_cmd(Namespace(evolve_cmd="audit", limit=5, report=None, show_proposals=True)) == 0
    assert "Evolution audit" in capsys.readouterr().out
    assert evolve_cmd(Namespace(evolve_cmd="trace", limit=5, apply=False)) == 0
    assert "Evolution analysis: trace" in capsys.readouterr().out
    assert evolve_cmd(Namespace(evolve_cmd="feedback", feedback="Prefer concise verification")) == 0
    assert "Applied evolution reports" in capsys.readouterr().out

    report = tmp_path / "eval.json"
    report.write_text(json.dumps({"results": [{"id": "bad", "passed": False, "checks": {"contains:x": False}, "answer": "y", "tool_logs": []}]}))
    assert evolve_cmd(Namespace(evolve_cmd="eval", report=report, apply=True)) == 0
    output = capsys.readouterr().out
    assert "Evolution analysis: eval" in output and "Applied evolution reports" in output


def test_cli_optimize_cmd(monkeypatch, capsys, temp_config):
    monkeypatch.setattr("evolva.cli.AgentConfig", lambda: temp_config)
    assert optimize_cmd(Namespace(apply=False, fail_on_items=False)) == 0
    assert "Daily optimization report" in capsys.readouterr().out


def test_cli_dream_cmd_integration(monkeypatch, capsys, temp_config):
    monkeypatch.setattr("evolva.cli.AgentConfig", lambda: temp_config)
    assert dream_cmd(Namespace(dream_cmd=None, apply=False, limit=5, report=None, min_confidence=None, json=False)) == 0
    assert "Dream report" in capsys.readouterr().out


def test_cli_loop_cmd_integration(monkeypatch, capsys, temp_config):
    monkeypatch.setattr("evolva.cli.AgentConfig", lambda: temp_config)
    assert loop_cmd(Namespace(loop_cmd="list", yes=True)) == 0
    assert "dream-loop" in capsys.readouterr().out


def test_tui_non_curses_command_completion_queue_and_confirmation(monkeypatch, temp_config):
    monkeypatch.setattr("evolva.tui.AgentConfig", lambda: temp_config)
    app = EvolvaTUI(assume_yes=True, show_tools=True)
    app.messages.clear()
    app.input_text = "/he"
    app._complete_command()
    assert app.input_text == "/help"
    app._handle_command("/help")
    assert any("TUI keys" in m.text for m in app.messages)
    app._handle_command("/todo add tui task")
    assert any("Added todo" in m.text for m in app.messages)
    app.agent.memory.add("fact", "TUI memory detail")
    app._handle_command("/memory stats")
    assert any("Memory stats" in m.text for m in app.messages)
    app._handle_command("/memory recent 1")
    assert any("TUI memory detail" in m.text for m in app.messages)
    app._handle_command("/evolve status")
    assert any("Evolution status" in m.text for m in app.messages)
    app._handle_command("/evolve audit")
    assert any("Evolution audit" in m.text for m in app.messages)
    app._handle_command("/evolve trace")
    assert any("Evolution analysis: trace" in m.text for m in app.messages)
    app._handle_command("/dream")
    assert any("Dream report" in m.text for m in app.messages)
    app._handle_command("/dream status")
    assert any("Dream status" in m.text for m in app.messages)
    app._handle_command("/dream backlog")
    assert any("Dream backlog" in m.text for m in app.messages)
    app._handle_command("/dream verify")
    assert any("Dream verification" in m.text for m in app.messages)
    app._handle_command("/loop list")
    assert any("dream-loop" in m.text for m in app.messages)
    app._handle_command("/model")
    assert any("Current model" in m.text for m in app.messages)
    app._handle_command("/config")
    assert any("Provider configuration" in m.text for m in app.messages)
    app._handle_command("/config set model tui-config-model")
    assert app.agent.config.model == "tui-config-model"
    app._handle_command("/config set base_url https://llm.example/v1")
    assert app.agent.config.base_url == "https://llm.example/v1"
    app._handle_command("/config set temperature 1")
    assert app.agent.config.temperature == 1.0
    app._handle_command("/config set api_key sk-local-test")
    assert app.agent.config.api_key == "sk-local-test"
    assert "sk-local-test" not in app.messages[-1].text
    assert temp_config.runtime_config_file.exists()
    app._submit("/config set api_key sk-hidden-history")
    assert "sk-hidden-history" not in app.messages[-2].text
    assert app.messages[-2].text == "/config set api_key <hidden>"
    app._handle_command("/config wizard")
    assert app.config_wizard is not None
    app.input_text = "wizard-model"
    app._handle_key("\n")
    app.input_text = "https://wizard.example/v1"
    app._handle_key("\n")
    app.input_text = "0.9"
    app._handle_key("\n")
    app.input_text = "sk-wizard-test"
    app._handle_key("\n")
    assert app.config_wizard is None
    assert app.agent.config.model == "wizard-model"
    assert app.agent.config.base_url == "https://wizard.example/v1"
    assert app.agent.config.temperature == 0.9
    assert app.agent.config.api_key == "sk-wizard-test"
    assert "sk-wizard-test" not in app.messages[-1].text
    app._handle_command("/model tui-test-model")
    assert app.agent.config.model == "tui-test-model"
    app._handle_command("/mcp add tui-demo python3 server.py")
    assert "tui-demo" in app.agent.mcp.list_servers()
    assert any("Added MCP server" in m.text for m in app.messages)
    app._handle_command("/mcp remove tui-demo")
    assert "tui-demo" not in app.agent.mcp.list_servers()
    assert any("Removed MCP server" in m.text for m in app.messages)
    workflow_path = temp_config.root / "evolva" / "workflows" / "tui-demo.json"
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text(
        json.dumps(
            {
                "id": "tui-demo",
                "nodes": [
                    {"id": "sandbox", "type": "tool", "tool": "sandbox_info", "args": {}},
                ],
            }
        ),
        encoding="utf-8",
    )
    app._handle_command(f"/workflow {workflow_path.relative_to(temp_config.root)}")
    for _ in range(100):
        app._drain_queue()
        if "Workflow tui-demo: ok" in app.messages[-1].text:
            break
        time.sleep(0.01)
    app._drain_queue()
    assert "Workflow tui-demo: ok" in app.messages[-1].text
    app.input_text = "/mo"
    app._complete_command()
    assert app.input_text == "/model "
    run_id = app.agent.tracer.start("tui context")
    app.agent.tracer.event("prompt", {"message_count": 1})
    app.agent.tracer.end("ok")
    app._handle_command("/trace context latest")
    assert any("Trace context" in m.text for m in app.messages)
    app._handle_command(f"/trace context {run_id}")
    assert any("message_count" in m.text for m in app.messages)
    app._handle_key(18)
    assert any(run_id in m.text for m in app.messages)
    app._handle_key(24)
    assert any("Trace context" in m.text for m in app.messages)
    app.input_text = ""
    app._handle_key("你")
    app._handle_key("好")
    assert app.input_text == "你好"
    app.queue.put(("tool_result", ("sandbox_info", True, "ok")))
    app.queue.put(("system", "system msg"))
    app.queue.put(("error", "bad"))
    app._drain_queue()
    assert "TOOL sandbox_info" in app.tool_logs[-1]
    assert app.status == "Error"

    app2 = EvolvaTUI(assume_yes=False, show_tools=True)
    result = {}
    thread = threading.Thread(target=lambda: result.setdefault("answer", TUIConfirmation(app2).ask("shell", {"command": "printf hi"})))
    thread.start()
    for _ in range(100):
        if app2.confirmation_event is not None:
            break
    assert app2.confirmation_event is not None
    app2._handle_key(ord("y"))
    thread.join(timeout=1)
    assert result["answer"] is True


def test_tui_status_bar_avoids_duplicate_ready(monkeypatch, temp_config):
    monkeypatch.setattr("evolva.tui.AgentConfig", lambda: temp_config)
    app = EvolvaTUI(assume_yes=True, show_tools=True)
    writes = []

    class FakeScreen:
        def addnstr(self, y, x, text, width, attr=None):
            writes.append(str(text))

    app.stdscr = FakeScreen()
    app._draw_status(0, 80)
    status = " ".join(writes).strip()
    assert "READY" in status
    assert "Ready  Ready" not in status
    assert "rule-mode" in status and "tools:on" in status


def test_tui_draws_polished_shell(monkeypatch, temp_config):
    monkeypatch.setattr("evolva.tui.AgentConfig", lambda: temp_config)
    app = EvolvaTUI(assume_yes=True, show_tools=True)
    writes = []

    class FakeScreen:
        def addnstr(self, y, x, text, width, attr=None):
            writes.append(str(text))

        def addch(self, y, x, ch, attr=None):
            writes.append(str(ch))

        def move(self, y, x):
            pass

    app.stdscr = FakeScreen()
    app._draw_title(0, 100)
    app._draw_chat(7, 0, 16, 92)
    app._draw_tools(7, 70, 16, 30)
    app._draw_input(20, 100)
    rendered = "\n".join(writes)
    assert "E V O L A  Agent Workbench" in rendered
    assert "local_rule-mode" in rendered
    assert app._path_label(78) in rendered
    assert "╭───────●" in rendered
    assert "Evolva is a local-first Agent Harness." in rendered
    assert "Trace / Tool Stream" in rendered
    assert "No tool calls yet." in rendered
    assert "What's on your mind?" in rendered
    assert "You ›" in rendered



def test_inline_tui_renders_workbench_panels(monkeypatch, capsys, temp_config):
    monkeypatch.setattr("evolva.tui.AgentConfig", lambda: temp_config)
    app = EvolvaInlineTUI(assume_yes=True)
    app._print_header()
    print(app._agent("done"))
    print(app._tool("TOOL repo_index.build -> ok=True"))
    out = capsys.readouterr().out
    assert "Evolva TUI Workbench" in out
    assert "E V O L A  Agent Workbench" in out
    assert "Trace · Eval · Dream · Loop" in out
    assert "╭─ Evolva" in out
    assert "Trace / Tool Stream" in out


def test_run_tui_delegates_to_textual_workbench(monkeypatch):
    called = {}

    def fake_textual(assume_yes=False, show_tools=True, config=None):
        called["args"] = (assume_yes, show_tools, config)
        return 17

    monkeypatch.setattr(tui_module, "run_textual_tui", fake_textual)
    assert tui_module.run_tui(assume_yes=True, show_tools=False) == 17
    assert called["args"] == (True, False, None)


def test_textual_tui_falls_back_to_inline_when_missing(monkeypatch, capsys):
    called = {}

    class FakeInlineTUI:
        def __init__(self, assume_yes=False, show_tools=True, config=None):
            called["init"] = (assume_yes, show_tools, config)

        def run(self):
            called["run"] = True
            return 23

    monkeypatch.setattr(tui_module, "TEXTUAL_AVAILABLE", False)
    monkeypatch.setattr(tui_module, "EvolvaInlineTUI", FakeInlineTUI)
    assert tui_module.run_textual_tui(assume_yes=True, show_tools=False) == 23
    assert called == {"init": (True, False, None), "run": True}
    assert "falling back to the inline TUI" in capsys.readouterr().out


def test_textual_placeholder_raises_when_dependency_missing():
    if tui_module.TEXTUAL_AVAILABLE:
        pytest.skip("Textual is installed; placeholder is not active")
    with pytest.raises(RuntimeError, match="Textual is not installed"):
        tui_module.EvolvaTextualApp()


@pytest.mark.skipif(not tui_module.TEXTUAL_AVAILABLE, reason="Textual is not installed")
def test_textual_input_accepts_chinese_key_events():
    app = tui_module.EvolvaInput()

    class FakeEvent:
        key = "你"
        character = "你"

        def __init__(self):
            self.stopped = False
            self.prevented = False

        def stop(self):
            self.stopped = True

        def prevent_default(self):
            self.prevented = True

    event = FakeEvent()
    rendered = []
    app.has_focus = True
    app.update = lambda content, layout=False: rendered.append(content)
    import asyncio

    asyncio.run(app._on_key(event))
    assert app.value == "你"
    assert "你" in rendered[-1]
    assert event.stopped and event.prevented


@pytest.mark.skipif(not tui_module.TEXTUAL_AVAILABLE, reason="Textual is not installed")
def test_textual_tui_shows_reasoning_indicator(monkeypatch, temp_config):
    monkeypatch.setattr("evolva.tui.AgentConfig", lambda: temp_config)

    async def run_case():
        app = tui_module.EvolvaTextualApp(assume_yes=True, show_tools=True)
        async with app.run_test(size=(110, 32)):
            app.runtime.busy = True
            app.runtime.status = "thinking"
            app._refresh_status()
            thinking = app.query_one("#thinking", tui_module.Static)
            first = getattr(thinking, "_Static__content", "")
            assert "Orbiting" in first
            assert "thinking" in first
            assert "hidden" not in thinking.classes
            assert app._spinner_tick == 1

            app._refresh_status()
            second = getattr(thinking, "_Static__content", "")
            assert second != first
            assert "Orbiting" in second
            assert app._spinner_tick == 2

            app._thinking_started_at -= 3
            app._refresh_status()
            elapsed = getattr(thinking, "_Static__content", "")
            assert any(frame in elapsed for frame in app.THINKING_FRAMES)
            assert "(3s · thinking)" in elapsed

            app.runtime.busy = False
            app.runtime.status = "Ready"
            app._refresh_status()
            assert getattr(thinking, "_Static__content", "") == ""
            assert "hidden" in thinking.classes
            assert app._spinner_tick == 0
            assert app._thinking_started_at is None

    import asyncio

    asyncio.run(run_case())


@pytest.mark.skipif(not tui_module.TEXTUAL_AVAILABLE, reason="Textual is not installed")
def test_textual_reasoning_indicator_includes_operation_status(monkeypatch, temp_config):
    monkeypatch.setattr("evolva.tui.AgentConfig", lambda: temp_config)

    async def run_case():
        app = tui_module.EvolvaTextualApp(assume_yes=True, show_tools=True)
        async with app.run_test(size=(110, 32)):
            app.runtime.busy = True
            app.runtime.status = "Running tool..."
            app._refresh_status()
            thinking = app.query_one("#thinking", tui_module.Static)
            content = getattr(thinking, "_Static__content", "")
            status = getattr(app.query_one("#status", tui_module.Static), "_Static__content", "")
            assert "Orbiting" in content
            assert "Running tool..." in content
            assert "Running tool..." in status

    import asyncio

    asyncio.run(run_case())

def test_inline_tui_ctrl_c_requires_second_interrupt(monkeypatch, capsys, temp_config):
    monkeypatch.setattr("evolva.tui.AgentConfig", lambda: temp_config)
    events = iter([KeyboardInterrupt, "/exit"])

    def fake_input(prompt):
        event = next(events)
        if event is KeyboardInterrupt:
            raise KeyboardInterrupt
        return event

    monkeypatch.setattr("builtins.input", fake_input)
    app = EvolvaInlineTUI(assume_yes=True)
    assert app.run() == 0
    assert "Press Ctrl+C again to exit" in capsys.readouterr().out


def test_inline_tui_second_ctrl_c_exits(monkeypatch, capsys, temp_config):
    monkeypatch.setattr("evolva.tui.AgentConfig", lambda: temp_config)

    def fake_input(prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", fake_input)
    app = EvolvaInlineTUI(assume_yes=True)
    app._interrupt_armed = True
    assert app.run() == 0
    assert "Evolva session closed" in capsys.readouterr().out
