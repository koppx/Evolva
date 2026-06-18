from __future__ import annotations

from evolva.maintenance.optimizer import DailyOptimizer, run_daily_optimization


def test_daily_optimizer_detects_and_applies_safe_fixes(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("pytest-1%20passed\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='evolva'\n", encoding="utf-8")
    (tmp_path / ".DS_Store").write_text("x", encoding="utf-8")

    optimizer = DailyOptimizer(tmp_path)
    monkeypatch.setattr(optimizer, "_pytest_count", lambda: 53)
    monkeypatch.setattr(optimizer, "_scan_test_health", lambda: [])
    report = optimizer.scan(apply=True)

    assert any(item.id == "pytest_badge_drift" and item.fixed for item in report.items)
    assert any(item.id == "runtime_artifacts" and item.fixed for item in report.items)
    assert "pytest-53%20passed" in (tmp_path / "README.md").read_text(encoding="utf-8")
    assert not (tmp_path / ".DS_Store").exists()
    assert "Daily optimization report" in optimizer.render(report)


def test_run_daily_optimization_writes_report(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("ok", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("ok", encoding="utf-8")
    monkeypatch.setattr(DailyOptimizer, "_pytest_count", lambda self: None)
    monkeypatch.setattr(DailyOptimizer, "_scan_test_health", lambda self: [])

    report, path, rendered = run_daily_optimization(tmp_path, apply=False, write=True)
    assert path is not None and path.exists()
    assert report.root == str(tmp_path.resolve())
    assert "Daily optimization report" in rendered
