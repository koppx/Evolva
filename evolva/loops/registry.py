from __future__ import annotations

import json
from pathlib import Path

from evolva.loops.spec import LoopSpec


BUILTIN_LOOP_SPECS: dict[str, dict] = {
    "dream-loop": {
        "id": "dream-loop",
        "name": "Dream Evidence Promotion Loop",
        "description": "Collect trace/eval/memory evidence, stage Dream candidates, then verify before promotion.",
        "trigger": {"type": "manual"},
        "phases": [
            {"id": "observe", "type": "tool", "tool": "dream_report", "args": {"limit": 20, "apply": False, "verify": False}},
            {"id": "backlog", "type": "dream", "action": "backlog", "depends_on": ["observe"]},
            {"id": "verify", "type": "dream", "action": "verify", "depends_on": ["backlog"], "continue_on_error": True},
        ],
        "gates": [{"after": "observe", "type": "phase_success"}],
        "artifacts": ["trace", "dream_candidate", "memory", "skill"],
    },
    "repo-improvement-loop": {
        "id": "repo-improvement-loop",
        "name": "Repository Improvement Loop",
        "description": "Scan the local codebase, inspect evolution surfaces, and create evidence for a small follow-up improvement.",
        "trigger": {"type": "manual"},
        "phases": [
            {"id": "index", "type": "tool", "tool": "repo_index_build", "args": {"max_files": 1000}},
            {"id": "scan", "type": "tool", "tool": "repo_index_search", "args": {"query": "TODO FIXME demo weak test", "limit": 8}, "depends_on": ["index"]},
            {"id": "audit", "type": "dream", "action": "run", "args": {"limit": 20}, "depends_on": ["scan"]},
        ],
        "gates": [{"after": "index", "type": "phase_success"}],
        "artifacts": ["repo_index", "trace", "dream_candidate"],
    },
    "eval-regression-loop": {
        "id": "eval-regression-loop",
        "name": "Eval Regression Loop",
        "description": "Run the smoke eval gate and feed the resulting evidence into Dream.",
        "trigger": {"type": "manual"},
        "command_allowlist": [".venv/bin/python -m pytest -q tests/test_dream.py"],
        "phases": [
            {"id": "eval", "type": "tool", "tool": "shell", "args": {"command": ".venv/bin/python -m pytest -q tests/test_dream.py", "timeout": 120}},
            {"id": "dream", "type": "dream", "action": "run", "depends_on": ["eval"], "continue_on_error": True},
        ],
        "gates": [{"after": "eval", "type": "phase_success"}],
        "artifacts": ["eval_result", "trace", "dream_candidate"],
    },
    "release-readiness-loop": {
        "id": "release-readiness-loop",
        "name": "Release Readiness Loop",
        "description": "Check tests, CLI help, and README surfaces before a release.",
        "trigger": {"type": "manual"},
        "command_allowlist": [".venv/bin/evolva --help", ".venv/bin/python -m pytest -q"],
        "phases": [
            {"id": "help", "type": "tool", "tool": "shell", "args": {"command": ".venv/bin/evolva --help", "timeout": 30}},
            {"id": "tests", "type": "tool", "tool": "shell", "args": {"command": ".venv/bin/python -m pytest -q", "timeout": 180}, "depends_on": ["help"]},
            {"id": "dream", "type": "dream", "action": "run", "depends_on": ["tests"], "continue_on_error": True},
        ],
        "gates": [{"after": "help", "type": "phase_success"}, {"after": "tests", "type": "phase_success"}],
        "artifacts": ["trace", "eval_result", "dream_candidate"],
    },
}


class LoopRegistry:
    """Resolve built-in and workspace loop specs by ID or JSON path."""

    def __init__(self, loops_dir: Path | None = None):
        self.loops_dir = loops_dir
        if loops_dir is not None:
            loops_dir.mkdir(parents=True, exist_ok=True)

    def list_specs(self) -> list[LoopSpec]:
        specs = [LoopSpec.from_dict(data) for data in BUILTIN_LOOP_SPECS.values()]
        if self.loops_dir is not None:
            for path in sorted(self.loops_dir.glob("*.json")):
                try:
                    spec = LoopSpec.from_file(path)
                except Exception:
                    continue
                if spec.id not in {item.id for item in specs}:
                    specs.append(spec)
        return specs

    def load(self, identifier: str) -> LoopSpec:
        if identifier in BUILTIN_LOOP_SPECS:
            return LoopSpec.from_dict(BUILTIN_LOOP_SPECS[identifier])
        path = Path(identifier)
        if not path.exists() and self.loops_dir is not None:
            path = self.loops_dir / identifier
        if not path.exists() and path.suffix != ".json" and self.loops_dir is not None:
            path = self.loops_dir / f"{identifier}.json"
        if path.exists():
            return LoopSpec.from_file(path)
        known = ", ".join(sorted(BUILTIN_LOOP_SPECS))
        raise KeyError(f"Unknown loop `{identifier}`. Built-ins: {known}")

    def write_template(self, spec: LoopSpec) -> Path:
        if self.loops_dir is None:
            raise ValueError("loops_dir is not configured")
        path = self.loops_dir / f"{spec.id}.json"
        path.write_text(json.dumps(spec.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path
