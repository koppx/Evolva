from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from evolva.agent.context import ContextStore
from evolva.agent.evolution import SelfEvolutionEngine
from evolva.agent.evolution_analyzer import EvalEvolutionAnalyzer, TraceEvolutionAnalyzer, apply_proposals, render_analysis, render_reports
from evolva.agent.memory import MemoryStore
from evolva.agent.observability import AlertRule, ObservabilitySink
from evolva.agent.skills import SkillStore
from evolva.agent.tracing import TraceRecorder
from evolva.agent.todo import TodoStore
from evolva.storage import atomic_update_json


def test_memory_ignores_empty_and_malformed_rows(tmp_path):
    path = tmp_path / "memory.jsonl"
    store = MemoryStore(path)
    empty = store.add("fact", "   ")
    assert empty.content == ""
    assert not path.exists()

    path.write_text('{"kind":"fact","content":"alpha beta","confidence":0.9,"source":"test","ts":1}\nnot-json\n')
    assert [m.content for m in store.search("alpha")] == ["alpha beta"]
    assert "alpha beta" in store.context("beta")


def test_memory_search_ranks_exact_matches(tmp_path):
    store = MemoryStore(tmp_path / "memory.jsonl")
    item = store.add("fact", "Use pytest for unit tests", source="a", evidence=["trace:1"])
    store.add("lesson", "Always run compileall", source="b")
    assert store.search("pytest")[0].content == "Use pytest for unit tests"
    assert store.search("trace:1")[0].id == item.id
    assert len(store.all(limit=1)) == 1
    assert store.find_similar("fact", "Use pytest for unit tests") is not None
    assert store.stats()["total"] == 2
    assert "fact: 1" in store.render_stats()
    assert "Use pytest for unit tests" in store.render_items(query="pytest")
    assert "Always run compileall" in store.render_items(limit=1)
    assert store.rollback(item.id, reason="bad lesson")
    assert not store.search("pytest")


def test_skill_store_seeds_sanitizes_and_appends(tmp_path):
    skills = SkillStore(tmp_path / "skills")
    assert "general_agent" in [s.name for s in skills.list()]
    path = skills.upsert("Check Python!!!", "Run py_compile", metadata={"source": "self_evolution", "category": "verification"})
    assert path.name == "check_python.md"
    skills.upsert("Check Python!!!", "Run pytest")
    text = path.read_text()
    assert "source: self_evolution" in text and "Run py_compile" in text and "Run pytest" in text
    assert "check_python" in skills.context("pytest")
    assert skills.list()[0].metadata is not None
    triggered = skills.upsert("Trace Guard", "Inspect trace before promotion", metadata={"triggers": ["trace", "promotion"], "source": "manual"})
    assert triggered.exists()
    assert skills.match("promotion gate")[0].name == "trace_guard"
    assert skills.stats()["evolved"] == 1


def test_context_store_caps_searches_and_compacts(tmp_path):
    context = ContextStore(tmp_path / "context.json", max_items=3)
    context.add("note", "first old")
    context.add("decision", "Use sandbox", role="planner", meta={"area": "safety"})
    context.add("artifact", "Generated report")
    context.add("message", "latest message", role="user")

    assert "first old" not in context.render(limit=10)
    assert "Use sandbox" in context.render("safety")
    summary = context.compact("Daily summary")
    assert summary.kind == "summary"
    assert summary.meta["source_items"] == 3
    assert "Daily summary" in context.prompt_context("summary")


def test_context_store_rejects_empty_content(tmp_path):
    with pytest.raises(ValueError, match="required"):
        ContextStore(tmp_path / "context.json").add("note", " ")


def test_context_store_recovers_corrupt_json(tmp_path):
    path = tmp_path / "context.json"
    path.write_text("{bad json", encoding="utf-8")
    context = ContextStore(path)
    assert context.render() == "No context."
    assert list(tmp_path.glob("context.json.corrupt.*"))
    context.add("note", "recovered")
    assert "recovered" in context.render()


def test_todo_store_lifecycle_errors_and_clear(tmp_path):
    todos = TodoStore(tmp_path / "todos.json")
    with pytest.raises(ValueError, match="title"):
        todos.add(" ")
    first = todos.add("Implement tests", detail="pytest", owner="coder")
    second = todos.add("Review", owner="reviewer")
    assert second.id == first.id + 1
    assert "Implement tests" in todos.context()
    todos.update(first.id, status="done")
    assert "Implement tests" not in todos.render(include_done=False)
    assert todos.clear() == 1
    assert "Review" in todos.render()
    assert todos.clear(include_done=True) == 1
    assert todos.render() == "No todos."
    with pytest.raises(KeyError):
        todos.update(999, status="done")
    item = todos.add("Validate bad status")
    with pytest.raises(ValueError, match="invalid status"):
        todos.update(item.id, status="bad")


