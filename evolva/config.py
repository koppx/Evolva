from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class AgentConfig:
    root: Path = ROOT
    workspace: Path = ROOT / "evolva" / "workspace"
    memory_file: Path = ROOT / "evolva" / "memory" / "memory.jsonl"
    skills_dir: Path = ROOT / "evolva" / "skills"
    context_file: Path = ROOT / "evolva" / "context" / "context.json"
    todo_file: Path = ROOT / "evolva" / "todo" / "todos.json"
    traces_dir: Path = ROOT / "evolva" / "traces"
    eval_results_dir: Path = ROOT / "evolva" / "eval_results"
    dreams_dir: Path = ROOT / "evolva" / "dreams"
    workflows_dir: Path = ROOT / "evolva" / "workflows"
    mcp_config_file: Path = ROOT / "evolva" / "mcp" / "servers.json"
    repo_index_file: Path = ROOT / "evolva" / "repo_index" / "index.json"
    sandbox_allow_shell: bool = os.getenv("EVOLVA_SANDBOX_ALLOW_SHELL", "1") != "0"
    tracing_enabled: bool = os.getenv("EVOLVA_TRACING", "1") != "0"
    model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    api_key: str | None = os.getenv("OPENAI_API_KEY")
    base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    max_steps: int = int(os.getenv("EVOLVA_MAX_STEPS", "8"))
    auto_evolve: bool = os.getenv("EVOLVA_AUTO_EVOLVE", "1") != "0"

    def ensure_dirs(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.context_file.parent.mkdir(parents=True, exist_ok=True)
        self.todo_file.parent.mkdir(parents=True, exist_ok=True)
        self.traces_dir.mkdir(parents=True, exist_ok=True)
        self.eval_results_dir.mkdir(parents=True, exist_ok=True)
        self.dreams_dir.mkdir(parents=True, exist_ok=True)
        self.workflows_dir.mkdir(parents=True, exist_ok=True)
        self.mcp_config_file.parent.mkdir(parents=True, exist_ok=True)
        self.repo_index_file.parent.mkdir(parents=True, exist_ok=True)
