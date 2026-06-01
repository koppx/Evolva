from __future__ import annotations

import json
import threading
from argparse import Namespace
from dataclasses import replace

import pytest

from evolva.agent.core import EvolvaAgent, SYSTEM_PROMPT
from evolva.agent.mcp import MCPClient, MCPManager, MCPServerConfig, render_mcp_result
from evolva.agent.multi_agent import MultiAgentCoordinator
from evolva.agent.tracing import TraceRecorder
from evolva.cli import build_parser, evolve_cmd, handle_command, main, mcp_cmd, once, optimize_cmd
from evolva.eval.harness import EvalHarness, EvalResult, render_results
from evolva.tui import EvolvaTUI, TUIConfirmation
from evolva.workflow.engine import WorkflowEngine


def test_agent_fallback_remember_read_list_and_image(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    assert "Evolva" in SYSTEM_PROMPT
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


def test_agent_auto_evolve_records_report_in_trace_and_context(temp_config):
    agent = EvolvaAgent(replace(temp_config, max_steps=1), assume_yes=True)
    agent.llm = type(
        "FakeLLM",
        (),
        {"available": True, "chat": lambda self, messages: type("Resp", (), {"content": json.dumps({"tool": {"name": "missing", "args": {}}, "final": None})})()},
    )()
    result = agent.chat("run missing tool")

    assert result.failed_tools == ["missing"]
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


def test_trace_recorder_list_load_render_disabled_and_path_sanitization(tmp_path):
    traces = TraceRecorder(tmp_path / "traces")
    run_id = traces.start("hello", meta={"a": 1})
    traces.event("tool_call", {"tool": "noop"})
    path = traces.end("done")
    assert path and path.exists()
    assert traces.list_runs(limit=1)[0]["run_id"] == run_id
    assert traces.load(run_id)["final_answer"] == "done"
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


def test_eval_harness_score_summary_report_and_run_file(temp_config, tmp_path):
    harness = EvalHarness(temp_config, assume_yes=True)
    harness.agent.memory.add("fact", "Eval remembers memory state")
    harness.agent.context.add("decision", "Eval checks context state")
    checks = harness.score(
        {
            "expected_contains": ["ok"],
            "forbidden_contains": ["bad"],
            "expected_regex": ["^ok$"],
            "expected_artifacts": ["evolva/workspace/out.txt", "../escape.txt"],
            "expected_memory": ["memory state"],
            "expected_context": ["context state"],
            "max_duration_ms": 500,
            "scorers": ["no_tool_error"],
        },
        "ok",
        [],
        duration_ms=10,
    )
    assert checks["contains:ok"]
    assert checks["not_contains:bad"]
    assert checks["regex:^ok$"]
    assert not checks["artifact_exists:evolva/workspace/out.txt"]
    assert not checks["artifact_inside_root:../escape.txt"]
    assert checks["memory:memory state"]
    assert checks["context:context state"]
    assert checks["duration<=500ms"]
    assert checks["no_tool_error"]

    results = [EvalResult("a", True, 1.0, {}, "ok"), EvalResult("b", False, 0.0, {}, "bad")]
    assert harness.summary(results) == {"total": 2, "passed": 1, "failed": 1, "avg_score": 0.5}
    report = harness.write_report(results, "unit")
    assert report.exists()
    assert "PASS a" in render_results(results)

    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text('\n# comment\n{"id":"fallback","input":"remember eval","expected_contains":["已记住"],"scorers":["no_tool_error"]}\n')
    run_results = harness.run_file(tasks)
    assert len(run_results) == 1 and run_results[0].passed


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


def test_cli_parser_main_once_and_handle_commands(monkeypatch, capsys, temp_config):
    parser = build_parser()
    assert parser.prog == "evolva"
    assert parser.parse_args(["ask", "hi", "--image", "a.png", "--yes"]).image == ["a.png"]
    assert parser.parse_args(["mcp", "call", "s", "t", "{}", "--yes"]).mcp_cmd == "call"
    assert parser.parse_args(["evolve", "trace", "--apply"]).evolve_cmd == "trace"
    assert parser.parse_args(["optimize", "--apply"]).apply

    monkeypatch.setattr("evolva.cli.AgentConfig", lambda: temp_config)
    assert once(Namespace(message="remember cli", image=None, yes=True, show_tools=False)) == 0
    assert "已记住" in capsys.readouterr().out
    assert main(["ask", "remember main", "--yes"]) == 0
    assert "已记住" in capsys.readouterr().out

    agent = EvolvaAgent(temp_config, assume_yes=True)
    for line in ["/help", "/tools", "/skills", "/memory", "/memory stats", "/memory recent 2", "/memory search cli", "/context", "/todo", "/todo add task", "/todo done 1", "/agents", "/trace list", "/policy", "/mcp", "/mcp tools", "/evolve feedback", "/evolve status", "/evolve trace", "/evolve apply-trace", "/evolve eval", "/workflow", "/run sandbox_info {}", "/unknown"]:
        assert handle_command(agent, line) is True
    assert handle_command(agent, "/exit") is False
    output = capsys.readouterr().out
    assert "Commands:" in output and "Sandbox root" in output and "Evolution status" in output and "Unknown command" in output


def test_cli_mcp_cmd_json_error_and_success(monkeypatch, capsys, temp_config):
    monkeypatch.setattr("evolva.cli.AgentConfig", lambda: temp_config)
    assert mcp_cmd(Namespace(mcp_cmd="servers", yes=True)) == 0
    assert "No MCP servers" in capsys.readouterr().out
    assert mcp_cmd(Namespace(mcp_cmd="call", server="s", tool="t", arguments="{", yes=True)) == 2
    assert "JSON error" in capsys.readouterr().out


def test_cli_evolve_cmd_status_trace_eval_and_feedback(monkeypatch, capsys, temp_config, tmp_path):
    monkeypatch.setattr("evolva.cli.AgentConfig", lambda: temp_config)
    assert evolve_cmd(Namespace(evolve_cmd="status")) == 0
    assert "Evolution status" in capsys.readouterr().out
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


def test_tui_non_curses_command_completion_queue_and_confirmation(monkeypatch, temp_config):
    monkeypatch.setattr("evolva.tui.AgentConfig", lambda: temp_config)
    app = EvolvaTUI(assume_yes=True, show_tools=True)
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
    app._handle_command("/evolve trace")
    assert any("Evolution analysis: trace" in m.text for m in app.messages)
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
