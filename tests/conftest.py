from __future__ import annotations

import os
from pathlib import Path

import pytest

# Keep unit tests deterministic and offline even if the developer shell has LLM credentials.
os.environ.pop("OPENAI_API_KEY", None)

from evolva.config import AgentConfig


@pytest.fixture
def temp_config(tmp_path: Path) -> AgentConfig:
    base = tmp_path / "evolva"
    return AgentConfig(
        root=tmp_path,
        workspace=base / "workspace",
        memory_file=base / "memory" / "memory.jsonl",
        skills_dir=base / "skills",
        context_file=base / "context" / "context.json",
        todo_file=base / "todo" / "todos.json",
        traces_dir=base / "traces",
        eval_results_dir=base / "eval_results",
        dreams_dir=base / "dreams",
        workflows_dir=base / "workflows",
        mcp_config_file=base / "mcp" / "servers.json",
        repo_index_file=base / "repo_index" / "index.json",
        api_key=None,
    )
