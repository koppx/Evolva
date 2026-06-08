from __future__ import annotations

import json
from argparse import Namespace

from evolva.agent.core import EvolvaAgent
from evolva.agent.dream import DreamEngine
from evolva.cli import dream_cmd


def _failed_trace(agent: EvolvaAgent) -> str:
    run_id = agent.tracer.start("run dangerous shell")
    agent.tracer.event("tool_call", {"tool": "shell", "ok": False, "output": "bad"})
    agent.tracer.event("policy_decision", {"tool": "shell", "allowed": False})
    agent.tracer.end("done", status="completed_with_tool_failures")
    return run_id


def test_dream_engine_analyzes_trace_and_writes_report(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    _failed_trace(agent)

    engine = DreamEngine(agent)
    report = engine.run(trace_limit=5, apply=False)
    rendered = engine.render(report)

    assert report.mode == "analyze"
    assert report.inspected["traces"] == 1
    assert report.stages == ["collect", "hypothesize", "critique", "plan", "archive"]
    assert report.evidence
    assert report.hypotheses
    assert report.actions
    assert report.insights
    assert report.report_path
    assert temp_config.dreams_dir.joinpath(report.report_path.split("/")[-1]).exists()
    assert "Dream report" in rendered
    assert "Hypotheses" in rendered
    assert "Dream" in agent.context.render("Dream")


def test_dream_engine_apply_promotes_high_confidence_proposals(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    _failed_trace(agent)

    report = DreamEngine(agent).run(trace_limit=5, apply=True)

    assert report.mode == "apply"
    assert report.applied >= 1
    assert "trace_analysis" in agent.evolution.render_status()
    assert any("tool_failure" in skill.path.read_text(encoding="utf-8") for skill in agent.skills.list())


def test_dream_engine_respects_drift_guard_threshold(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    _failed_trace(agent)

    report = DreamEngine(agent).run(trace_limit=5, apply=True, min_confidence=0.99)

    assert report.applied == 0
    assert report.rejections
    assert any("confidence" in item for item in report.rejections)


def test_dream_engine_uses_eval_report(temp_config, tmp_path):
    report_path = tmp_path / "eval.json"
    report_path.write_text(
        json.dumps(
            {
                "results": [
                    {"id": "bad", "passed": False, "checks": {"contains:expected": False}, "answer": "missing", "tool_logs": []}
                ]
            }
        ),
        encoding="utf-8",
    )
    agent = EvolvaAgent(temp_config, assume_yes=True)
    report = DreamEngine(agent).run(eval_report=report_path)

    assert report.inspected["eval_results"] == 1
    assert any(insight.source == "eval" for insight in report.insights)
    assert any(item.source == "eval" for item in report.hypotheses)


def test_dream_bootstrap_is_observe_only(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)

    report = DreamEngine(agent).run(apply=True)

    assert any(item.id == "hyp_bootstrap_evolution_loop" for item in report.hypotheses)
    assert report.applied == 0
    assert any("observe-only" in item for item in report.rejections)


def test_cli_dream_cmd(monkeypatch, capsys, temp_config):
    monkeypatch.setattr("evolva.cli.AgentConfig", lambda: temp_config)
    assert dream_cmd(Namespace(apply=False, limit=5, report=None, min_confidence=None, json=False)) == 0
    output = capsys.readouterr().out
    assert "Dream report" in output


def test_cli_dream_cmd_json(monkeypatch, capsys, temp_config):
    monkeypatch.setattr("evolva.cli.AgentConfig", lambda: temp_config)
    assert dream_cmd(Namespace(apply=False, limit=5, report=None, min_confidence=0.8, json=True)) == 0
    output = capsys.readouterr().out
    data = json.loads(output)
    assert data["stages"]
    assert "hypotheses" in data
