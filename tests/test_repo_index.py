from __future__ import annotations

from pathlib import Path

from evolva.agent.core import EvolvaAgent
from evolva.agent.repo_index import RepoIndex
from evolva.eval.harness import EvalHarness


def test_repo_index_builds_symbol_chunks_and_searches(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "evolution.py").write_text(
        "from pkg.memory import MemoryStore\n\n"
        "class SelfEvolutionEngine:\n"
        "    def evolve(self, feedback: str) -> str:\n"
        "        return f'lesson: {feedback}'\n\n"
        "def helper_function():\n"
        "    return SelfEvolutionEngine\n",
        encoding="utf-8",
    )
    (pkg / "memory.py").write_text("class MemoryStore:\n    pass\n", encoding="utf-8")

    index = RepoIndex(tmp_path, tmp_path / "index.json")
    snapshot = index.build()

    assert snapshot.chunks
    assert snapshot.backend in {"stdlib_symbol_vectors", "tree_sitter_available+stdlib_symbol_vectors"}
    results = index.search("SelfEvolutionEngine evolve", limit=3)
    assert results
    assert results[0].path == "pkg/evolution.py"
    assert results[0].symbol in {"SelfEvolutionEngine", "evolve"}
    assert results[0].score > 0


def test_repo_index_persists_and_loads(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Evolva\n\nTrace Eval Self Evolution\n", encoding="utf-8")
    index = RepoIndex(tmp_path, tmp_path / "repo_index" / "index.json")

    built = index.build()
    loaded = index.load()

    assert loaded is not None
    assert len(loaded.chunks) == len(built.chunks)
    assert index.search("Trace Eval")


def test_repo_index_tools_are_available(temp_config) -> None:
    (temp_config.root / "sample.py").write_text(
        "class RepoIndexer:\n"
        "    def search(self, query):\n"
        "        return query\n",
        encoding="utf-8",
    )
    agent = EvolvaAgent(temp_config, assume_yes=True)

    build = agent._call_tool("repo_index_build", {"max_files": 20})
    search = agent._call_tool("repo_index_search", {"query": "RepoIndexer search", "limit": 2})

    assert build.ok, build.output
    assert "Built repo index" in build.output
    assert search.ok, search.output
    assert "RepoIndexer" in search.output


def test_eval_harness_can_run_tool_tasks(temp_config) -> None:
    (temp_config.root / "sample.py").write_text("class EvalTarget:\n    pass\n", encoding="utf-8")
    harness = EvalHarness(temp_config, assume_yes=True)

    result = harness.run_task(
        {
            "id": "repo_tool_eval",
            "tool": "repo_index_search",
            "args": {"query": "EvalTarget", "limit": 3},
            "expected_contains": ["EvalTarget", "sample.py"],
            "scorers": ["no_tool_error"],
        }
    )

    assert result.passed
    assert result.score == 1.0
