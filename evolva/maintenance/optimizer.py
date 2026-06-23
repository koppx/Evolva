from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class OptimizationItem:
    id: str
    title: str
    severity: str
    description: str
    recommendation: str
    auto_fixable: bool = False
    fixed: bool = False
    files: list[str] = field(default_factory=list)


@dataclass
class OptimizationReport:
    generated_at: str
    root: str
    items: list[OptimizationItem]
    checks: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DailyOptimizer:
    """Conservative daily project health scan with safe auto-fixes."""

    RUNTIME_DIRS = [
        ".pytest_cache",
        "evolva.egg-info",
        "evolva/__pycache__",
        "evolva/agent/__pycache__",
        "evolva/eval/__pycache__",
        "evolva/tools/__pycache__",
        "evolva/workflow/__pycache__",
        "tests/__pycache__",
    ]
    GENERATED_DIRS = [
        ".evolva",
        "evolva/context",
        "evolva/memory",
        "evolva/todo",
        "evolva/traces",
        "evolva/eval_results",
        "evolva/workspace",
        "evolva/workflows",
    ]
    USER_FACING_FILES = ["README.md", "pyproject.toml"]

    def __init__(self, root: Path):
        self.root = root.resolve()

    def scan(self, *, apply: bool = False) -> OptimizationReport:
        items: list[OptimizationItem] = []
        items.extend(self._scan_runtime_artifacts(apply=apply))
        items.extend(self._scan_badge_drift(apply=apply))
        items.extend(self._scan_generated_state())
        items.extend(self._scan_test_health())
        items.extend(self._scan_public_copy())
        return OptimizationReport(generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), root=str(self.root), items=items, checks={"apply": apply})

    def write_report(self, report: OptimizationReport, *, reports_dir: Path | None = None) -> Path:
        target_dir = reports_dir or self.root / "evolva" / "optimization_reports"
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / ("daily_optimization_" + time.strftime("%Y%m%d_%H%M%S", time.gmtime()) + ".json")
        path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def render(self, report: OptimizationReport) -> str:
        lines = ["Daily optimization report", f"- Generated: {report.generated_at}", f"- Items: {len(report.items)}"]
        if not report.items:
            lines.append("- No optimization items found.")
            return "\n".join(lines)
        for item in report.items:
            mark = "fixed" if item.fixed else "todo"
            auto = "auto" if item.auto_fixable else "manual"
            lines.append(f"- [{item.severity}/{auto}/{mark}] {item.id}: {item.title}")
            lines.append(f"  {item.description}")
            lines.append(f"  Recommendation: {item.recommendation}")
        return "\n".join(lines)

    def _scan_runtime_artifacts(self, *, apply: bool) -> list[OptimizationItem]:
        files = [p for p in self.root.rglob(".DS_Store") if ".git" not in p.parts]
        dirs = [self.root / d for d in self.RUNTIME_DIRS if (self.root / d).exists()]
        if not files and not dirs:
            return []
        item = OptimizationItem(
            id="runtime_artifacts",
            title="Runtime/cache artifacts detected",
            severity="low",
            description="Local cache/build artifacts can make repository scans noisy.",
            recommendation="Keep them ignored and clean them locally before release branches.",
            auto_fixable=True,
            files=[str(p.relative_to(self.root)) for p in files + dirs],
        )
        if apply:
            for path in files:
                self._safe_unlink(path)
            for path in dirs:
                self._safe_rmtree(path)
            item.fixed = True
        return [item]

    def _scan_badge_drift(self, *, apply: bool) -> list[OptimizationItem]:
        readme = self.root / "README.md"
        if not readme.exists():
            return []
        passed = self._pytest_count()
        if passed is None:
            return []
        text = readme.read_text(encoding="utf-8")
        import re

        match = re.search(r"pytest-(\d+)%20passed", text)
        if not match or int(match.group(1)) == passed:
            return []
        item = OptimizationItem(
            id="pytest_badge_drift",
            title="README pytest badge is stale",
            severity="low",
            description=f"README shows {match.group(1)} passed tests, but local pytest reports {passed}.",
            recommendation="Update the README badge so public project status matches test coverage.",
            auto_fixable=True,
            files=["README.md"],
        )
        if apply:
            readme.write_text(re.sub(r"pytest-\d+%20passed", f"pytest-{passed}%20passed", text), encoding="utf-8")
            item.fixed = True
        return [item]

    def _scan_generated_state(self) -> list[OptimizationItem]:
        existing = [d for d in self.GENERATED_DIRS if (self.root / d).exists()]
        if not existing:
            return []
        return [
            OptimizationItem(
                id="runtime_state_present",
                title="Local runtime state exists",
                severity="info",
                description="Runtime state directories are present locally. They are useful for development but should stay ignored.",
                recommendation="Do not commit generated context, memory, traces, eval results, or workspace artifacts unless intentionally publishing examples.",
                auto_fixable=False,
                files=existing,
            )
        ]

    def _scan_test_health(self) -> list[OptimizationItem]:
        result = self._run([self._python(), "-m", "pytest", "-q"], timeout=60)
        if result.returncode == 0:
            return []
        return [
            OptimizationItem(
                id="tests_failing",
                title="Test suite is not green",
                severity="high",
                description=(result.stdout + result.stderr)[-800:],
                recommendation="Fix failing tests before shipping other optimizations.",
                auto_fixable=False,
            )
        ]

    def _scan_public_copy(self) -> list[OptimizationItem]:
        bad_terms = ["deerflow", "deer agent", "面试"]
        findings: list[str] = []
        for rel in self.USER_FACING_FILES:
            path = self.root / rel
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            for term in bad_terms:
                if term in text:
                    findings.append(f"{rel}:{term}")
        if not findings:
            return []
        return [
            OptimizationItem(
                id="public_copy_review",
                title="Public-facing copy contains terms to review",
                severity="medium",
                description=", ".join(findings),
                recommendation="Review public copy and keep product positioning clean and standalone.",
                auto_fixable=False,
                files=self.USER_FACING_FILES,
            )
        ]

    def _pytest_count(self) -> int | None:
        result = self._run([self._python(), "-m", "pytest", "-q"], timeout=60)
        if result.returncode != 0:
            return None
        import re

        match = re.search(r"(\d+) passed", result.stdout + result.stderr)
        return int(match.group(1)) if match else None

    def _python(self) -> str:
        venv_python = self.root / ".venv" / "bin" / "python"
        return str(venv_python) if venv_python.exists() else "python3"

    def _run(self, cmd: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(cmd, cwd=self.root, text=True, capture_output=True, timeout=timeout)
        except Exception as exc:
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr=str(exc))

    def _safe_unlink(self, path: Path) -> None:
        try:
            if self.root in path.resolve().parents and path.name == ".DS_Store":
                path.unlink(missing_ok=True)
        except Exception:
            pass

    def _safe_rmtree(self, path: Path) -> None:
        import shutil

        try:
            resolved = path.resolve()
            if self.root not in resolved.parents:
                return
            if path.name in {"__pycache__", ".pytest_cache", "evolva.egg-info"}:
                shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass


def run_daily_optimization(root: Path, *, apply: bool = False, write: bool = True) -> tuple[OptimizationReport, Path | None, str]:
    optimizer = DailyOptimizer(root)
    report = optimizer.scan(apply=apply)
    path = optimizer.write_report(report) if write else None
    return report, path, optimizer.render(report)
