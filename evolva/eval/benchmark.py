from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evolva.agent.core import EvolvaAgent
from evolva.config import AgentConfig
from evolva.tools.benchmark import classify_benchmark_task, file_to_text, load_benchmark_metadata, normalize_answer, resolve_attachment


@dataclass
class BenchmarkSmokeReport:
    metadata_csv: str
    attachments_dir: str
    total_tasks: int
    sampled_tasks: int
    level_counts: dict[str, int]
    tasks_with_file: int
    resolved_attachments: int
    missing_attachments: int
    preview_ok: int
    preview_failed: int
    status_counts: dict[str, int]
    category_counts: dict[str, int]
    extension_counts: dict[str, int]
    blockers: dict[str, int]
    samples: list[dict[str, Any]]
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _limited(rows: list[dict[str, str]], limit: int | None) -> list[dict[str, str]]:
    if limit is None or int(limit) <= 0:
        return rows
    return rows[: int(limit)]


def build_benchmark_prompt(row: dict[str, str], attachment_text: str = "", attachment_path: str | None = None, include_answer: bool = False) -> str:
    parts = [
        "You are solving a benchmark task. Provide the final answer only unless reasoning is explicitly requested.",
        f"Task ID: {row.get('task_id', '')}",
        f"Level: {row.get('Level', '')}",
        "Question:",
        row.get("Question", ""),
    ]
    if attachment_path:
        parts.extend(["Attachment path:", attachment_path])
    if attachment_text:
        parts.extend(["Attachment preview:", attachment_text])
    if include_answer and row.get("Final answer"):
        parts.extend(["Reference final answer:", row.get("Final answer", "")])
    return "\n\n".join(parts)


def benchmark_smoke_report(metadata_csv: str | Path, attachments_dir: str | Path, limit: int | None = None, max_chars: int = 4000) -> BenchmarkSmokeReport:
    metadata_path = Path(metadata_csv).expanduser().resolve()
    attachments_path = Path(attachments_dir).expanduser().resolve()
    rows = load_benchmark_metadata(metadata_path)
    sampled = _limited(rows, limit)
    level_counts = Counter(str(row.get("Level", "")) for row in rows)
    status_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    extension_counts: Counter[str] = Counter()
    blockers: Counter[str] = Counter()
    tasks_with_file = 0
    resolved = 0
    missing = 0
    preview_ok = 0
    preview_failed = 0
    samples: list[dict[str, Any]] = []

    for row in sampled:
        file_name = row.get("file_name", "") or ""
        if file_name:
            tasks_with_file += 1
            suffix = Path(file_name).suffix.lower() or "(none)"
            extension_counts[suffix] += 1
        classification = classify_benchmark_task(row.get("Question", ""), file_name, row.get("Annotator Metadata", ""))
        status_counts[classification["status"]] += 1
        category_counts.update(classification["categories"])
        blockers.update(classification["blockers"])
        attachment = resolve_attachment(row.get("task_id", ""), file_name, attachments_path, row.get("file_path", ""))
        preview: dict[str, Any] | None = None
        if file_name:
            if attachment.get("exists"):
                resolved += 1
                result = file_to_text(str(attachment["path"]), max_chars=max_chars)
                if result.ok:
                    preview_ok += 1
                else:
                    preview_failed += 1
                preview = {"ok": result.ok, "kind": result.data.get("kind") if isinstance(result.data, dict) else None, "message": result.output[:500]}
            else:
                missing += 1
        if len(samples) < 20:
            samples.append(
                {
                    "task_id": row.get("task_id"),
                    "level": row.get("Level"),
                    "file_name": file_name,
                    "attachment": attachment,
                    "classification": classification,
                    "preview": preview,
                    "question_preview": (row.get("Question") or "")[:300],
                }
            )

    return BenchmarkSmokeReport(
        metadata_csv=str(metadata_path),
        attachments_dir=str(attachments_path),
        total_tasks=len(rows),
        sampled_tasks=len(sampled),
        level_counts=dict(sorted(level_counts.items())),
        tasks_with_file=tasks_with_file,
        resolved_attachments=resolved,
        missing_attachments=missing,
        preview_ok=preview_ok,
        preview_failed=preview_failed,
        status_counts=dict(sorted(status_counts.items())),
        category_counts=dict(sorted(category_counts.items())),
        extension_counts=dict(sorted(extension_counts.items())),
        blockers=dict(blockers.most_common()),
        samples=samples,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def render_benchmark_smoke_report(report: BenchmarkSmokeReport) -> str:
    lines = [
        "Benchmark smoke report",
        f"- metadata: {report.metadata_csv}",
        f"- attachments: {report.attachments_dir}",
        f"- tasks: {report.total_tasks} total, {report.sampled_tasks} sampled",
        f"- levels: {report.level_counts}",
        f"- attachments: {report.resolved_attachments}/{report.tasks_with_file} resolved, {report.missing_attachments} missing",
        f"- previews: {report.preview_ok} ok, {report.preview_failed} failed",
        f"- statuses: {report.status_counts}",
        f"- categories: {report.category_counts}",
        f"- extensions: {report.extension_counts}",
    ]
    if report.blockers:
        lines.append("- blockers:")
        lines.extend(f"  - {name}: {count}" for name, count in report.blockers.items())
    lines.append("- verdict: Evolva can load and prepare benchmark tasks; full benchmark accuracy still depends on LLM config plus browser/OCR/audio/video tools for blocked categories.")
    return "\n".join(lines)


def write_benchmark_report(report: BenchmarkSmokeReport, output_dir: str | Path) -> Path:
    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"benchmark_smoke_{stamp}.json"
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def run_benchmark_sample(
    config: AgentConfig,
    metadata_csv: str | Path,
    attachments_dir: str | Path,
    *,
    limit: int = 1,
    level: str | None = None,
    run_agent: bool = False,
    include_answers: bool = False,
    max_attachment_chars: int = 8000,
    assume_yes: bool = True,
) -> list[dict[str, Any]]:
    rows = load_benchmark_metadata(metadata_csv)
    if level:
        rows = [row for row in rows if str(row.get("Level")) == str(level)]
    rows = _limited(rows, limit)
    agent = EvolvaAgent(config, assume_yes=assume_yes) if run_agent else None
    outputs: list[dict[str, Any]] = []
    for row in rows:
        attachment = resolve_attachment(row.get("task_id", ""), row.get("file_name", ""), attachments_dir, row.get("file_path", ""))
        attachment_text = ""
        if attachment.get("exists") and attachment.get("path"):
            preview = file_to_text(attachment["path"], max_chars=max_attachment_chars)
            attachment_text = preview.output
        prompt = build_benchmark_prompt(row, attachment_text=attachment_text, attachment_path=attachment.get("path"), include_answer=include_answers)
        item: dict[str, Any] = {"task_id": row.get("task_id"), "level": row.get("Level"), "prompt": prompt, "attachment": attachment}
        if include_answers:
            item["reference_answer"] = row.get("Final answer", "")
            item["normalized_reference_answer"] = normalize_answer(row.get("Final answer", ""))
        if agent is not None:
            result = agent.chat(prompt)
            item.update({"answer": result.answer, "tool_logs": result.tool_logs, "failed_tools": result.failed_tools})
            if include_answers:
                item["normalized_answer"] = normalize_answer(result.answer)
                item["exact_match"] = item["normalized_answer"] == item["normalized_reference_answer"]
        outputs.append(item)
    return outputs
