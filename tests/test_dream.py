from __future__ import annotations

import json
from argparse import Namespace

from evolva.agent.core import EvolvaAgent
from evolva.agent.dream import DreamCandidate, DreamEngine, DreamVerifier
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
    assert report.stages == ["collect", "hypothesize", "critique", "candidate", "verify", "archive"]
    assert report.evidence
    assert report.hypotheses
    assert report.actions
    assert report.candidates
    assert report.candidates[0].verifier is not None
    assert report.candidates[0].status == "accepted"
    assert report.candidates[0].affected_surfaces
    assert report.insights
    assert report.report_path
    assert temp_config.dreams_dir.joinpath(report.report_path.split("/")[-1]).exists()
    assert "Dream report" in rendered
    assert "Hypotheses" in rendered
    assert "Candidates" in rendered
    backlog = engine.load_backlog()
    assert backlog.candidates
    assert "Dream backlog" in engine.render_backlog()
    assert "Dream" in agent.context.render("Dream")


def test_dream_engine_apply_stages_candidates_until_verified(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    _failed_trace(agent)

    report = DreamEngine(agent).run(trace_limit=5, apply=True)

    assert report.mode == "apply"
    assert report.applied == 0
    assert report.candidates
    assert all(candidate.status == "accepted" for candidate in report.candidates)
    assert any(action.kind == "verify_before_promotion" for action in report.actions)
    assert "trace_analysis" not in agent.evolution.render_status()


def test_dream_engine_legacy_apply_can_write_immediately(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    object.__setattr__(agent.config, "dream_require_verification", False)
    _failed_trace(agent)

    report = DreamEngine(agent).run(trace_limit=5, apply=True)

    assert report.applied >= 1
    assert any(candidate.status == "applied" for candidate in report.candidates)
    assert "trace_analysis" in agent.evolution.render_status()


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
    assert any(item.verifier and item.verifier.type == "eval" for item in report.candidates)


def test_dream_candidate_roundtrip_and_backlog_dedupe(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    engine = DreamEngine(agent)
    candidate = DreamCandidate(
        id="cand_demo",
        title="Demo candidate",
        category="verification",
        evidence_ids=["ev_demo"],
        affected_surfaces=["memory", "skill", "eval"],
        proposed_change={"kind": "evolution_lesson", "feedback": "verify before final"},
        verifier=DreamVerifier(type="eval", command="evolva eval evals/tasks/smoke.jsonl --yes"),
        confidence=0.91,
        status="accepted",
    )

    engine._merge_backlog([candidate])
    engine._merge_backlog([candidate])
    backlog = engine.load_backlog()

    assert len(backlog.candidates) == 1
    assert backlog.candidates[0].fingerprint == candidate.fingerprint
    assert backlog.candidates[0].verifier.type == "eval"


def test_dream_status_renders_gate_and_candidate_counts(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    engine = DreamEngine(agent)
    engine._merge_backlog(
        [
            DreamCandidate(
                id="cand_status_wait",
                title="Waiting candidate",
                category="workflow",
                verifier=DreamVerifier(type="manual_review"),
                status="accepted",
            ),
            DreamCandidate(
                id="cand_status_done",
                title="Promoted candidate",
                category="workflow",
                verifier=DreamVerifier(type="manual_review"),
                status="promoted",
            ),
        ]
    )

    rendered = engine.render_status()

    assert "Dream status" in rendered
    assert "Verification gate: required" in rendered
    assert "pending_verification=1" in rendered
    assert "promoted=1" in rendered


def test_dream_verify_backlog_runs_eval_verifier_and_promotes(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    engine = DreamEngine(agent)
    candidate = DreamCandidate(
        id="cand_eval",
        title="Verify dream eval",
        category="verification",
        evidence_ids=["ev_eval"],
        proposed_change={"kind": "evolution_lesson", "feedback": "verify with local eval"},
        verifier=DreamVerifier(type="eval", command="evolva eval smoke --yes"),
        confidence=0.91,
        status="applied",
    )
    engine._merge_backlog([candidate])
    task_file = temp_config.root / "dream_verify.jsonl"
    task_file.write_text(
        json.dumps({"id": "memory_help", "input": "remember dream verifier", "expected_contains": ["已记住"], "scorers": ["no_tool_error"]}) + "\n",
        encoding="utf-8",
    )

    results = engine.verify_backlog(tasks_path=task_file, promote=True)
    backlog = engine.load_backlog()

    assert results and results[0].ok
    assert backlog.candidates[0].status == "promoted"
    assert backlog.candidates[0].verification["ok"] is True
    assert "evolution_fingerprint" in backlog.candidates[0].verification
    assert "dream_promote" in agent.evolution.render_status()
    assert "Dream verification: 1/1 passed" in engine.render_verification(results)


def test_dream_tool_adapter_can_verify(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)
    output, data = agent._run_dream_tool(limit=5, verify=True)

    assert "Dream verification" in output
    assert "verification" in data


def test_dream_bootstrap_is_observe_only(temp_config):
    agent = EvolvaAgent(temp_config, assume_yes=True)

    report = DreamEngine(agent).run(apply=True)

    assert any(item.id == "hyp_bootstrap_evolution_loop" for item in report.hypotheses)
    assert report.applied == 0
    assert any("observe-only" in item for item in report.rejections)


def test_cli_dream_cmd(monkeypatch, capsys, temp_config):
    monkeypatch.setattr("evolva.cli.AgentConfig", lambda: temp_config)
    assert dream_cmd(Namespace(dream_cmd=None, apply=False, limit=5, report=None, min_confidence=None, json=False)) == 0
    output = capsys.readouterr().out
    assert "Dream report" in output


def test_cli_dream_cmd_json(monkeypatch, capsys, temp_config):
    monkeypatch.setattr("evolva.cli.AgentConfig", lambda: temp_config)
    assert dream_cmd(Namespace(dream_cmd=None, apply=False, limit=5, report=None, min_confidence=0.8, json=True)) == 0
    output = capsys.readouterr().out
    data = json.loads(output)
    assert data["stages"]
    assert "hypotheses" in data
    assert "candidates" in data


def test_cli_dream_backlog_cmd(monkeypatch, capsys, temp_config):
    monkeypatch.setattr("evolva.cli.AgentConfig", lambda: temp_config)
    agent = EvolvaAgent(temp_config, assume_yes=True)
    _failed_trace(agent)
    DreamEngine(agent).run(trace_limit=5)

    assert dream_cmd(Namespace(dream_cmd="backlog", limit=5)) == 0
    assert "Dream backlog" in capsys.readouterr().out


def test_cli_dream_verify_cmd(monkeypatch, capsys, temp_config):
    monkeypatch.setattr("evolva.cli.AgentConfig", lambda: temp_config)
    agent = EvolvaAgent(temp_config, assume_yes=True)
    engine = DreamEngine(agent)
    engine._merge_backlog(
        [
            DreamCandidate(
                id="cand_manual",
                title="Manual review candidate",
                category="workflow",
                verifier=DreamVerifier(type="manual_review", expected="manual approval"),
                status="accepted",
            )
        ]
    )

    code = dream_cmd(Namespace(dream_cmd="verify", tasks=None, limit=5, promote=False, json=False))

    assert code == 1
    assert "Dream verification" in capsys.readouterr().out
