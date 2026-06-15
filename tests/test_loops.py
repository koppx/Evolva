from __future__ import annotations

import json
from argparse import Namespace

from evolva.agent.core import EvolvaAgent
from evolva.agent.llm import LLMResponse
from evolva.cli import build_parser, handle_command, loop_cmd
from evolva.loops import LoopDraftSession, LoopRegistry, LoopRunner, LoopSpec, render_loop_draft, render_loop_result, render_loop_specs, render_loop_validation, validate_loop_spec
from evolva.loops.planner import LoopPlanner
from evolva.tui import EvolvaTUI


class FakeLoopPlannerLLM:
    available = True

    def __init__(self, payload: dict | str):
        self.payload = payload
        self.calls = []

    def chat(self, messages, *, temperature=None):
        self.calls.append({"messages": messages, "temperature": temperature})
        content = self.payload if isinstance(self.payload, str) else json.dumps(self.payload, ensure_ascii=False)
        return LLMResponse(content=content)


def llm_loop_payload() -> dict:
    return {
        "intent_type": "web_feature",
        "goal": "交付一个响应式 landing page，包含 hero、pricing、FAQ 和移动端验收",
        "complexity": "medium",
        "assumptions": ["先生成计划，不直接执行", "需要浏览器或人工确认视觉效果"],
        "open_questions": [],
        "phases": [
            {"id": "context_scan", "title": "上下文扫描", "purpose": "识别前端框架和入口文件", "type": "agent", "depends_on": [], "expected_output": "框架、入口和命令"},
            {"id": "product_design", "title": "产品设计", "purpose": "定义页面结构、文案层级和移动端行为", "type": "agent", "depends_on": ["context_scan"], "expected_output": "页面结构和验收标准"},
            {"id": "implementation", "title": "实施", "purpose": "实现页面并保持现有风格", "type": "agent", "depends_on": ["product_design"], "expected_output": "代码改动"},
            {"id": "verification", "title": "自动验证", "purpose": "运行构建和测试", "type": "tool", "depends_on": ["implementation"], "expected_output": "命令结果"},
            {"id": "visual_acceptance", "title": "视觉验收", "purpose": "检查 hero、pricing、FAQ 和移动端", "type": "agent", "depends_on": ["verification"], "expected_output": "视觉验收说明"},
            {"id": "final_report", "title": "最终报告", "purpose": "汇总改动、验证和风险", "type": "agent", "depends_on": ["visual_acceptance"], "expected_output": "Loop report"},
        ],
        "checkpoints": [
            {"id": "design_review", "after_phase": "product_design", "type": "manual_confirmation", "description": "用户确认页面结构和验收口径", "required": True},
            {"id": "build_check", "after_phase": "verification", "type": "command_success", "description": "构建成功", "required": True, "command": "npm run build"},
            {"id": "mobile_visual", "after_phase": "visual_acceptance", "type": "manual_confirmation", "description": "移动端视觉确认", "required": True},
        ],
        "command_candidates": ["npm run build", "rm -rf .", "git push origin main"],
        "risks": ["视觉质量需要人工确认"],
        "execution_limits": {"max_total_phases": 10, "max_duration_seconds": 1800, "max_tool_calls": 35, "max_command_runs": 8, "max_file_changes": 25},
    }


def test_loop_spec_validation_and_registry(temp_config):
    registry = LoopRegistry(temp_config.loops_dir)
    specs = registry.list_specs()
    assert {spec.id for spec in specs} >= {"dream-loop", "repo-improvement-loop", "eval-regression-loop"}
    assert "dream-loop" in render_loop_specs(specs)

    custom = temp_config.loops_dir / "custom.json"
    custom.write_text(json.dumps({"id": "custom", "phases": [{"id": "a", "type": "tool", "tool": "sandbox_info"}]}), encoding="utf-8")
    spec = registry.load("custom")
    assert spec.id == "custom"
    assert spec.validate_order() == ["a"]

    bad = LoopSpec.from_dict({"id": "bad", "phases": [{"id": "a", "depends_on": []}, {"id": "b", "depends_on": ["a"]}]})
    assert bad.validate_order() == ["a", "b"]


