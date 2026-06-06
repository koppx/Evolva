from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
from dataclasses import asdict

from evolva.agent.context import ContextStore
from evolva.agent.memory import MemoryStore
from evolva.agent.mcp import MCPManager, render_mcp_result
from evolva.agent.multi_agent import MultiAgentCoordinator
from evolva.agent.policy import PolicyEngine
from evolva.agent.repo_index import RepoIndex
from evolva.agent.sandbox import Sandbox
from evolva.agent.skills import SkillStore
from evolva.agent.todo import TodoStore
from evolva.tools.base import Tool, ToolRegistry, ToolResult


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
) -> ToolRegistry:
    reg = ToolRegistry()

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
        p = sandbox.resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if append:
            with p.open("a", encoding="utf-8") as f:
                f.write(content)
        else:
            p.write_text(content, encoding="utf-8")
        context.add("artifact", f"Wrote file {p.relative_to(sandbox.root)}", meta={"path": str(p), "chars": len(content), "append": append})
        return ToolResult(True, f"Wrote {len(content)} chars to {p.relative_to(sandbox.root)}")

    def shell(command: str, cwd: str = ".", timeout: int = 30) -> ToolResult:
        result = sandbox.run_shell(command, cwd=cwd, timeout=timeout)
        context.add("artifact", f"Shell `{command}` ok={result.ok}\n{result.output[:1000]}", meta={"cwd": cwd})
        return result

    def python_exec(code: str, timeout: int = 10) -> ToolResult:
        result = sandbox.run_python(code, timeout=timeout)
        context.add("artifact", f"Python exec ok={result.ok}\n{result.output[:1000]}")
        return result

    def web_search(query: str, max_results: int = 5) -> ToolResult:
        url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
        req = urllib.request.Request(url, headers={"User-Agent": "evolva/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            return ToolResult(False, f"Search failed: {exc}")
        import re

        matches = re.findall(r'<a rel="nofollow" class="result__a" href="([^"]+)">(.*?)</a>', html)
        rows = []
        for href, title in matches[:max_results]:
            title = re.sub("<.*?>", "", title)
            title = title.replace("&amp;", "&")
            rows.append({"title": title, "url": href})
        context.add("artifact", f"Web search: {query}", meta={"results": rows[:max_results]})
        return ToolResult(True, json.dumps(rows, ensure_ascii=False, indent=2), rows)

    def remember(kind: str, content: str, confidence: float = 0.7) -> ToolResult:
        item = memory.add(kind, content, confidence=confidence, source="agent")
        return ToolResult(True, f"Remembered [{item.kind}] {item.content}")

    def recall(query: str = "") -> ToolResult:
        return ToolResult(True, memory.context(query))

    def list_skills() -> ToolResult:
        names = [s.name for s in skills.list()]
        return ToolResult(True, "\n".join(names), names)

    def save_skill(name: str, content: str) -> ToolResult:
        path = skills.upsert(name, content)
        context.add("artifact", f"Saved skill {path.name}", meta={"path": str(path)})
        return ToolResult(True, f"Saved skill: {path.name}")

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
        output = f"Built repo index: {len(snapshot.chunks)} chunks backend={snapshot.backend}"
        context.add("artifact", output, meta={"index_file": str(index.index_file), "chunks": len(snapshot.chunks)})
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

    def mcp_servers() -> ToolResult:
        if mcp is None:
            return ToolResult(False, "MCP manager is not configured")
        names = mcp.list_servers()
        return ToolResult(True, "\n".join(names) or "No MCP servers configured", names)

    def mcp_tools(server: str = "") -> ToolResult:
        if mcp is None:
            return ToolResult(False, "MCP manager is not configured")
        rows = mcp.list_tools(server or None)
        lines = []
        for item in rows:
            lines.append(f"- {item.get('server')}/{item.get('name')}: {item.get('description', '')}")
        return ToolResult(True, "\n".join(lines) or "No MCP tools", rows)

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
        output = coordinator.delegate(role, task, context=context_text)
        context.add("note", f"Sub-agent {role} result for task `{task}`:\n{output}", role=role)
        return ToolResult(True, output)

    def collaborate(task: str, roles: list[str] | None = None, context_text: str = "") -> ToolResult:
        if coordinator is None:
            return ToolResult(False, "Multi-agent coordinator is not configured")
        output = coordinator.collaborate(task, roles=roles, context=context_text)
        context.add("note", f"Multi-agent collaboration for `{task}`:\n{output}")
        return ToolResult(True, output)

    reg.register(Tool("list_files", "List files under the sandbox root", {"path": "str", "max_entries": "int"}, list_files))
    reg.register(Tool("read_file", "Read a UTF-8 text file under the sandbox root", {"path": "str", "max_chars": "int"}, read_file))
    reg.register(Tool("write_file", "Write or append a UTF-8 text file under the sandbox root", {"path": "str", "content": "str", "append": "bool"}, write_file))
    reg.register(Tool("shell", "Run a shell command inside the sandbox", {"command": "str", "cwd": "str", "timeout": "int"}, shell, needs_confirmation=True))
    reg.register(Tool("python_exec", "Run a short Python snippet in a sandboxed subprocess", {"code": "str", "timeout": "int"}, python_exec, needs_confirmation=True))
    reg.register(Tool("web_search", "Search the web with DuckDuckGo HTML endpoint", {"query": "str", "max_results": "int"}, web_search))
    reg.register(Tool("remember", "Store a long-term memory item", {"kind": "str", "content": "str", "confidence": "float"}, remember))
    reg.register(Tool("recall", "Search long-term memory", {"query": "str"}, recall))
    reg.register(Tool("list_skills", "List available skills", {}, list_skills))
    reg.register(Tool("save_skill", "Create or update a markdown skill", {"name": "str", "content": "str"}, save_skill))
    reg.register(Tool("context_add", "Add a note, artifact, summary, decision, or message to persistent context", {"kind": "str", "content": "str", "role": "str"}, context_add))
    reg.register(Tool("context_view", "View/search persistent context", {"query": "str", "limit": "int"}, context_view))
    reg.register(Tool("context_compact", "Summarize recent context into a compact summary item", {"title": "str", "limit": "int"}, context_compact))
    reg.register(Tool("todo_add", "Add a todo item", {"title": "str", "detail": "str", "owner": "str"}, todo_add))
    reg.register(Tool("todo_list", "List todo items", {"include_done": "bool"}, todo_list))
    reg.register(Tool("todo_update", "Update a todo item", {"todo_id": "int", "status": "str", "title": "str", "detail": "str", "owner": "str"}, todo_update))
    reg.register(Tool("todo_clear", "Clear completed/cancelled todos, or all todos if include_done=true", {"include_done": "bool"}, todo_clear))
    reg.register(Tool("sandbox_info", "Show sandbox root, workspace, and policy", {}, sandbox_info))
    reg.register(Tool("policy_info", "Show guardrail policy configuration", {}, policy_info))
    reg.register(Tool("policy_check", "Preview whether policy allows a tool call", {"tool_name": "str", "args": "dict"}, policy_check))
    reg.register(Tool("repo_index_build", "Build a local semantic repository index with symbol chunks", {"max_files": "int"}, repo_index_build))
    reg.register(Tool("repo_index_search", "Search repository symbols, references, paths, and code chunks", {"query": "str", "limit": "int"}, repo_index_search))
    reg.register(Tool("mcp_servers", "List configured MCP servers", {}, mcp_servers))
    reg.register(Tool("mcp_tools", "List tools from configured MCP servers", {"server": "str"}, mcp_tools))
    reg.register(Tool("mcp_call", "Call an MCP tool via stdio JSON-RPC", {"server": "str", "tool": "str", "arguments": "dict"}, mcp_call, needs_confirmation=True))
    reg.register(Tool("delegate_agent", "Delegate a task to a role agent: planner, researcher, coder, reviewer", {"role": "str", "task": "str", "context_text": "str"}, delegate_agent))
    reg.register(Tool("collaborate", "Run a task through multiple role agents", {"task": "str", "roles": "list[str]", "context_text": "str"}, collaborate))
    return reg
