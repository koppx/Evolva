from __future__ import annotations

import json

import pytest

from evolva.agent.context import ContextStore
from evolva.agent.evolution import SelfEvolutionEngine
from evolva.agent.evolution_analyzer import EvalEvolutionAnalyzer, TraceEvolutionAnalyzer, apply_proposals, render_analysis, render_reports
from evolva.agent.memory import MemoryStore
from evolva.agent.skills import SkillStore
from evolva.agent.tracing import TraceRecorder
from evolva.agent.todo import TodoStore


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
    store.add("fact", "Use pytest for unit tests", source="a")
    store.add("lesson", "Always run compileall", source="b")
    assert store.search("pytest")[0].content == "Use pytest for unit tests"
    assert len(store.all(limit=1)) == 1
    assert store.find_similar("fact", "Use pytest for unit tests") is not None
    assert store.stats()["total"] == 2
    assert "fact: 1" in store.render_stats()
    assert "Use pytest for unit tests" in store.render_items(query="pytest")
    assert "Always run compileall" in store.render_items(limit=1)


def test_skill_store_seeds_sanitizes_and_appends(tmp_path):
    skills = SkillStore(tmp_path / "skills")
    assert "general_agent" in [s.name for s in skills.list()]
    path = skills.upsert("Check Python!!!", "Run py_compile", metadata={"source": "self_evolution", "category": "verification"})
    assert path.name == "check_python.md"
    skills.upsert("Check Python!!!", "Run pytest")
    text = path.read_text()
    assert "source: self_evolution" in text and "Run py_compile" in text and "Run pytest" in text
    assert "check_python" in skills.context("pytest")
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


def test_self_evolution_records_memory_and_skill(tmp_path):
    memory = MemoryStore(tmp_path / "memory.jsonl")
    skills = SkillStore(tmp_path / "skills")
    report = SelfEvolutionEngine(memory, skills).evolve("Prefer tests", task="edit code", outcome="ok")
    assert "Prefer tests" in report.lesson
    assert report.trigger == "manual_feedback"
    assert report.category in {"preference", "verification"}
    assert report.actions
    assert report.memory_written
    assert report.skill_path
    assert "Prefer tests" in memory.context("Prefer")
    assert "Checklist" in skills.context("Prefer")

    duplicate = SelfEvolutionEngine(memory, skills).evolve("Prefer tests", task="edit code", outcome="ok")
    assert duplicate.deduped
    assert not duplicate.memory_written

    status = SelfEvolutionEngine(memory, skills).status()
    assert status["total_lessons"] == 1
    assert status["skill_stats"]["evolved"] >= 1
    assert "Evolution status" in SelfEvolutionEngine(memory, skills).render_status()


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
    assert "Applied evolution reports" in render_reports(reports)


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
