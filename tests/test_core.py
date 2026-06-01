from evolva.agent.context import ContextStore
from evolva.agent.evolution import SelfEvolutionEngine
from evolva.agent.core import EvolvaAgent
from evolva.agent.memory import MemoryStore
from evolva.agent.sandbox import Sandbox, SandboxPolicy
from evolva.agent.skills import SkillStore
from evolva.agent.todo import TodoStore
from evolva.tools.builtin import build_registry
from evolva.agent.multi_agent import MultiAgentCoordinator
from evolva.agent.llm import OpenAICompatibleLLM
from evolva.config import AgentConfig
from evolva.agent.policy import PolicyConfig, PolicyEngine
from evolva.agent.tracing import TraceRecorder
from evolva.eval.harness import EvalHarness
from evolva.workflow.engine import WorkflowEngine


def test_memory_search(tmp_path):
    store = MemoryStore(tmp_path / "memory.jsonl")
    store.add("fact", "Python files should be checked with py_compile")
    assert "py_compile" in store.context("Python")


def test_skill_upsert(tmp_path):
    skills = SkillStore(tmp_path / "skills")
    path = skills.upsert("Check Python", "Run py_compile")
    assert path.exists()
    assert "py_compile" in path.read_text()


def test_tools_write_read(tmp_path):
    memory = MemoryStore(tmp_path / "memory.jsonl")
    skills = SkillStore(tmp_path / "skills")
    context = ContextStore(tmp_path / "context.json")
    todos = TodoStore(tmp_path / "todos.json")
    sandbox = Sandbox(SandboxPolicy(tmp_path, tmp_path / "workspace"))
    llm = OpenAICompatibleLLM(AgentConfig(root=tmp_path, workspace=tmp_path / "workspace", memory_file=tmp_path / "memory.jsonl", skills_dir=tmp_path / "skills", context_file=tmp_path / "context.json", todo_file=tmp_path / "todos.json"))
    coordinator = MultiAgentCoordinator(llm, memory, skills, todos)
    reg = build_registry(sandbox, memory, skills, context, todos, coordinator)
    assert reg.call("write_file", {"path": "a.txt", "content": "hello"}).ok
    out = reg.call("read_file", {"path": "a.txt"})
    assert out.ok and out.output == "hello"


def test_evolution_creates_lesson_and_skill(tmp_path):
    memory = MemoryStore(tmp_path / "memory.jsonl")
    skills = SkillStore(tmp_path / "skills")
    engine = SelfEvolutionEngine(memory, skills)
    report = engine.evolve("Always run tests after edits")
    assert "Always run tests" in report.lesson
    assert report.skill_path


def test_todo_store_persists_and_updates(tmp_path):
    todos = TodoStore(tmp_path / "todos.json")
    item = todos.add("Implement sandbox", owner="planner")
    assert "Implement sandbox" in todos.context()
    updated = todos.update(item.id, status="done")
    assert updated.status == "done"
    assert "done" in todos.render(include_done=True)


def test_context_store_search_and_compact(tmp_path):
    context = ContextStore(tmp_path / "context.json")
    context.add("decision", "Use a workspace sandbox", role="planner")
    assert "workspace sandbox" in context.render("sandbox")
    summary = context.compact("Summary")
    assert summary.kind == "summary"


def test_sandbox_blocks_path_escape(tmp_path):
    sandbox = Sandbox(SandboxPolicy(tmp_path, tmp_path / "workspace"))
    try:
        sandbox.resolve("../outside")
    except ValueError as exc:
        assert "escapes" in str(exc)
    else:
        raise AssertionError("expected path escape to fail")


def test_multi_agent_fallback_creates_todo(tmp_path):
    memory = MemoryStore(tmp_path / "memory.jsonl")
    skills = SkillStore(tmp_path / "skills")
    todos = TodoStore(tmp_path / "todos.json")
    llm = OpenAICompatibleLLM(AgentConfig(root=tmp_path, workspace=tmp_path / "workspace", memory_file=tmp_path / "memory.jsonl", skills_dir=tmp_path / "skills", context_file=tmp_path / "context.json", todo_file=tmp_path / "todos.json"))
    coordinator = MultiAgentCoordinator(llm, memory, skills, todos)
    output = coordinator.delegate("planner", "Add context support")
    assert "Planner fallback" in output
    assert "Sub-agent planner" in todos.render()


def test_policy_blocks_dangerous_shell(tmp_path):
    policy = PolicyEngine(PolicyConfig(root=tmp_path, workspace=tmp_path / "workspace"))
    decision = policy.check_tool("shell", {"command": "git reset --hard"})
    assert not decision.allowed
    assert decision.risk == "critical"


def test_trace_recorder_roundtrip(tmp_path):
    traces = TraceRecorder(tmp_path / "traces")
    run_id = traces.start("hello")
    traces.event("tool_call", {"tool": "noop", "ok": True})
    traces.end("done")
    assert run_id in traces.render(run_id)
    assert traces.replay_prompt(run_id) == "hello"


def test_workflow_engine_tool_node(tmp_path):
    cfg = AgentConfig(
        root=tmp_path,
        workspace=tmp_path / "evolva" / "workspace",
        memory_file=tmp_path / "evolva" / "memory" / "memory.jsonl",
        skills_dir=tmp_path / "evolva" / "skills",
        context_file=tmp_path / "evolva" / "context" / "context.json",
        todo_file=tmp_path / "evolva" / "todo" / "todos.json",
        traces_dir=tmp_path / "evolva" / "traces",
        eval_results_dir=tmp_path / "evolva" / "eval_results",
        workflows_dir=tmp_path / "evolva" / "workflows",
    )
    agent = EvolvaAgent(cfg, assume_yes=True)
    result = WorkflowEngine(agent).run({"id": "wf", "nodes": [{"id": "write", "type": "tool", "tool": "write_file", "args": {"path": "evolva/workspace/wf.txt", "content": "ok"}}]})
    assert result.ok
    assert (tmp_path / "evolva" / "workspace" / "wf.txt").exists()


def test_eval_harness_scores_contains(tmp_path):
    cfg = AgentConfig(
        root=tmp_path,
        workspace=tmp_path / "evolva" / "workspace",
        memory_file=tmp_path / "evolva" / "memory" / "memory.jsonl",
        skills_dir=tmp_path / "evolva" / "skills",
        context_file=tmp_path / "evolva" / "context" / "context.json",
        todo_file=tmp_path / "evolva" / "todo" / "todos.json",
        traces_dir=tmp_path / "evolva" / "traces",
        eval_results_dir=tmp_path / "evolva" / "eval_results",
        workflows_dir=tmp_path / "evolva" / "workflows",
    )
    harness = EvalHarness(cfg)
    checks = harness.score({"expected_contains": ["abc"], "scorers": ["no_tool_error"]}, "abc", [])
    assert checks["contains:abc"]
    assert checks["no_tool_error"]
