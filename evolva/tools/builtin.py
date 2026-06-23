from __future__ import annotations

import json
from pathlib import Path
from dataclasses import asdict
from typing import Callable

from evolva.agent.capabilities import DEFAULT_TOOL_CAPABILITIES
from evolva.agent.context import ContextStore
from evolva.agent.memory import MemoryStore
from evolva.agent.mcp import MCPManager, render_mcp_result
from evolva.agent.mcp_presets import get_mcp_preset, list_mcp_presets
from evolva.agent.multi_agent import MultiAgentCoordinator
from evolva.agent.policy import PolicyEngine
from evolva.agent.repo_index import RepoIndex
from evolva.agent.sandbox import Sandbox
from evolva.agent.skills import SkillStore
from evolva.agent.todo import TodoStore
from evolva.tools.base import Tool, ToolRegistry, ToolResult
from evolva.tools import benchmark as benchmark_tools


def build_registry(
    sandbox: Sandbox,
    memory: MemoryStore,
    skills: SkillStore,
    context: ContextStore,
    todos: TodoStore,
    coordinator: MultiAgentCoordinator | None = None,
    policy: PolicyEngine | None = None,
    mcp: MCPManager | None = None,
    repo_index_file: Path | None = None,
    dream_runner: Callable[..., tuple[str, dict]] | None = None,
) -> ToolRegistry:
    reg = ToolRegistry()

    def caps(tool_name: str) -> list[str]:
        return [cap.value for cap in DEFAULT_TOOL_CAPABILITIES.get(tool_name, [])]

    def list_files(path: str = ".", max_entries: int = 200) -> ToolResult:
        p = sandbox.resolve(path)
        if not p.exists():
            return ToolResult(False, f"Not found: {p}")
        rows = []
        entries = list(p.iterdir()) if p.is_dir() else [p]
        for item in sorted(entries)[:max_entries]:
            kind = "dir" if item.is_dir() else "file"
            rows.append(f"{kind}\t{item.relative_to(sandbox.root)}")
        return ToolResult(True, "\n".join(rows), rows)

    def read_file(path: str, max_chars: int = 20000) -> ToolResult:
        p = sandbox.resolve(path)
        if not p.exists() or not p.is_file():
            return ToolResult(False, f"File not found: {p}")
        text = p.read_text(encoding="utf-8", errors="replace")[:max_chars]
        context.add("artifact", f"Read file {p.relative_to(sandbox.root)}", meta={"path": str(p)})
        return ToolResult(True, text, {"path": str(p), "truncated": len(text) >= max_chars})

    def write_file(path: str, content: str, append: bool = False) -> ToolResult:
        try:
            p = sandbox.resolve_write(path)
        except ValueError as exc:
            return ToolResult(False, str(exc), {"path": path})
        p.parent.mkdir(parents=True, exist_ok=True)
        if append:
            with p.open("a", encoding="utf-8") as f:
                f.write(content)
        else:
            p.write_text(content, encoding="utf-8")
        rel = p.relative_to(sandbox.root).as_posix()
        context.add("artifact", f"Wrote file {rel}", meta={"path": str(p), "chars": len(content), "append": append})
        return ToolResult(
            True,
            f"Wrote {len(content)} chars to {rel}",
            {
                "artifact": {
                    "path": rel,
                    "absolute_path": str(p),
                    "kind": "file",
                    "chars": len(content),
                    "append": append,
                }
            },
        )

    def shell(command: str, cwd: str = ".", timeout: int = 30) -> ToolResult:
        result = sandbox.run_shell(command, cwd=cwd, timeout=timeout)
        context.add("artifact", f"Shell `{command}` ok={result.ok}\n{result.output[:1000]}", meta={"cwd": cwd})
        return result

    def python_exec(code: str, timeout: int = 10) -> ToolResult:
        result = sandbox.run_python(code, timeout=timeout)
        context.add("artifact", f"Python exec ok={result.ok}\n{result.output[:1000]}")
        return result

    def web_search(query: str, max_results: int = 5) -> ToolResult:
        result = benchmark_tools.web_search_pro(query, provider="auto", max_results=max_results)
        context.add("artifact", f"Web search: {query} ok={result.ok}", meta=result.data if isinstance(result.data, dict) else {})
        return result

    def web_search_pro(query: str, provider: str = "auto", max_results: int = 5, timeout: int = 15) -> ToolResult:
        result = benchmark_tools.web_search_pro(query, provider=provider, max_results=max_results, timeout=timeout)
        context.add("artifact", f"Web search provider={provider}: {query} ok={result.ok}", meta=result.data if isinstance(result.data, dict) else {})
        return result

    def web_fetch(url: str, max_chars: int = 20000, timeout: int = 20) -> ToolResult:
        result = benchmark_tools.web_fetch(url, max_chars=max_chars, timeout=timeout)
        context.add("artifact", f"Web fetch: {url} ok={result.ok}", meta=result.data if isinstance(result.data, dict) else {"url": url})
        return result

    def file_to_text(path: str, max_chars: int = 20000, max_rows: int = 20) -> ToolResult:
        try:
            p = sandbox.resolve(path)
        except ValueError as exc:
            return ToolResult(False, str(exc), {"path": path})
        result = benchmark_tools.file_to_text(p, max_chars=max_chars, max_rows=max_rows)
        context.add("artifact", f"File preview: {p} ok={result.ok}", meta=result.data if isinstance(result.data, dict) else {"path": str(p)})
        return result

    def spreadsheet_describe(path: str, max_rows: int = 20, max_chars: int = 20000) -> ToolResult:
        try:
            p = sandbox.resolve(path)
        except ValueError as exc:
            return ToolResult(False, str(exc), {"path": path})
        result = benchmark_tools.spreadsheet_describe(p, max_rows=max_rows, max_chars=max_chars)
        context.add("artifact", f"Spreadsheet preview: {p} ok={result.ok}", meta=result.data if isinstance(result.data, dict) else {"path": str(p)})
        return result

    def normalize_answer(answer: str) -> ToolResult:
        normalized = benchmark_tools.normalize_answer(answer)
        return ToolResult(True, normalized, {"answer": answer, "normalized": normalized})

    def benchmark_task_context(metadata_csv: str, attachments_dir: str, task_id: str = "", limit: int = 5, max_chars: int = 12000) -> ToolResult:
        try:
            metadata_path = sandbox.resolve(metadata_csv)
            attachments_path = sandbox.resolve(attachments_dir)
        except ValueError as exc:
            return ToolResult(False, str(exc), {"metadata_csv": metadata_csv, "attachments_dir": attachments_dir})
        return benchmark_tools.benchmark_task_context(metadata_path, attachments_path, task_id=task_id, limit=limit, max_chars=max_chars)

    def benchmark_smoke_check(metadata_csv: str, attachments_dir: str, limit: int = 20, max_chars: int = 4000) -> ToolResult:
        try:
            metadata_path = sandbox.resolve(metadata_csv)
            attachments_path = sandbox.resolve(attachments_dir)
        except ValueError as exc:
            return ToolResult(False, str(exc), {"metadata_csv": metadata_csv, "attachments_dir": attachments_dir})
        from evolva.eval.benchmark import benchmark_smoke_report, render_benchmark_smoke_report

        report = benchmark_smoke_report(metadata_path, attachments_path, limit=limit, max_chars=max_chars)
        return ToolResult(True, render_benchmark_smoke_report(report), report.to_dict())

    def benchmark_tool_health() -> ToolResult:
        result = benchmark_tools.benchmark_tool_health(mcp.config_file if mcp is not None else None)
        context.add("artifact", "Benchmark optional tool health checked", meta=result.data if isinstance(result.data, dict) else {})
        return result

    def ocr_image(path: str, language: str = "eng", max_chars: int = 20000, timeout: int = 60) -> ToolResult:
        try:
            p = sandbox.resolve(path)
        except ValueError as exc:
            return ToolResult(False, str(exc), {"path": path})
        result = benchmark_tools.ocr_image(p, language=language, max_chars=max_chars, timeout=timeout)
        context.add("artifact", f"OCR image: {p} ok={result.ok}", meta=result.data if isinstance(result.data, dict) else {"path": str(p)})
        return result

    def audio_transcribe(path: str, model: str = "base", language: str = "", max_chars: int = 20000, timeout: int = 600) -> ToolResult:
        try:
            p = sandbox.resolve(path)
        except ValueError as exc:
            return ToolResult(False, str(exc), {"path": path})
        result = benchmark_tools.audio_transcribe(p, model=model, language=language, max_chars=max_chars, timeout=timeout)
        context.add("artifact", f"Audio/video transcription: {p} ok={result.ok}", meta=result.data if isinstance(result.data, dict) else {"path": str(p)})
        return result

    def video_probe(path: str, timeout: int = 30) -> ToolResult:
        try:
            p = sandbox.resolve(path)
        except ValueError as exc:
            return ToolResult(False, str(exc), {"path": path})
        result = benchmark_tools.video_probe(p, timeout=timeout)
        context.add("artifact", f"Video probe: {p} ok={result.ok}", meta=result.data if isinstance(result.data, dict) else {"path": str(p)})
        return result

    def video_extract_frames(path: str, output_dir: str, every_seconds: float = 10.0, max_frames: int = 12, timeout: int = 120) -> ToolResult:
        try:
            p = sandbox.resolve(path)
            out = sandbox.resolve_write(output_dir)
        except ValueError as exc:
            return ToolResult(False, str(exc), {"path": path, "output_dir": output_dir})
        result = benchmark_tools.video_extract_frames(p, out, every_seconds=every_seconds, max_frames=max_frames, timeout=timeout)
        context.add("artifact", f"Video frame extraction: {p} ok={result.ok}", meta=result.data if isinstance(result.data, dict) else {"path": str(p), "output_dir": str(out)})
        return result

    def pdf_extract(path: str, max_chars: int = 20000, timeout: int = 60) -> ToolResult:
        try:
            p = sandbox.resolve(path)
        except ValueError as exc:
            return ToolResult(False, str(exc), {"path": path})
        result = benchmark_tools.pdf_extract_external(p, max_chars=max_chars, timeout=timeout)
        context.add("artifact", f"PDF extraction: {p} ok={result.ok}", meta=result.data if isinstance(result.data, dict) else {"path": str(p)})
        return result

    def yt_dlp_info(url: str, max_chars: int = 30000, timeout: int = 120) -> ToolResult:
        result = benchmark_tools.yt_dlp_info(url, max_chars=max_chars, timeout=timeout)
        context.add("artifact", f"yt-dlp info: {url} ok={result.ok}", meta=result.data if isinstance(result.data, dict) else {"url": url})
        return result

    def remember(kind: str, content: str, confidence: float = 0.7, status: str = "active", evidence: list[str] | None = None) -> ToolResult:
        item = memory.add(kind, content, confidence=confidence, source="agent", status=status, evidence=list(evidence or []))
        return ToolResult(True, f"Remembered [{item.kind}/{item.confidence:.1f}/{item.status}] {item.content}", asdict(item))

    def recall(query: str = "") -> ToolResult:
        return ToolResult(True, memory.context(query))

    def memory_status(item_id: str, status: str, reason: str = "manual governance") -> ToolResult:
        changed = memory.update_status(item_id, status, reason=reason)
        if not changed:
            return ToolResult(False, f"Memory item `{item_id}` was not found")
        return ToolResult(True, f"Memory item `{item_id}` marked {status}", {"id": item_id, "status": status, "reason": reason})

    def memory_audit() -> ToolResult:
        audit = memory.audit()
        lines = ["Memory audit", *[f"- {key}: {value}" for key, value in sorted(audit.items())]]
        return ToolResult(True, "\n".join(lines), audit)

    def list_skills() -> ToolResult:
        names = [f"{s.name} [{(s.metadata or {}).get('status', 'active')}]" for s in skills.list()]
        return ToolResult(True, "\n".join(names), names)

    def save_skill(name: str, content: str, status: str = "active", triggers: list[str] | None = None, source: str = "agent") -> ToolResult:
        metadata = {"status": status, "source": source}
        if triggers:
            metadata["triggers"] = list(triggers)
        path = skills.upsert(name, content, metadata=metadata)
        context.add("artifact", f"Saved skill {path.name}", meta={"path": str(path)})
        return ToolResult(True, f"Saved skill: {path.name}")

    def skill_status(name: str, status: str, reason: str = "manual governance") -> ToolResult:
        changed = skills.set_status(name, status, reason=reason)
        if not changed:
            return ToolResult(False, f"Skill `{name}` was not found")
        return ToolResult(True, f"Skill `{name}` marked {status}", {"name": name, "status": status, "reason": reason})

    def skill_audit() -> ToolResult:
        audit = skills.audit()
        lines = ["Skill audit", *[f"- {key}: {value}" for key, value in sorted(audit.items())]]
        return ToolResult(True, "\n".join(lines), audit)

    def context_add(kind: str, content: str, role: str = "agent") -> ToolResult:
        item = context.add(kind, content, role=role)
        return ToolResult(True, f"Added context [{item.kind}/{item.role}] {item.content[:200]}")

    def context_view(query: str = "", limit: int = 12) -> ToolResult:
        return ToolResult(True, context.render(query=query, limit=limit))

    def context_compact(title: str = "Conversation summary", limit: int = 30) -> ToolResult:
        item = context.compact(title=title, limit=limit)
        return ToolResult(True, f"Compacted context: {item.content[:1000]}")

    def todo_add(title: str, detail: str = "", owner: str = "Evolva") -> ToolResult:
        item = todos.add(title, detail=detail, owner=owner)
        return ToolResult(True, f"Added todo #{item.id}: {item.title}", item)

    def todo_list(include_done: bool = True) -> ToolResult:
        return ToolResult(True, todos.render(include_done=include_done))

    def todo_update(todo_id: int, status: str | None = None, title: str | None = None, detail: str | None = None, owner: str | None = None) -> ToolResult:
        item = todos.update(int(todo_id), status=status, title=title, detail=detail, owner=owner)
        return ToolResult(True, f"Updated todo #{item.id}: [{item.status}] {item.title}", item)

    def todo_clear(include_done: bool = False) -> ToolResult:
        count = todos.clear(include_done=include_done)
        return ToolResult(True, f"Cleared {count} todos")

    def sandbox_info() -> ToolResult:
        return ToolResult(True, sandbox.describe())

    def policy_info() -> ToolResult:
        if policy is None:
            return ToolResult(False, "Policy engine is not configured")
        return policy.as_tool_result()

    def policy_check(tool_name: str, args: dict | None = None) -> ToolResult:
        if policy is None:
            return ToolResult(False, "Policy engine is not configured")
        decision = policy.check_tool(tool_name, args or {})
        return ToolResult(True, json.dumps(decision.to_dict(), ensure_ascii=False, indent=2), decision.to_dict())

    def repo_index_build(max_files: int = 1000) -> ToolResult:
        index = RepoIndex(sandbox.root, repo_index_file)
        snapshot = index.build(max_files=int(max_files))
        stats = snapshot.stats
        output = f"Built repo index: {len(snapshot.chunks)} chunks, {stats.get('files', 0)} files, reused={stats.get('reused_files', 0)} backend={snapshot.backend}"
        context.add("artifact", output, meta={"index_file": str(index.index_file), "chunks": len(snapshot.chunks), "stats": stats, "skipped": snapshot.skipped})
        return ToolResult(True, output, asdict(snapshot))

    def repo_index_search(query: str, limit: int = 8) -> ToolResult:
        index = RepoIndex(sandbox.root, repo_index_file)
        rows = index.search(query, limit=int(limit))
        lines = []
        for row in rows:
            excerpt = " ".join(row.text.strip().split())[:240]
            lines.append(f"- {row.path}:{row.start_line}-{row.end_line} {row.kind} {row.symbol} score={row.score:.3f}\n  {excerpt}")
        output = "\n".join(lines) or "No repo index matches"
        context.add("artifact", f"Repo index search `{query}` returned {len(rows)} chunks", meta={"query": query, "limit": limit})
        return ToolResult(True, output, [asdict(row) for row in rows])

    def repo_index_status(max_files: int = 1000) -> ToolResult:
        index = RepoIndex(sandbox.root, repo_index_file)
        status = index.status(max_files=int(max_files))
        if not status.get("exists"):
            return ToolResult(True, f"Repo index missing: {status.get('index_file')}", status)
        stats = status.get("stats") if isinstance(status.get("stats"), dict) else {}
        skipped = status.get("skipped") if isinstance(status.get("skipped"), dict) else {}
        lines = [
            "Repo index status",
            f"- index_file: {status.get('index_file')}",
            f"- backend: {status.get('backend')}",
            f"- stale: {status.get('stale')}",
            f"- age_seconds: {status.get('age_seconds')}",
            f"- chunks: {status.get('chunks')}",
            f"- files: {status.get('files')}",
            f"- indexed_files: {stats.get('indexed_files', 0)}",
            f"- reused_files: {stats.get('reused_files', 0)}",
            f"- skipped_files: {stats.get('skipped_files', 0)}",
        ]
        for key, value in sorted(skipped.items()):
            lines.append(f"- skipped.{key}: {value}")
        return ToolResult(True, "\n".join(lines), status)

    def mcp_servers() -> ToolResult:
        if mcp is None:
            return ToolResult(False, "MCP manager is not configured")
        names = mcp.list_servers()
        return ToolResult(True, "\n".join(names) or "No MCP servers configured", names)

    def mcp_presets() -> ToolResult:
        rows = list_mcp_presets()
        lines = [f"- {item['name']}: {item['description']} ({item['command']} {' '.join(item['args'])})" for item in rows]
        return ToolResult(True, "\n".join(lines), rows)

    def mcp_add_server(
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict | None = None,
        cwd: str | None = None,
        request_timeout: int = 30,
        max_message_bytes: int = 2_000_000,
    ) -> ToolResult:
        if mcp is None:
            return ToolResult(False, "MCP manager is not configured")
        config = mcp.add_server(name, command, list(args or []), env=dict(env or {}), cwd=cwd, request_timeout=int(request_timeout), max_message_bytes=int(max_message_bytes))
        output = f"Added MCP server `{config.name}`: {config.command} {' '.join(config.args)}".strip()
        context.add("artifact", output, meta={"server": config.name, "config_file": str(mcp.config_file)})
        return ToolResult(
            True,
            output,
            {
                "name": config.name,
                "command": config.command,
                "args": config.args,
                "config_file": str(mcp.config_file),
                "request_timeout": config.request_timeout,
                "max_message_bytes": config.max_message_bytes,
            },
        )

    def mcp_add_preset(preset: str, name: str = "", env: dict | None = None) -> ToolResult:
        if mcp is None:
            return ToolResult(False, "MCP manager is not configured")
        try:
            recipe = get_mcp_preset(preset)
        except KeyError as exc:
            return ToolResult(False, str(exc))
        cfg = recipe.to_server_config(env_overrides={str(k): str(v) for k, v in dict(env or {}).items()}, name=name or recipe.name)
        config = mcp.add_server(
            cfg["name"],
            cfg["command"],
            cfg["args"],
            env=cfg["env"],
            request_timeout=cfg["request_timeout"],
            max_message_bytes=cfg["max_message_bytes"],
        )
        output = f"Added MCP preset `{recipe.name}` as `{config.name}`: {config.command} {' '.join(config.args)}".strip()
        if recipe.install_hint:
            output += f"\nHint: {recipe.install_hint}"
        context.add("artifact", output, meta={"server": config.name, "preset": recipe.name, "config_file": str(mcp.config_file)})
        return ToolResult(True, output, {"name": config.name, "preset": recipe.name, "command": config.command, "args": config.args, "config_file": str(mcp.config_file), "env_keys": sorted(config.env)})

    def mcp_remove_server(name: str) -> ToolResult:
        if mcp is None:
            return ToolResult(False, "MCP manager is not configured")
        existed = mcp.remove_server(name)
        output = f"Removed MCP server `{name}`" if existed else f"MCP server `{name}` was not configured"
        context.add("artifact", output, meta={"server": name, "config_file": str(mcp.config_file)})
        return ToolResult(True, output, {"name": name, "removed": existed, "config_file": str(mcp.config_file)})

    def mcp_tools(server: str = "") -> ToolResult:
        if mcp is None:
            return ToolResult(False, "MCP manager is not configured")
        rows = mcp.list_tools(server or None)
        lines = []
        for item in rows:
            lines.append(f"- {item.get('server')}/{item.get('name')}: {item.get('description', '')}")
        return ToolResult(True, "\n".join(lines) or "No MCP tools", rows)

    def mcp_health(server: str = "", refresh: bool = False) -> ToolResult:
        if mcp is None:
            return ToolResult(False, "MCP manager is not configured")
        rows = mcp.health(server or None, refresh=bool(refresh))
        lines = []
        for item in rows:
            detail = f"{item.get('tool_count', 0)} tools"
            if item.get("cached"):
                detail += ", cache"
            if item.get("error"):
                detail += f", error={item.get('error')}"
            lines.append(f"- {item.get('server')}: {item.get('status')} ({detail})")
        ok = all(item.get("status") in {"ok", "cached", "degraded"} for item in rows)
        return ToolResult(ok, "\n".join(lines) or "No MCP servers configured", {"health": rows})

    def mcp_call(server: str, tool: str, arguments: dict | None = None) -> ToolResult:
        if mcp is None:
            return ToolResult(False, "MCP manager is not configured")
        result = mcp.call_tool(server, tool, arguments or {})
        output = render_mcp_result(result)
        context.add("artifact", f"MCP {server}/{tool}\n{output[:1000]}", meta={"server": server, "tool": tool})
        return ToolResult(not bool(result.get("isError")), output, result)

    def delegate_agent(role: str, task: str, context_text: str = "") -> ToolResult:
        if coordinator is None:
            return ToolResult(False, "Multi-agent coordinator is not configured")
        result = coordinator.delegate_report(role, task, context=context_text)
        output = result.output
        context.add("note", f"Sub-agent {role} result for task `{task}`:\n{output}", role=role)
        return ToolResult(result.ok, output, {"delegate": result.__dict__})

    def collaborate(task: str, roles: list[str] | None = None, context_text: str = "") -> ToolResult:
        if coordinator is None:
            return ToolResult(False, "Multi-agent coordinator is not configured")
        report = coordinator.collaborate_report(task, roles=roles, context=context_text)
        output = report.render()
        context.add("note", f"Multi-agent collaboration for `{task}`:\n{output}")
        return ToolResult(report.status in {"completed", "completed_with_fallbacks"}, output, {"multi_agent": report.to_dict()})

    def dream_report(limit: int = 20, apply: bool = False, verify: bool = False) -> ToolResult:
        if dream_runner is None:
            return ToolResult(False, "Dream runner is not configured")
        output, data = dream_runner(int(limit), bool(apply), bool(verify))
        return ToolResult(True, output, data)

    reg.register(Tool("list_files", "List files under the sandbox root", {"path": "str", "max_entries": "int"}, list_files, capabilities=caps("list_files")))
    reg.register(Tool("read_file", "Read a UTF-8 text file under the sandbox root", {"path": "str", "max_chars": "int"}, read_file, capabilities=caps("read_file")))
    reg.register(Tool("write_file", "Write or append a UTF-8 text file under the sandbox root", {"path": "str", "content": "str", "append": "bool"}, write_file, capabilities=caps("write_file")))
    reg.register(Tool("shell", "Run a shell command inside the sandbox", {"command": "str", "cwd": "str", "timeout": "int"}, shell, needs_confirmation=True, capabilities=caps("shell")))
    reg.register(Tool("python_exec", "Run a short Python snippet in a sandboxed subprocess", {"code": "str", "timeout": "int"}, python_exec, needs_confirmation=True, capabilities=caps("python_exec")))
    reg.register(Tool("web_search", "Search the web with configured APIs and DuckDuckGo HTML fallback", {"query": "str", "max_results": "int"}, web_search, capabilities=caps("web_search")))
    reg.register(Tool("web_search_pro", "Search the web using provider=auto|tavily|brave|serpapi|duckduckgo", {"query": "str", "provider": "str", "max_results": "int", "timeout": "int"}, web_search_pro, capabilities=caps("web_search_pro")))
    reg.register(Tool("web_fetch", "Fetch a static HTTP(S) page and return plain text when possible", {"url": "str", "max_chars": "int", "timeout": "int"}, web_fetch, capabilities=caps("web_fetch")))
    reg.register(Tool("file_to_text", "Preview local text from benchmark-style attachments: text, CSV, DOCX, PPTX, XLSX, PDF best-effort, zip, image/media metadata", {"path": "str", "max_chars": "int", "max_rows": "int"}, file_to_text, capabilities=caps("file_to_text")))
    reg.register(Tool("spreadsheet_describe", "Preview spreadsheet/table files including CSV, TSV, XLSX and optional parquet", {"path": "str", "max_rows": "int", "max_chars": "int"}, spreadsheet_describe, capabilities=caps("spreadsheet_describe")))
    reg.register(Tool("normalize_answer", "Normalize a benchmark final answer for lightweight exact matching", {"answer": "str"}, normalize_answer, capabilities=caps("normalize_answer")))
    reg.register(Tool("benchmark_task_context", "Build benchmark task context with resolved local attachment preview", {"metadata_csv": "str", "attachments_dir": "str", "task_id": "str", "limit": "int", "max_chars": "int"}, benchmark_task_context, capabilities=caps("benchmark_task_context")))
    reg.register(Tool("benchmark_smoke_check", "Check whether a benchmark metadata CSV and attachment directory are readable and previewable", {"metadata_csv": "str", "attachments_dir": "str", "limit": "int", "max_chars": "int"}, benchmark_smoke_check, capabilities=caps("benchmark_smoke_check")))
    reg.register(Tool("benchmark_tool_health", "Report optional OCR/PDF/audio/video/web tooling available for higher benchmark coverage", {}, benchmark_tool_health, capabilities=caps("benchmark_tool_health")))
    reg.register(Tool("ocr_image", "OCR a local image with optional pytesseract/Pillow or tesseract CLI", {"path": "str", "language": "str", "max_chars": "int", "timeout": "int"}, ocr_image, needs_confirmation=True, capabilities=caps("ocr_image")))
    reg.register(Tool("audio_transcribe", "Transcribe local audio/video with an installed Whisper CLI", {"path": "str", "model": "str", "language": "str", "max_chars": "int", "timeout": "int"}, audio_transcribe, needs_confirmation=True, capabilities=caps("audio_transcribe")))
    reg.register(Tool("video_probe", "Inspect local video/audio metadata with ffprobe", {"path": "str", "timeout": "int"}, video_probe, needs_confirmation=True, capabilities=caps("video_probe")))
    reg.register(Tool("video_extract_frames", "Extract bounded video frames with ffmpeg into a sandbox-writable output directory", {"path": "str", "output_dir": "str", "every_seconds": "float", "max_frames": "int", "timeout": "int"}, video_extract_frames, needs_confirmation=True, capabilities=caps("video_extract_frames")))
    reg.register(Tool("pdf_extract", "Extract PDF text with optional pypdf/PyPDF2 or pdftotext", {"path": "str", "max_chars": "int", "timeout": "int"}, pdf_extract, needs_confirmation=True, capabilities=caps("pdf_extract")))
    reg.register(Tool("yt_dlp_info", "Fetch media metadata/transcript availability through yt-dlp", {"url": "str", "max_chars": "int", "timeout": "int"}, yt_dlp_info, needs_confirmation=True, capabilities=caps("yt_dlp_info")))
    reg.register(Tool("remember", "Store a governed long-term memory item", {"kind": "str", "content": "str", "confidence": "float", "status": "str", "evidence": "list[str]"}, remember, capabilities=caps("remember")))
    reg.register(Tool("recall", "Search long-term memory", {"query": "str"}, recall, capabilities=caps("recall")))
    reg.register(Tool("memory_status", "Update a memory item's governance status", {"item_id": "str", "status": "str", "reason": "str"}, memory_status, capabilities=caps("memory_status")))
    reg.register(Tool("memory_audit", "Summarize memory governance quality", {}, memory_audit, capabilities=caps("memory_audit")))
    reg.register(Tool("list_skills", "List available skills", {}, list_skills, capabilities=caps("list_skills")))
    reg.register(Tool("save_skill", "Create or update a governed markdown skill", {"name": "str", "content": "str", "status": "str", "triggers": "list[str]", "source": "str"}, save_skill, capabilities=caps("save_skill")))
    reg.register(Tool("skill_status", "Update a skill's governance status", {"name": "str", "status": "str", "reason": "str"}, skill_status, capabilities=caps("skill_status")))
    reg.register(Tool("skill_audit", "Summarize skill governance quality", {}, skill_audit, capabilities=caps("skill_audit")))
    reg.register(Tool("context_add", "Add a note, artifact, summary, decision, or message to persistent context", {"kind": "str", "content": "str", "role": "str"}, context_add, capabilities=caps("context_add")))
    reg.register(Tool("context_view", "View/search persistent context", {"query": "str", "limit": "int"}, context_view, capabilities=caps("context_view")))
    reg.register(Tool("context_compact", "Summarize recent context into a compact summary item", {"title": "str", "limit": "int"}, context_compact, capabilities=caps("context_compact")))
    reg.register(Tool("todo_add", "Add a todo item", {"title": "str", "detail": "str", "owner": "str"}, todo_add, capabilities=caps("todo_add")))
    reg.register(Tool("todo_list", "List todo items", {"include_done": "bool"}, todo_list, capabilities=caps("todo_list")))
    reg.register(Tool("todo_update", "Update a todo item", {"todo_id": "int", "status": "str", "title": "str", "detail": "str", "owner": "str"}, todo_update, capabilities=caps("todo_update")))
    reg.register(Tool("todo_clear", "Clear completed/cancelled todos, or all todos if include_done=true", {"include_done": "bool"}, todo_clear, capabilities=caps("todo_clear")))
    reg.register(Tool("sandbox_info", "Show sandbox root, workspace, and policy", {}, sandbox_info, capabilities=caps("sandbox_info")))
    reg.register(Tool("policy_info", "Show guardrail policy configuration", {}, policy_info, capabilities=caps("policy_info")))
    reg.register(Tool("policy_check", "Preview whether policy allows a tool call", {"tool_name": "str", "args": "dict"}, policy_check, capabilities=caps("policy_check")))
    reg.register(Tool("repo_index_build", "Build a local semantic repository index with symbol chunks", {"max_files": "int"}, repo_index_build, capabilities=caps("repo_index_build")))
    reg.register(Tool("repo_index_search", "Search repository symbols, references, paths, and code chunks", {"query": "str", "limit": "int"}, repo_index_search, capabilities=caps("repo_index_search")))
    reg.register(Tool("repo_index_status", "Show repository index freshness, manifest, and skipped-file diagnostics", {"max_files": "int"}, repo_index_status, capabilities=caps("repo_index_status")))
    reg.register(Tool("mcp_servers", "List configured MCP servers", {}, mcp_servers, capabilities=caps("mcp_servers")))
    reg.register(Tool("mcp_presets", "List built-in browser/search/fetch MCP presets", {}, mcp_presets, capabilities=caps("mcp_presets")))
    reg.register(Tool("mcp_add_preset", "Persist a built-in browser/search/fetch MCP preset", {"preset": "str", "name": "str", "env": "dict"}, mcp_add_preset, capabilities=caps("mcp_add_preset")))
    reg.register(Tool("mcp_add_server", "Persist a stdio MCP server config", {"name": "str", "command": "str", "args": "list[str]", "env": "dict", "cwd": "str", "request_timeout": "int", "max_message_bytes": "int"}, mcp_add_server, capabilities=caps("mcp_add_server")))
    reg.register(Tool("mcp_remove_server", "Remove a configured MCP server", {"name": "str"}, mcp_remove_server, capabilities=caps("mcp_remove_server")))
    reg.register(Tool("mcp_health", "Check MCP server health, latency, tool count, and schema cache status", {"server": "str", "refresh": "bool"}, mcp_health, capabilities=caps("mcp_health")))
    reg.register(Tool("mcp_tools", "List tools from configured MCP servers", {"server": "str"}, mcp_tools, capabilities=caps("mcp_tools")))
    reg.register(Tool("mcp_call", "Call an MCP tool via stdio JSON-RPC", {"server": "str", "tool": "str", "arguments": "dict"}, mcp_call, needs_confirmation=True, capabilities=caps("mcp_call")))
    reg.register(Tool("delegate_agent", "Delegate a task to a role agent: planner, researcher, coder, reviewer", {"role": "str", "task": "str", "context_text": "str"}, delegate_agent, capabilities=caps("delegate_agent")))
    reg.register(Tool("collaborate", "Run a task through multiple role agents", {"task": "str", "roles": "list[str]", "context_text": "str"}, collaborate, capabilities=caps("collaborate")))
    reg.register(Tool("dream_report", "Run or verify the local Dream self-evolution loop over trace/eval/evolution evidence", {"limit": "int", "apply": "bool", "verify": "bool"}, dream_report, capabilities=caps("dream_report")))
    return reg
