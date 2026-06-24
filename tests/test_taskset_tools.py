from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path

from evolva.cli import main
from evolva.config import AgentConfig
from evolva.eval.taskset import build_taskset_prompt, taskset_smoke_report, render_taskset_smoke_report, run_taskset_sample
from evolva.tools.taskset import classify_taskset_task, file_to_text, taskset_context, taskset_tool_health, normalize_answer, ocr_image, resolve_attachment, spreadsheet_describe, video_probe, web_search_pro


def _write_metadata(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = ["task_id", "Question", "Level", "Final answer", "file_name", "file_path", "Annotator Metadata"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_normalize_classify_and_resolve_attachment(tmp_path: Path):
    attachment = tmp_path / "note.txt"
    attachment.write_text("hello", encoding="utf-8")

    assert normalize_answer("  Hello!\n") == "hello"
    cls = classify_taskset_task("Count rows in this spreadsheet", "data.csv")
    assert cls["status"] == "native_or_likely"
    assert {"calc", "table"}.issubset(cls["categories"])

    media = classify_taskset_task("What is said in the audio?", "clip.mp3")
    assert media["status"] == "needs_external_media_tool"
    assert "audio" in media["categories"]

    resolved = resolve_attachment("1", "note.txt", tmp_path)
    assert resolved["exists"]
    assert resolved["path"].endswith("note.txt")


def test_file_to_text_csv_docx_and_spreadsheet(tmp_path: Path):
    text = tmp_path / "note.txt"
    text.write_text("hello world", encoding="utf-8")
    assert file_to_text(text).output == "hello world"

    csv_path = tmp_path / "table.csv"
    csv_path.write_text("a,b\n1,2\n", encoding="utf-8")
    csv_result = spreadsheet_describe(csv_path)
    assert csv_result.ok
    assert "a\tb" in csv_result.output

    docx = tmp_path / "sample.docx"
    with zipfile.ZipFile(docx, "w") as zf:
        zf.writestr("word/document.xml", "<w:document xmlns:w='x'><w:body><w:p><w:r><w:t>Doc text</w:t></w:r></w:p></w:body></w:document>")
    docx_result = file_to_text(docx)
    assert docx_result.ok
    assert "Doc text" in docx_result.output


def test_taskset_smoke_report_and_task_context(tmp_path: Path):
    attachments = tmp_path / "attachments"
    attachments.mkdir()
    (attachments / "note.txt").write_text("attachment text", encoding="utf-8")
    metadata = tmp_path / "metadata.csv"
    _write_metadata(
        metadata,
        [
            {"task_id": "1", "Question": "Read the attachment", "Level": "1", "Final answer": "attachment text", "file_name": "note.txt", "file_path": "", "Annotator Metadata": ""},
            {"task_id": "2", "Question": "Search the web", "Level": "2", "Final answer": "x", "file_name": "", "file_path": "", "Annotator Metadata": ""},
        ],
    )

    report = taskset_smoke_report(metadata, attachments)
    assert report.total_tasks == 2
    assert report.resolved_attachments == 1
    assert report.preview_ok == 1
    rendered = render_taskset_smoke_report(report)
    assert "Task-set smoke report" in rendered

    context = taskset_context(metadata, attachments, task_id="1")
    assert context.ok
    data = json.loads(context.output)
    assert data[0]["preview"]["ok"]
    assert "attachment text" in data[0]["preview"]["output"]


def test_prompt_run_dry_and_cli_smoke(tmp_path: Path, capsys):
    attachments = tmp_path / "attachments"
    attachments.mkdir()
    (attachments / "note.txt").write_text("42", encoding="utf-8")
    metadata = tmp_path / "metadata.csv"
    _write_metadata(
        metadata,
        [{"task_id": "1", "Question": "What number is in the file?", "Level": "1", "Final answer": "42", "file_name": "note.txt", "file_path": "", "Annotator Metadata": ""}],
    )

    prompt = build_taskset_prompt({"task_id": "1", "Level": "1", "Question": "Q", "Final answer": "A"}, attachment_text="T", attachment_path="p", include_answer=True)
    assert "Reference final answer" in prompt

    rows = run_taskset_sample(AgentConfig(root=tmp_path), metadata, attachments, include_answers=True)
    assert rows[0]["normalized_reference_answer"] == "42"
    assert "Attachment preview" in rows[0]["prompt"]

    rc = main(["taskset", "smoke", "--metadata", str(metadata), "--attachments", str(attachments), "--limit", "1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Task-set smoke report" in out


def test_taskset_optional_tool_health_and_media_wrappers(tmp_path: Path, capsys):
    health = taskset_tool_health()
    assert health.ok
    assert "Task-set optional tool health" in health.output
    assert "binaries" in health.data
    assert "browser_search" in health.data
    assert "ocr_image" in health.data["capabilities"]
    assert "xlsx_basic" in health.data["capabilities"]
    assert "xlsx" not in health.data["capabilities"]
    assert health.data["capabilities"]["parquet_table"] == (
        health.data["modules"]["pandas"]["available"]
        and (health.data["modules"]["pyarrow"]["available"] or health.data["modules"]["fastparquet"]["available"])
    )

    image = tmp_path / "fake.png"
    image.write_bytes(b"not really an image")
    ocr = ocr_image(image, max_chars=100)
    assert isinstance(ocr.ok, bool)
    assert ocr.data["path"].endswith("fake.png")

    video = tmp_path / "fake.mp4"
    video.write_bytes(b"not really a video")
    probe = video_probe(video)
    assert isinstance(probe.ok, bool)
    assert probe.data["path"].endswith("fake.mp4")

    rc = main(["taskset", "health"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Task-set optional tool health" in out


def test_web_search_pro_duckduckgo_mock(monkeypatch):
    class FakeResponse:
        headers = {"content-type": "text/html"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *_args):
            return b'<a rel="nofollow" class="result__a" href="https://example.com">Example &amp; Title</a><div class="result__snippet">Snippet</div>'

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: FakeResponse())
    result = web_search_pro("example", provider="duckduckgo", max_results=1)
    assert result.ok
    assert result.data["provider"] == "duckduckgo"
    assert result.data["results"][0]["url"] == "https://example.com"
