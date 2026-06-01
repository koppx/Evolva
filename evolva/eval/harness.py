from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from evolva.agent.core import EvolvaAgent
from evolva.config import AgentConfig


@dataclass
class EvalResult:
    id: str
    passed: bool
    score: float
    checks: dict[str, bool]
    answer: str
    tool_logs: list[str] = field(default_factory=list)
    duration_ms: int = 0


class EvalHarness:
    """Small stdlib eval harness for agent regression tests and demos."""

    def __init__(self, config: AgentConfig | None = None, *, assume_yes: bool = True):
        self.config = config or AgentConfig()
        self.agent = EvolvaAgent(self.config, assume_yes=assume_yes)
        self.results_dir = self.config.eval_results_dir
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def run_file(self, tasks_path: Path) -> list[EvalResult]:
        results: list[EvalResult] = []
        with tasks_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                task = json.loads(line)
                results.append(self.run_task(task))
        self.write_report(results, tasks_path.stem)
        return results

    def run_task(self, task: dict[str, Any]) -> EvalResult:
        started = time.time()
        result = self.agent.chat(str(task["input"]))
        checks = self.score(task, result.answer, result.tool_logs)
        passed = all(checks.values()) if checks else bool(result.answer.strip())
        score = sum(1 for ok in checks.values() if ok) / max(1, len(checks))
        return EvalResult(
            id=str(task.get("id", "unnamed")),
            passed=passed,
            score=score,
            checks=checks,
            answer=result.answer,
            tool_logs=result.tool_logs,
            duration_ms=int((time.time() - started) * 1000),
        )

    def score(self, task: dict[str, Any], answer: str, tool_logs: list[str]) -> dict[str, bool]:
        text = answer + "\n" + "\n".join(tool_logs)
        checks: dict[str, bool] = {}
        for expected in task.get("expected_contains", []):
            checks[f"contains:{expected}"] = str(expected) in text
        for artifact in task.get("expected_artifacts", []):
            path = (self.config.root / str(artifact)).resolve()
            checks[f"artifact_exists:{artifact}"] = path.exists()
        if "no_tool_error" in task.get("scorers", []):
            checks["no_tool_error"] = "ok=False" not in text and "Tool error" not in text
        return checks

    def write_report(self, results: list[EvalResult], name: str = "eval") -> Path:
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = self.results_dir / f"{name}_{ts}.json"
        payload = {
            "summary": self.summary(results),
            "results": [asdict(r) for r in results],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def summary(self, results: list[EvalResult]) -> dict[str, Any]:
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        avg_score = sum(r.score for r in results) / max(1, total)
        return {"total": total, "passed": passed, "failed": total - passed, "avg_score": avg_score}


def render_results(results: list[EvalResult]) -> str:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    lines = [f"Eval results: {passed}/{total} passed"]
    for result in results:
        mark = "PASS" if result.passed else "FAIL"
        lines.append(f"- {mark} {result.id} score={result.score:.2f} duration={result.duration_ms}ms checks={result.checks}")
    return "\n".join(lines)