def test_todo_store_concurrent_adds_do_not_lose_items(tmp_path):
    todos = TodoStore(tmp_path / "todos.json")

    def add_item(index: int) -> int:
        return todos.add(f"task {index}").id

    with ThreadPoolExecutor(max_workers=8) as executor:
        ids = list(executor.map(add_item, range(20)))

    items = todos.list()
    assert len(items) == 20
    assert len({item.id for item in items}) == 20
    assert sorted(ids) == list(range(1, 21))


def test_atomic_update_json_preserves_old_file_on_update_error(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"ok": True}), encoding="utf-8")

    def boom(data):
        data["ok"] = False
        raise RuntimeError("no write")

    with pytest.raises(RuntimeError, match="no write"):
        atomic_update_json(path, {}, boom)
    assert json.loads(path.read_text(encoding="utf-8")) == {"ok": True}


def test_self_evolution_records_memory_and_skill(tmp_path):
    memory = MemoryStore(tmp_path / "memory.jsonl")
    skills = SkillStore(tmp_path / "skills")
    report = SelfEvolutionEngine(memory, skills).evolve("Prefer tests", task="edit code", outcome="ok")
    assert "Prefer tests" in report.lesson
    assert report.trigger == "manual_feedback"
    assert report.category in {"preference", "verification"}
    assert report.actions
    assert report.memory_written
    assert report.fingerprint
    assert any("task=edit code" in item for item in report.evidence)
    assert report.skill_path
    assert "Prefer tests" in memory.context("Prefer")
    skill_context = skills.context("Prefer")
    assert "Checklist" in skill_context and "Fingerprint" in skill_context and "Evidence" in skill_context

    duplicate = SelfEvolutionEngine(memory, skills).evolve("Prefer tests", task="edit code", outcome="ok")
    assert duplicate.deduped
    assert not duplicate.memory_written

    status = SelfEvolutionEngine(memory, skills).status()
    assert status["total_lessons"] == 1
    assert status["lesson_categories"]
    assert status["skill_stats"]["evolved"] >= 1
    assert "Evolution status" in SelfEvolutionEngine(memory, skills).render_status()


def test_self_evolution_audit_reports_coverage_and_recommendations(tmp_path):
    engine = SelfEvolutionEngine(MemoryStore(tmp_path / "memory.jsonl"), SkillStore(tmp_path / "skills"))
    report = engine.evolve("Always verify Python edits", category="verification", evidence=["unit-test evidence"], confidence=0.91)
    assert report.category == "verification"
    assert report.confidence == 0.91
    assert "unit-test evidence" in report.lesson

    audit = engine.audit()
    assert audit["status"]["total_lessons"] == 1
    assert "verification" in audit["status"]["lesson_categories"]
    assert audit["recommendations"]
    rendered = engine.render_audit()
    assert "Evolution audit" in rendered and "Recommended next steps" in rendered


def test_reflect_after_turn_only_for_failures_or_long_answer(tmp_path):
    engine = SelfEvolutionEngine(MemoryStore(tmp_path / "memory.jsonl"), SkillStore(tmp_path / "skills"))
    assert engine.reflect_after_turn("task", "short", []) is None
    tool_report = engine.reflect_after_turn("task", "short", ["shell"])
    assert tool_report is not None and tool_report.trigger == "tool_failure"
    long_report = engine.reflect_after_turn("task", "x" * 4001, [])
    assert long_report is not None and long_report.trigger == "quality_signal"


def test_trace_evolution_analyzer_generates_and_applies_proposals(tmp_path):
    tracer = TraceRecorder(tmp_path / "traces")
    tracer.start("run missing")
    tracer.event("tool_call", {"tool": "shell", "ok": False, "output": "bad"})
    tracer.event("policy_decision", {"tool": "shell", "allowed": False})
    tracer.end("done", status="completed_with_tool_failures")

    analysis = TraceEvolutionAnalyzer(tracer).analyze(limit=5)
    assert analysis.inspected == 1
    assert {p.category for p in analysis.proposals} >= {"tool_failure", "safety"}
    assert "Evolution analysis: trace" in render_analysis(analysis)

    engine = SelfEvolutionEngine(MemoryStore(tmp_path / "memory.jsonl"), SkillStore(tmp_path / "skills"))
    reports = apply_proposals(engine, analysis.proposals)
    assert reports and any(r.trigger == "trace_analysis" for r in reports)
    assert any(r.evidence for r in reports)
    assert any(r.category == "safety" for r in reports)
    assert "Applied evolution reports" in render_reports(reports)


