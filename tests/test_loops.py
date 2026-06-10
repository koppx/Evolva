from __future__ import annotations

import json
from argparse import Namespace

from evolva.agent.core import EvolvaAgent
from evolva.cli import handle_command, loop_cmd
from evolva.loops import LoopRegistry, LoopRunner, LoopSpec, render_loop_result, render_loop_specs
from evolva.tui import EvolvaTUI


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


def test_cli_and_tui_loop_commands(monkeypatch, capsys, temp_config):
    monkeypatch.setattr("evolva.cli.AgentConfig", lambda: temp_config)
    assert loop_cmd(Namespace(loop_cmd="list", yes=True)) == 0
    assert "dream-loop" in capsys.readouterr().out
    assert loop_cmd(Namespace(loop_cmd="show", loop_id="dream-loop", yes=True)) == 0
    assert '"id": "dream-loop"' in capsys.readouterr().out
    assert loop_cmd(Namespace(loop_cmd="run", loop_id="dream-loop", json=False, yes=True)) in {0, 1}
    assert "Loop run:" in capsys.readouterr().out

    agent = EvolvaAgent(temp_config, assume_yes=True)
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
