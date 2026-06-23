from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Protocol

from evolva.agent.llm import OpenAICompatibleLLM, extract_json_object
from evolva.agent.memory import MemoryStore
from evolva.agent.skills import SkillStore
from evolva.agent.todo import TodoStore
from evolva.tools.base import ToolRegistry, ToolResult


class ToolRunner(Protocol):
    def __call__(self, name: str, args: dict[str, object]) -> ToolResult:
        ...


@dataclass(frozen=True)
class AgentRole:
    name: str
    description: str
    system_prompt: str
    tool_names: tuple[str, ...] = ()


@dataclass
class AgentRoleResult:
    role: str
    ok: bool
    output: str
    status: str
    latency_ms: int
    error: str = ""
    fallback: bool = False
    tool_calls: list[dict[str, object]] = field(default_factory=list)


@dataclass
class MultiAgentRun:
    run_id: str
    task: str
    roles: list[str]
    status: str
    started_at: float
    ended_at: float
    max_roles: int
    results: list[AgentRoleResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def outputs(self) -> dict[str, str]:
        return {result.role: result.output for result in self.results}

    def render(self) -> str:
        lines = [f"Multi-agent run {self.run_id}: {self.status}", f"- task: {self.task}", f"- roles: {', '.join(self.roles)}"]
        for result in self.results:
            detail = "fallback" if result.fallback else result.status
            lines.append(f"\n## {result.role} ({detail}, {result.latency_ms}ms)\n{result.output}")
        if self.errors:
            lines.append("\nErrors:")
            lines.extend(f"- {item}" for item in self.errors)
        return "\n".join(lines)


DEFAULT_ROLES: dict[str, AgentRole] = {
    "planner": AgentRole(
        "planner",
        "Breaks work into actionable plans",
        "You are Evolva Planner. Produce concise steps, dependencies, and risks.",
        ("recall", "context_view", "todo_list", "repo_index_status"),
    ),
    "researcher": AgentRole(
        "researcher",
        "Finds and summarizes information",
        "You are Evolva Researcher. Identify facts needed, sources to inspect, and uncertainties.",
        ("recall", "context_view", "repo_index_search", "repo_index_status", "list_files", "read_file", "web_search"),
    ),
    "coder": AgentRole(
        "coder",
        "Implements code changes",
        "You are Evolva Coder. Propose concrete code edits and verification commands.",
        ("recall", "context_view", "repo_index_search", "repo_index_status", "list_files", "read_file", "sandbox_info", "python_exec"),
    ),
    "reviewer": AgentRole(
        "reviewer",
        "Reviews results for bugs and gaps",
        "You are Evolva Reviewer. Find missing requirements, risks, and test gaps.",
        ("recall", "context_view", "repo_index_search", "repo_index_status", "list_files", "read_file", "sandbox_info", "python_exec"),
    ),
}


class MultiAgentCoordinator:
    """Role-based collaboration harness backed by the same LLM and shared state."""

    def __init__(
        self,
        llm: OpenAICompatibleLLM,
        memory: MemoryStore,
        skills: SkillStore,
        todos: TodoStore,
        *,
        max_roles_per_run: int = 4,
        max_tool_steps: int = 2,
    ):
        self.llm = llm
        self.memory = memory
        self.skills = skills
        self.todos = todos
        self.roles = dict(DEFAULT_ROLES)
        self.max_roles_per_run = max(1, int(max_roles_per_run))
        self.max_tool_steps = max(0, int(max_tool_steps))
        self.tool_runner: ToolRunner | None = None
        self.tool_registry: ToolRegistry | None = None

    def attach_tools(self, runner: ToolRunner, registry: ToolRegistry) -> None:
        """Attach the governed main-agent tool runner for bounded sub-agent use."""
        self.tool_runner = runner
        self.tool_registry = registry

    def list_roles(self) -> str:
        return "\n".join(f"- {r.name}: {r.description}" for r in self.roles.values())

    def delegate(self, role: str, task: str, *, context: str = "") -> str:
        return self.delegate_report(role, task, context=context).output

    def delegate_report(self, role: str, task: str, *, context: str = "") -> AgentRoleResult:
        started = time.monotonic()
        role_obj = self.roles.get(role)
        if role_obj is None:
            raise KeyError(f"unknown agent role: {role}")
        if not task.strip():
            raise ValueError("task is required")
        self.todos.add(f"Sub-agent {role_obj.name}: {task[:120]}", detail=context[:500], owner=role_obj.name)
        if not self.llm.available:
            return AgentRoleResult(role_obj.name, True, self._fallback(role_obj, task, context), "fallback", int((time.monotonic() - started) * 1000), fallback=True)
        if self.tool_runner is not None and self.tool_registry is not None and self.max_tool_steps > 0:
            return self._delegate_with_tools(role_obj, task, context=context, started=started)
        messages = [
            {"role": "system", "content": role_obj.system_prompt},
            {
                "role": "user",
                "content": (
                    f"Task:\n{task}\n\n"
                    f"Shared memory:\n{self.memory.context(task)}\n\n"
                    f"Relevant skills:\n{self.skills.context(task)}\n\n"
                    f"Current todos:\n{self.todos.context()}\n\n"
                    f"Extra context:\n{context or 'None'}\n\n"
                    "Return concise findings, next actions, and risks. Do not claim to run tools."
                ),
            },
        ]
        try:
            output = self.llm.chat(messages, temperature=0.2).content.strip()
            return AgentRoleResult(role_obj.name, True, output, "completed", int((time.monotonic() - started) * 1000))
        except Exception as exc:
            fallback = self._fallback(role_obj, task, context)
            return AgentRoleResult(role_obj.name, False, fallback, "failed_fallback", int((time.monotonic() - started) * 1000), error=str(exc), fallback=True)

    def collaborate(self, task: str, *, roles: list[str] | None = None, context: str = "") -> str:
        return json.dumps(self.collaborate_report(task, roles=roles, context=context).outputs(), ensure_ascii=False, indent=2)

    def collaborate_report(self, task: str, *, roles: list[str] | None = None, context: str = "") -> MultiAgentRun:
        task = task.strip()
        if not task:
            raise ValueError("task is required")
        chosen = roles or ["planner", "researcher", "coder", "reviewer"]
        chosen = self._normalize_roles(chosen)
        run_id = "multi_" + time.strftime("%Y%m%d_%H%M%S", time.gmtime()) + "_" + uuid.uuid4().hex[:8]
        started_at = time.time()
        results: list[AgentRoleResult] = []
        errors: list[str] = []
        running_context = context
        for role in chosen:
            result = self.delegate_report(role, task, context=running_context)
            results.append(result)
            if not result.ok:
                errors.append(f"{role}: {result.error or result.status}")
            running_context += f"\n\n[{role}]\n{result.output}"
        status = "completed" if not errors else "completed_with_fallbacks"
        return MultiAgentRun(run_id=run_id, task=task, roles=chosen, status=status, started_at=started_at, ended_at=time.time(), max_roles=self.max_roles_per_run, results=results, errors=errors)

    def _normalize_roles(self, roles: list[str]) -> list[str]:
        normalized: list[str] = []
        for role in roles:
            role = role.strip()
            if not role:
                continue
            if role not in self.roles:
                raise KeyError(f"unknown agent role: {role}")
            if role not in normalized:
                normalized.append(role)
        if not normalized:
            raise ValueError("at least one role is required")
        if len(normalized) > self.max_roles_per_run:
            raise ValueError(f"too many roles: {len(normalized)} > {self.max_roles_per_run}")
        return normalized

    def _delegate_with_tools(self, role: AgentRole, task: str, *, context: str, started: float) -> AgentRoleResult:
        allowed = tuple(name for name in role.tool_names if self.tool_registry is not None and name in self.tool_registry.names())
        scratch = ""
        tool_calls: list[dict[str, object]] = []
        messages = [
            {"role": "system", "content": role.system_prompt + "\n\n" + self._tool_loop_instructions(role, allowed)},
        ]
        for _ in range(self.max_tool_steps + 1):
            messages.append({"role": "user", "content": self._tool_loop_user_prompt(task, context=context, scratch=scratch, allowed=allowed)})
            try:
                data = self._chat_json(messages)
            except Exception as exc:
                fallback = self._fallback(role, task, context)
                return AgentRoleResult(role.name, False, fallback, "failed_fallback", int((time.monotonic() - started) * 1000), error=str(exc), fallback=True, tool_calls=tool_calls)

            final = data.get("final")
            tool = data.get("tool")
            if final and not tool:
                return AgentRoleResult(role.name, True, str(final).strip(), "completed", int((time.monotonic() - started) * 1000), tool_calls=tool_calls)
            if not tool:
                output = str(final or "").strip() or scratch or self._fallback(role, task, context)
                return AgentRoleResult(role.name, True, output, "completed", int((time.monotonic() - started) * 1000), tool_calls=tool_calls)
            if len(tool_calls) >= self.max_tool_steps:
                return AgentRoleResult(
                    role.name,
                    False,
                    scratch or self._fallback(role, task, context),
                    "tool_limit_reached",
                    int((time.monotonic() - started) * 1000),
                    error=f"sub-agent tool step limit reached: {self.max_tool_steps}",
                    tool_calls=tool_calls,
                )
            if not isinstance(tool, dict):
                return AgentRoleResult(role.name, False, scratch, "invalid_tool_request", int((time.monotonic() - started) * 1000), error="tool must be an object", tool_calls=tool_calls)
            name = str(tool.get("name") or "").strip()
            args = tool.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            if name not in allowed:
                call = self._tool_call_summary(name, args, ok=False, status="denied", output=f"Tool `{name}` is not allowed for role `{role.name}`.")
                tool_calls.append(call)
                return AgentRoleResult(role.name, False, call["output"], "tool_denied", int((time.monotonic() - started) * 1000), error=str(call["output"]), tool_calls=tool_calls)
            assert self.tool_runner is not None
            result = self.tool_runner(name, dict(args))
            call = self._tool_call_summary(name, args, ok=result.ok, status="ok" if result.ok else "failed", output=result.output)
            tool_calls.append(call)
            scratch += f"\nTool {name} ({call['status']}):\n{result.output[:1500]}\n"
            if not result.ok:
                return AgentRoleResult(role.name, False, scratch.strip(), "tool_failed", int((time.monotonic() - started) * 1000), error=result.output[:1000], tool_calls=tool_calls)
            messages.append({"role": "assistant", "content": json.dumps(data, ensure_ascii=False)})

        return AgentRoleResult(
            role.name,
            False,
            scratch.strip() or self._fallback(role, task, context),
            "tool_limit_reached",
            int((time.monotonic() - started) * 1000),
            error=f"sub-agent tool step limit reached: {self.max_tool_steps}",
            tool_calls=tool_calls,
        )

    def _tool_loop_instructions(self, role: AgentRole, allowed: tuple[str, ...]) -> str:
        tools = self._describe_allowed_tools(allowed)
        return (
            "You may call only the tools listed below, and at most one tool per step. "
            "Return exactly one JSON object with keys `thought`, `tool`, and `final`. "
            "`tool` is either null or {\"name\": \"tool_name\", \"args\": {...}}. "
            "When you have enough evidence, set tool=null and final to your concise answer. "
            "Do not claim tool results unless they appear in the tool scratchpad.\n\n"
            f"Allowed tools for {role.name}:\n{tools or '- none'}"
        )

    def _tool_loop_user_prompt(self, task: str, *, context: str, scratch: str, allowed: tuple[str, ...]) -> str:
        return (
            f"Task:\n{task}\n\n"
            f"Shared memory:\n{self.memory.context(task)}\n\n"
            f"Relevant skills:\n{self.skills.context(task)}\n\n"
            f"Current todos:\n{self.todos.context()}\n\n"
            f"Extra context:\n{context or 'None'}\n\n"
            f"Allowed tool names: {', '.join(allowed) or 'none'}\n\n"
            f"Tool scratchpad:\n{scratch.strip() or 'No sub-agent tool calls yet.'}"
        )

    def _describe_allowed_tools(self, allowed: tuple[str, ...]) -> str:
        if self.tool_registry is None:
            return ""
        lines: list[str] = []
        for name in allowed:
            try:
                tool = self.tool_registry.get(name)
            except KeyError:
                continue
            lines.append(f"- {tool.name}: {tool.description}; schema={tool.schema}; capabilities={tool.capabilities}")
        return "\n".join(lines)

    def _tool_call_summary(self, name: str, args: dict[str, object], *, ok: bool, status: str, output: str) -> dict[str, object]:
        return {
            "tool": name,
            "ok": ok,
            "status": status,
            "arg_keys": sorted(str(key) for key in args),
            "output": output[:1000],
        }

    def _chat_json(self, messages: list[dict[str, object]]) -> dict[str, object]:
        if hasattr(self.llm, "chat_json"):
            data = self.llm.chat_json(messages, required_keys=["tool", "final"], temperature=0.2)  # type: ignore[attr-defined]
        else:
            response = self.llm.chat(messages, temperature=0.2)  # type: ignore[attr-defined]
            data = extract_json_object(response.content)
            if data is None:
                raise RuntimeError("LLM response did not contain a JSON object")
        missing = [key for key in ("tool", "final") if key not in data]
        if missing:
            raise RuntimeError(f"LLM JSON response missing required keys: {', '.join(missing)}")
        return dict(data)

    def _fallback(self, role: AgentRole, task: str, context: str) -> str:
        if role.name == "planner":
            return f"Planner fallback:\n1. Clarify goal: {task}\n2. Create todos.\n3. Use tools to inspect state.\n4. Implement safely.\n5. Verify."
        if role.name == "reviewer":
            return "Reviewer fallback:\n- Check all explicit requirements.\n- Run compile/tests.\n- Search for stale names and missing docs."
        return f"{role.name.title()} fallback: inspect relevant files and report findings. Context: {context[:300] or 'none'}"