def test_trace_recorder_redacts_secret_payloads(tmp_path):
    tracer = TraceRecorder(tmp_path / "traces")
    run_id = tracer.start("secret run")
    tracer.event("tool_call", {"api_key": "secret123456789", "output": "token=abcdefghi12345"})
    tracer.end("password=supersecret123", status="completed")

    text = (tmp_path / "traces" / f"{run_id}.json").read_text(encoding="utf-8")
    assert "secret123456789" not in text
    assert "abcdefghi12345" not in text
    assert "supersecret123" not in text
    assert "[REDACTED:api_key]" in text


def test_observability_sink_records_metrics_alerts_and_dedupes(tmp_path):
    sink = ObservabilitySink(
        tmp_path / "metrics" / "metrics.jsonl",
        tmp_path / "metrics" / "alerts.jsonl",
        rules=[AlertRule("policy-denied-test", "policy.denied", dedupe_seconds=60)],
    )

    sink.record("policy.denied", tags={"tool": "shell", "risk": "critical"})
    sink.record("policy.denied", tags={"tool": "shell", "risk": "critical"})

    metrics = sink.recent_metrics(name="policy.denied")
    alerts = sink.recent_alerts()
    assert len(metrics) == 2
    assert len(alerts) == 1
    assert alerts[0].rule == "policy-denied-test"
    assert alerts[0].tags["tool"] == "shell"
    assert "policy.denied" in sink.render_metrics()
    assert "policy-denied-test" in sink.render_alerts()
    prometheus = sink.render_prometheus()
    assert 'evolva_policy_denied_total{risk="critical",tool="shell"} 2' in prometheus
    assert 'evolva_alert_active{metric="policy.denied",risk="critical",rule="policy-denied-test",severity="warning",tool="shell"} 1' in prometheus


def test_trace_recorder_emits_metrics_and_alerts(tmp_path):
    sink = ObservabilitySink(tmp_path / "metrics" / "metrics.jsonl", tmp_path / "metrics" / "alerts.jsonl")
    tracer = TraceRecorder(tmp_path / "traces", observability=sink)
    tracer.start("observable run")
    tracer.event(
        "policy_decision",
        {
            "tool": "shell",
            "allowed": False,
            "risk": "critical",
            "reason": "Denied dangerous pattern",
            "redactions": ["command"],
            "audit_tags": ["dangerous_command"],
        },
    )
    tracer.event("tool_call", {"tool": "mcp_call", "ok": False, "latency_ms": 25, "output": "MCP request timed out"})
    tracer.event("tool_error", {"tool": "mcp_call", "error": "MCP request timed out"})
    tracer.event("artifact_error", {"tool": "write_file", "error": "digest mismatch"})
    tracer.end("done")

    names = [record.name for record in sink.recent_metrics()]
    assert "policy.decision" in names
    assert "policy.denied" in names
    assert "redaction.hit" in names
    assert "tool.call" in names
    assert "tool.latency_ms" in names
    assert "tool.failure" in names
    assert "tool.error" in names
    assert "mcp.timeout" in names
    assert "artifact.error" in names
    alert_rules = {alert.rule for alert in sink.recent_alerts()}
    assert {"policy-denied-any", "tool-failure-any", "tool-error-any", "mcp-timeout-any", "artifact-error-any"} <= alert_rules


def test_eval_evolution_analyzer_reads_failures(tmp_path):
    report = tmp_path / "eval_results" / "demo.json"
    report.parent.mkdir()
    report.write_text(
        json.dumps(
            {
                "summary": {"total": 2, "passed": 1, "failed": 1},
                "results": [
                    {"id": "ok", "passed": True, "score": 1.0, "checks": {"contains:ok": True}, "answer": "ok", "tool_logs": []},
                    {"id": "bad", "passed": False, "score": 0.0, "checks": {"contains:hello": False}, "answer": "missing", "tool_logs": []},
                ],
            }
        ),
        encoding="utf-8",
    )
    analysis = EvalEvolutionAnalyzer(report.parent).analyze_file(report)
    assert analysis.inspected == 2
    assert len(analysis.proposals) == 1
    assert analysis.proposals[0].trigger == "eval_failure"
    assert analysis.proposals[0].category == "quality"