def test_loop_runner_runs_tool_and_dream_phases(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    spec = LoopSpec.from_dict(
        {
            "id": "unit-loop",
            "phases": [
                {"id": "info", "type": "tool", "tool": "sandbox_info", "args": {}},
                {"id": "dream", "type": "dream", "action": "backlog", "depends_on": ["info"]},
            ],
            "gates": [{"after": "info", "type": "phase_success"}],
            "artifacts": ["trace", "dream_candidate"],
        }
    )
    result = LoopRunner(agent).run(spec)
    rendered = render_loop_result(result)
    assert result.ok
    assert result.outputs["info"].startswith("Sandbox root")
    assert "Dream backlog" in result.outputs["dream"]
    assert "phase_success:ok" in rendered
    assert temp_config.loop_runs_dir.joinpath(result.run_id + ".json").exists()
    assert "unit-loop" in agent.context.render("unit-loop")


def test_loop_runner_stops_on_gate_failure(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    spec = LoopSpec.from_dict(
        {
            "id": "gate-loop",
            "phases": [{"id": "info", "type": "tool", "tool": "sandbox_info"}],
            "gates": [{"after": "info", "type": "output_contains", "expected_contains": "definitely-missing"}],
        }
    )
    result = LoopRunner(agent).run(spec)
    assert not result.ok
    assert result.status == "failed"
    assert not result.phase_results[0].gate_results[0]["ok"]


def test_loop_runner_creates_trace_for_standalone_loop(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    spec = LoopSpec.from_dict(
        {
            "id": "trace-loop",
            "phases": [{"id": "info", "type": "tool", "tool": "sandbox_info"}],
        }
    )
    result = LoopRunner(agent).run(spec)
    assert result.ok
    assert result.trace_run_id.startswith("run_")
    trace_path = temp_config.traces_dir / f"{result.trace_run_id}.json"
    assert trace_path.exists()
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["status"] == "completed"
    assert any(event["kind"] == "loop_start" for event in trace["events"])
    assert any(event["kind"] == "loop_end" for event in trace["events"])


def test_loop_runner_command_gate_executes_command(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    spec = LoopSpec.from_dict(
        {
            "id": "command-gate-loop",
            "phases": [{"id": "info", "type": "tool", "tool": "sandbox_info"}],
            "command_allowlist": ["python3"],
            "gates": [{"after": "info", "type": "command_success", "command": "python3 -c 'print(123)'", "timeout": 5}],
        }
    )
    result = LoopRunner(agent).run(spec)
    assert result.ok
    gate = result.phase_results[0].gate_results[0]
    assert gate["ok"]
    assert gate["command"] == "python3 -c 'print(123)'"
    assert "123" in gate["output"]


def test_loop_runner_retries_failed_phase_and_records_attempts(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    spec = LoopSpec.from_dict(
        {
            "id": "retry-loop",
            "command_allowlist": ["python3"],
            "phases": [{"id": "fail", "type": "tool", "tool": "shell", "args": {"command": "python3 -c 'raise SystemExit(2)'"}, "retries": 1, "timeout": 5}],
        }
    )
    result = LoopRunner(agent).run(spec)
    assert not result.ok
    phase = result.phase_results[0]
    assert phase.attempts == 2
    assert len(phase.attempt_results) == 2


def test_loop_validation_renderer_and_cli(monkeypatch, capsys, temp_config):
    spec = LoopSpec.from_dict(
        {
            "id": "validate-loop",
            "phases": [{"id": "info", "type": "tool", "tool": "sandbox_info", "timeout": 5}],
            "command_allowlist": ["python3"],
            "gates": [{"after": "info", "type": "command_success", "command": "python3 -c 'print(1)'"}],
        }
    )
    assert "Status: ok" in render_loop_validation(spec)

    monkeypatch.setattr("evolva.cli.AgentConfig", lambda: temp_config)
    custom = temp_config.loops_dir / "validate-loop.json"
    custom.parent.mkdir(parents=True, exist_ok=True)
    custom.write_text(json.dumps(spec.to_dict()), encoding="utf-8")
    assert loop_cmd(Namespace(loop_cmd="validate", loop_id="validate-loop", yes=True)) == 0
    assert "Loop validation: validate-loop" in capsys.readouterr().out


def test_loop_validation_requires_command_allowlist_and_known_tools(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    missing_allowlist = LoopSpec.from_dict(
        {
            "id": "missing-allowlist",
            "phases": [{"id": "test", "type": "tool", "tool": "shell", "args": {"command": "python3 -c 'print(1)'"}}],
        }
    )
    validation = validate_loop_spec(missing_allowlist, agent=agent, strict_policy=True)
    assert not validation.ok
    assert any("allowlist" in error for error in validation.errors)

    unknown_tool = LoopSpec.from_dict({"id": "unknown-tool", "phases": [{"id": "x", "type": "tool", "tool": "missing_tool"}]})
    validation = validate_loop_spec(unknown_tool, agent=agent, strict_policy=True)
    assert not validation.ok
    assert any("unknown tool" in error for error in validation.errors)

    denied = LoopSpec.from_dict(
        {
            "id": "denied-command",
            "command_allowlist": ["git"],
            "phases": [{"id": "x", "type": "tool", "tool": "shell", "args": {"command": "git reset --hard"}}],
        }
    )
    validation = validate_loop_spec(denied, agent=agent, strict_policy=True)
    assert not validation.ok
    assert any("policy denied" in error for error in validation.errors)


def test_loop_runner_refuses_unallowlisted_shell_before_execution(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    spec = LoopSpec.from_dict(
        {
            "id": "blocked-loop",
            "phases": [{"id": "x", "type": "tool", "tool": "shell", "args": {"command": "python3 -c 'print(1)'"}}],
        }
    )
    result = LoopRunner(agent).run(spec)
    assert not result.ok
    assert result.status == "validation_failed"
    assert "allowlist" in result.phase_results[0].output


def test_loop_runner_resume_reuses_successful_outputs(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    first = LoopSpec.from_dict(
        {
            "id": "resume-loop",
            "command_allowlist": ["python3"],
            "phases": [
                {"id": "first", "type": "tool", "tool": "sandbox_info"},
                {"id": "second", "type": "tool", "tool": "shell", "args": {"command": "python3 -c 'raise SystemExit(2)'"}, "depends_on": ["first"]},
            ],
        }
    )
    first_result = LoopRunner(agent).run(first)
    assert not first_result.ok
    assert "first" in first_result.outputs

    second = LoopSpec.from_dict(
        {
            "id": "resume-loop",
            "command_allowlist": ["python3"],
            "phases": [
                {"id": "first", "type": "tool", "tool": "sandbox_info"},
                {"id": "second", "type": "tool", "tool": "shell", "args": {"command": "python3 -c 'print(2)'"}, "depends_on": ["first"]},
            ],
        }
    )
    resumed = LoopRunner(agent).run(second, resume=True)
    assert resumed.ok
    assert resumed.phase_results[0].attempts == 0
    assert resumed.phase_results[0].attempt_results[0]["resumed"]
    assert "2" in resumed.outputs["second"]


def test_loop_resume_skips_changed_phase_outputs(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    first = LoopSpec.from_dict(
        {
            "id": "resume-changed-loop",
            "command_allowlist": ["python3"],
            "phases": [
                {"id": "first", "type": "tool", "tool": "shell", "args": {"command": "python3 -c 'print(1)'"}},
                {"id": "second", "type": "tool", "tool": "shell", "args": {"command": "python3 -c 'raise SystemExit(2)'"}, "depends_on": ["first"]},
            ],
        }
    )
    assert not LoopRunner(agent).run(first).ok

    second = LoopSpec.from_dict(
        {
            "id": "resume-changed-loop",
            "command_allowlist": ["python3"],
            "phases": [
                {"id": "first", "type": "tool", "tool": "shell", "args": {"command": "python3 -c 'print(3)'"}},
                {"id": "second", "type": "tool", "tool": "shell", "args": {"command": "python3 -c 'print(4)'"}, "depends_on": ["first"]},
            ],
        }
    )
    resumed = LoopRunner(agent).run(second, resume=True)
    assert resumed.ok
    assert resumed.phase_results[0].attempts == 1
    assert "3" in resumed.outputs["first"]
    assert "4" in resumed.outputs["second"]


def test_loop_validation_rejects_structural_errors(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    runner = LoopRunner(agent)

    bad_path = temp_config.loops_dir / "bad-loop.json"
    bad_path.write_text(
        json.dumps(
            {
                "id": "bad-loop",
                "phases": [{"id": "bad", "type": "tool", "tool": "sandbox_info", "retries": -1}],
            }
        ),
        encoding="utf-8",
    )
    spec = runner.load("bad-loop")
    try:
        render_loop_validation(spec)
    except ValueError as exc:
        assert "retries must be >= 0" in str(exc)
    else:
        raise AssertionError("negative retries should fail validation")

    empty = LoopSpec.from_dict({"id": "empty-loop", "phases": []})
    try:
        render_loop_validation(empty)
    except ValueError as exc:
        assert "at least one phase" in str(exc)
    else:
        raise AssertionError("empty loop should fail validation")


def test_loop_planner_creates_user_friendly_valid_draft(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    draft = LoopPlanner().create_draft("做一个 AI 简历生成器 landing page，有上传入口、价格卡片、FAQ，移动端适配")

    assert draft.intent_type == "web_feature"
    assert draft.planner_source == "heuristic"
    assert draft.status == "awaiting_confirmation"
    assert draft.execution_limits.max_duration_seconds >= 900
    assert "npm run build" in draft.command_candidates
    rendered = render_loop_draft(draft)
    assert "Next actions" in rendered and "/loop confirm" in rendered
    validation = validate_loop_spec(draft.loop_spec, agent=agent, strict_policy=True)
    assert validation.ok, validation.errors
    assert draft.loop_spec.command_allowlist
    assert draft.loop_spec.execution_limits["max_repair_rounds"] == 1


def test_loop_planner_uses_llm_first_and_sanitizes_output(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    fake_llm = FakeLoopPlannerLLM(llm_loop_payload())
    agent.llm = fake_llm  # type: ignore[assignment]

    draft = LoopPlanner().create_draft("做一个响应式 landing page，有 hero、pricing、FAQ", agent=agent)

    assert fake_llm.calls, "planner should call LLM before heuristic fallback"
    assert draft.planner_source == "llm"
    assert draft.planner_model == temp_config.model
    assert draft.goal.startswith("交付一个响应式 landing page")
    assert [phase.id for phase in draft.phases] == ["context_scan", "product_design", "implementation", "verification", "visual_acceptance", "final_report"]
    assert "npm run build" in draft.command_candidates
    assert all("rm" not in command and "git push" not in command for command in draft.command_candidates)
    assert any("Dropped unsafe command" in warning for warning in draft.planner_warnings)
    assert any(phase.id == "product_design" for phase in draft.loop_spec.phases)
    assert any(phase.id == "visual_acceptance" for phase in draft.loop_spec.phases)
    rendered = render_loop_draft(draft)
    assert "Planner: llm" in rendered


def test_loop_planner_falls_back_when_llm_json_invalid(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    fake_llm = FakeLoopPlannerLLM("not json")
    agent.llm = fake_llm  # type: ignore[assignment]

    draft = LoopPlanner().create_draft("帮我补 README 文档", agent=agent)

    assert fake_llm.calls
    assert draft.planner_source == "heuristic"
    assert draft.intent_type == "docs"
    assert any("no valid JSON" in warning for warning in draft.planner_warnings)


def test_loop_draft_session_persists_revises_confirms_and_saves(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    session = LoopDraftSession.for_agent(agent)

    draft = session.plan("帮我补 README 文档，说明 loop 功能")
    assert session.load().draft_id == draft.draft_id
    revised = session.revise("增加测试说明和使用示例")
    assert revised.revisions == ["增加测试说明和使用示例"]
    confirmed = session.confirm(agent=agent)
    assert confirmed.status == "ready_to_run"
    path = session.save_loop("docs-loop-template")
    assert path.exists()
    saved = LoopRegistry(temp_config.loops_dir).load("generated-docs-loop-template")
    assert saved.id == "generated-docs-loop-template"
    session.clear()
    assert session.load() is None


def test_loop_validation_rejects_execution_limit_violations(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    spec = LoopSpec.from_dict(
        {
            "id": "limit-loop",
            "execution_limits": {"max_total_phases": 1, "max_phase_retries": 0},
            "phases": [
                {"id": "a", "type": "tool", "tool": "sandbox_info"},
                {"id": "b", "type": "tool", "tool": "sandbox_info", "depends_on": ["a"], "retries": 1},
            ],
        }
    )
    validation = validate_loop_spec(spec, agent=agent, strict_policy=True)
    assert not validation.ok
    assert any("max_total_phases" in error for error in validation.errors)
    assert any("max_phase_retries" in error for error in validation.errors)


def test_loop_runner_enforces_execution_limits(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)

    max_tools = LoopSpec.from_dict(
        {
            "id": "max-tools-loop",
            "execution_limits": {"max_tool_calls": 1},
            "phases": [
                {"id": "one", "type": "tool", "tool": "sandbox_info"},
                {"id": "two", "type": "tool", "tool": "sandbox_info", "depends_on": ["one"]},
            ],
        }
    )
    tool_result = LoopRunner(agent).run(max_tools)
    assert not tool_result.ok
    assert tool_result.status == "budget_exceeded"
    assert "max_tool_calls" in tool_result.phase_results[-1].output

    max_commands = LoopSpec.from_dict(
        {
            "id": "max-commands-loop",
            "command_allowlist": ["python3"],
            "execution_limits": {"max_command_runs": 1},
            "phases": [
                {"id": "one", "type": "tool", "tool": "shell", "args": {"command": "python3 -c 'print(1)'"}},
                {"id": "two", "type": "tool", "tool": "shell", "args": {"command": "python3 -c 'print(2)'"}, "depends_on": ["one"]},
            ],
        }
    )
    command_result = LoopRunner(agent).run(max_commands)
    assert not command_result.ok
    assert "max_command_runs" in command_result.phase_results[-1].output

    max_files = LoopSpec.from_dict(
        {
            "id": "max-files-loop",
            "execution_limits": {"max_file_changes": 1},
            "phases": [
                {"id": "write1", "type": "tool", "tool": "write_file", "args": {"path": "evolva/workspace/loop-a.txt", "content": "a"}},
                {"id": "write2", "type": "tool", "tool": "write_file", "args": {"path": "evolva/workspace/loop-b.txt", "content": "b"}, "depends_on": ["write1"]},
            ],
        }
    )
    file_result = LoopRunner(agent).run(max_files)
    assert not file_result.ok
    assert "max_file_changes" in file_result.phase_results[-1].output


def test_loop_parser_accepts_show_spec_after_free_form_text():
    parser = build_parser()

    planned = parser.parse_args(["loop", "plan", "做网页", "--show-spec"])
    assert planned.loop_cmd == "plan"
    assert planned.show_spec is True
    assert planned.request == ["做网页"]

    revised = parser.parse_args(["loop", "revise", "增加移动端验收", "--show-spec"])
    assert revised.loop_cmd == "revise"
    assert revised.show_spec is True
    assert revised.feedback == ["增加移动端验收"]


def test_cli_and_tui_loop_commands(monkeypatch, capsys, temp_config):
    monkeypatch.setattr("evolva.cli.AgentConfig", lambda: temp_config)
    assert loop_cmd(Namespace(loop_cmd="list", yes=True)) == 0
    assert "dream-loop" in capsys.readouterr().out
    assert loop_cmd(Namespace(loop_cmd="show", loop_id="dream-loop", yes=True)) == 0
    assert '"id": "dream-loop"' in capsys.readouterr().out
    assert loop_cmd(Namespace(loop_cmd="validate", loop_id="dream-loop", yes=True)) == 0
    assert "Status: ok" in capsys.readouterr().out
    assert loop_cmd(Namespace(loop_cmd="dry-run", loop_id="dream-loop", yes=True)) == 0
    assert "Execution: not run" in capsys.readouterr().out
    assert loop_cmd(Namespace(loop_cmd="run", loop_id="dream-loop", json=False, yes=True, resume=False)) in {0, 1}
    assert "Loop run:" in capsys.readouterr().out
    assert loop_cmd(Namespace(loop_cmd="plan", request=["做一个", "landing", "page"], show_spec=False, yes=True)) == 0
    assert "Loop Draft:" in capsys.readouterr().out
    assert loop_cmd(Namespace(loop_cmd="show-draft", show_spec=True, yes=True)) == 0
    assert "Generated LoopSpec" in capsys.readouterr().out
    assert loop_cmd(Namespace(loop_cmd="revise", feedback=["增加", "FAQ"], show_spec=False, yes=True)) == 0
    assert "FAQ" in capsys.readouterr().out
    assert loop_cmd(Namespace(loop_cmd="confirm", yes=True)) == 0
    assert "Dry-run: ok" in capsys.readouterr().out
    assert loop_cmd(Namespace(loop_cmd="save", name="cli generated loop", yes=True)) == 0
    assert "Saved Loop spec" in capsys.readouterr().out
    assert loop_cmd(Namespace(loop_cmd="cancel", yes=True)) == 0
    assert "Cancelled" in capsys.readouterr().out

    agent = EvolvaAgent(temp_config, assume_yes=True)
    assert handle_command(agent, "/loop 做一个响应式 landing page") is True
    assert handle_command(agent, "/loop show-draft") is True
    out = capsys.readouterr().out
    assert "Loop Draft:" in out and "Generated LoopSpec" in out
    assert handle_command(agent, "/loop list") is True
    assert handle_command(agent, "/loop show dream-loop") is True
    assert handle_command(agent, "/loop run dream-loop") is True
    out = capsys.readouterr().out
    assert "dream-loop" in out and "Loop run:" in out

    monkeypatch.setattr("evolva.tui.AgentConfig", lambda: temp_config)
    app = EvolvaTUI(assume_yes=True)
    app._handle_command("/loop list")
    assert any("dream-loop" in m.text for m in app.messages)
    app._handle_command("/loop show dream-loop")
    assert any('"id": "dream-loop"' in m.text for m in app.messages)
    app._handle_command("/loop validate dream-loop")
    assert any("Loop validation: dream-loop" in m.text for m in app.messages)
    app._handle_command("/loop dry-run dream-loop")
    assert any("Loop dry-run: dream-loop" in m.text for m in app.messages)
    app._handle_command("/loop 做一个网页，包含 hero 和 pricing")
    assert any("Loop Draft:" in m.text for m in app.messages)
    app._handle_command("/loop confirm")
    assert any("Loop confirmation:" in m.text for m in app.messages)
