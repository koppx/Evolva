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
    assert snapshot.files
    assert snapshot.stats["indexed_files"] == 2
    assert snapshot.stats["reused_files"] == 0
    assert index.status()["stale"] is False
    assert snapshot.backend in {"stdlib_symbol_vectors", "tree_sitter_available+stdlib_symbol_vectors"}
    assert index.capabilities()["local_first"] is True
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
    fresh = index.build_if_stale(max_age_seconds=3600)

    assert loaded is not None
    assert len(loaded.chunks) == len(built.chunks)
    assert fresh.built_at == loaded.built_at
    assert index.search("Trace Eval")


def test_repo_index_incremental_reuses_unchanged_files_and_detects_stale(tmp_path: Path) -> None:
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("class FirstSymbol:\n    pass\n", encoding="utf-8")
    second.write_text("class SecondSymbol:\n    pass\n", encoding="utf-8")
    index = RepoIndex(tmp_path, tmp_path / "index.json")

    built = index.build()
    assert built.stats["indexed_files"] == 2
    assert index.status()["stale"] is False

    second.write_text("class SecondSymbol:\n    pass\n\nclass AddedSymbol:\n    pass\n", encoding="utf-8")
    assert index.status()["stale"] is True
    rebuilt = index.build()

    assert rebuilt.stats["indexed_files"] == 1
    assert rebuilt.stats["reused_files"] == 1
    assert any(chunk.symbol == "FirstSymbol" for chunk in rebuilt.chunks)
    assert any(chunk.symbol == "AddedSymbol" for chunk in rebuilt.chunks)


def test_repo_index_records_skipped_files(tmp_path: Path) -> None:
    (tmp_path / "small.py").write_text("class Small:\n    pass\n", encoding="utf-8")
    (tmp_path / "large.py").write_text("x = '" + ("a" * 100) + "'\n", encoding="utf-8")
    (tmp_path / "image.bin").write_bytes(b"\x00\x01")
    index = RepoIndex(tmp_path, tmp_path / "index.json", max_file_bytes=40)

    snapshot = index.build(max_files=1)

    assert snapshot.stats["files"] == 1
    assert snapshot.skipped["too_large"] >= 1
    assert snapshot.skipped["unsupported_extension"] >= 1
    status = index.status(max_files=1)
    assert status["skipped"]["too_large"] >= 1


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
    status = agent._call_tool("repo_index_status", {"max_files": 20})

    assert build.ok, build.output
    assert "Built repo index" in build.output
    assert "reused=" in build.output
    assert search.ok, search.output
    assert "RepoIndexer" in search.output
    assert status.ok, status.output
    assert "stale: False" in status.output


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
