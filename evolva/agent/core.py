from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from evolva.agent.context import ContextStore
from evolva.agent.evolution import SelfEvolutionEngine
from evolva.agent.llm import OpenAICompatibleLLM, extract_json_object
from evolva.agent.memory import MemoryStore
from evolva.agent.multi_agent import MultiAgentCoordinator
from evolva.agent.policy import PolicyConfig, PolicyEngine
from evolva.agent.sandbox import Sandbox, SandboxPolicy
from evolva.agent.skills import SkillStore
from evolva.agent.todo import TodoStore
from evolva.agent.tracing import TraceRecorder
from evolva.config import AgentConfig
from evolva.tools.base import ToolRegistry, ToolResult
from evolva.tools.builtin import build_registry


SYSTEM_PROMPT = """You are Evolva, a local self-evolving super-agent harness.
You can plan, call tools, manage persistent context, maintain a todo list, delegate to role agents, execute inside a sandbox, remember facts, use skills, and improve yourself.

Return exactly one JSON object per step:
{
  "thought": "brief reasoning",
  "plan": ["short step", "..."],
  "tool": {"name": "tool_name", "args": {...}} | null,
  "final": "final answer to user, or null if you need a tool"
}

Rules:
- Use todo tools for multi-step work: create todos early, update statuses as work progresses, and close them when done.
- Use context tools to record important notes, artifacts, summaries, and decisions.
- Use delegate_agent/collaborate for multi-agent planning, research, coding advice, or review.
- Use sandbox_info and sandboxed file/shell/python tools for local work.
- Prefer safe, reversible actions. Do not fabricate tool outputs.
- When finished, set tool=null and final to a helpful answer.
- If a task teaches a reusable lesson, call remember or save_skill before final.
"""


@dataclass
class TurnResult:
    answer: str
    tool_logs: list[str] = field(default_factory=list)
    failed_tools: list[str] = field(default_factory=list)


class EvolvaAgent:
    def __init__(self, config: AgentConfig | None = None, *, assume_yes: bool = False, confirmer: Any | None = None):
        self.config = config or AgentConfig()
        self.config.ensure_dirs()
        self.memory = MemoryStore(self.config.memory_file)
        self.skills = SkillStore(self.config.skills_dir)
        self.context = ContextStore(self.config.context_file)
        self.todos = TodoStore(self.config.todo_file)
        self.sandbox = Sandbox(SandboxPolicy(self.config.root, self.config.workspace, self.config.sandbox_allow_shell))
        self.policy = PolicyEngine(PolicyConfig(self.config.root, self.config.workspace))
        self.tracer = TraceRecorder(self.config.traces_dir, enabled=self.config.tracing_enabled)
        self.llm = OpenAICompatibleLLM(self.config)
        self.coordinator = MultiAgentCoordinator(self.llm, self.memory, self.skills, self.todos)
        self.tools: ToolRegistry = build_registry(self.sandbox, self.memory, self.skills, self.context, self.todos, self.coordinator, self.policy)
        self.evolution = SelfEvolutionEngine(self.memory, self.skills)
        self.assume_yes = assume_yes
        self.confirmer = confirmer
        self.history: list[dict[str, str]] = []

    def chat(self, user_message: str) -> TurnResult:
        self.tracer.start(
            user_message,
            meta={"model": self.config.model, "llm_available": self.llm.available, "max_steps": self.config.max_steps},
        )
        if not self.llm.available:
            result = self._fallback_chat(user_message)
            self.tracer.end(result.answer, status="fallback")
            return result

        tool_logs: list[str] = []
        failed_tools: list[str] = []
        scratch = ""
        final = ""
        for _ in range(self.config.max_steps):
            messages = self._messages(user_message, scratch)
            self.tracer.event("prompt", {"message_count": len(messages), "scratch_chars": len(scratch), "system_chars": len(messages[0]["content"])})
            raw = self.llm.chat(messages).content
            self.tracer.event("llm_response", {"raw": raw[:4000]})
            action = extract_json_object(raw)
            if not action:
                final = raw.strip()
                break
            if action.get("final"):
                final = str(action["final"])
                break
            tool = action.get("tool")
            if not tool:
                final = str(action.get("thought", "Done."))
                break
            name = tool.get("name")
            args = tool.get("args") or {}
            result = self._call_tool(name, args)
            log = f"TOOL {name}({json.dumps(args, ensure_ascii=False)}) -> ok={result.ok}\n{result.output}"
            tool_logs.append(log)
            if not result.ok:
                failed_tools.append(name)
            scratch += "\n" + log[:4000]
        else:
            final = "达到最大执行步数，已停止。已完成的工具结果如下：\n" + "\n".join(tool_logs[-3:])

        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": final})
        self.context.add("message", user_message, role="user")
        self.context.add("message", final, role="assistant")
        self.tracer.event("context_write", {"items": 2})
        if self.config.auto_evolve:
            self.evolution.reflect_after_turn(user_message, final, failed_tools)
            self.tracer.event("auto_evolve", {"failed_tools": failed_tools})
        self.tracer.end(final, status="completed" if not failed_tools else "completed_with_tool_failures")
        return TurnResult(answer=final, tool_logs=tool_logs, failed_tools=failed_tools)

    def _messages(self, user_message: str, scratch: str) -> list[dict[str, str]]:
        context = (
            f"Relevant memories:\n{self.memory.context(user_message)}\n\n"
            f"Persistent context:\n{self.context.prompt_context(user_message)}\n\n"
            f"Active todos:\n{self.todos.context()}\n\n"
            f"Sandbox:\n{self.sandbox.describe()}\n\n"
            f"Sub-agent roles:\n{self.coordinator.list_roles()}\n\n"
            f"Relevant skills:\n{self.skills.context(user_message)}\n\n"
            f"Available tools:\n{self.tools.describe()}\n\n"
            f"Tool scratchpad:\n{scratch or 'No tool calls yet.'}"
        )
        messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n\n" + context}]
        messages.extend(self.history[-8:])
        messages.append({"role": "user", "content": user_message})
        return messages

    def _call_tool(self, name: str, args: dict[str, Any]) -> ToolResult:
        try:
            policy = self.policy.check_tool(name, args)
            self.tracer.event("policy_decision", {"tool": name, "args": args, **policy.to_dict()})
            if not policy.allowed:
                return ToolResult(False, f"Policy denied `{name}`: {policy.reason}", policy.to_dict())
            tool = self.tools.get(name)
            needs_confirmation = tool.needs_confirmation or policy.requires_confirmation
            if needs_confirmation and not self.assume_yes:
                if self.confirmer is not None:
                    allowed = bool(self.confirmer.ask(name, args))
                else:
                    reply = input(f"Allow tool `{name}` with args {args}? [y/N] ").strip().lower()
                    allowed = reply in {"y", "yes"}
                if not allowed:
                    return ToolResult(False, "User denied tool execution")
            import time

            started = time.time()
            result = self.tools.call(name, args)
            self.tracer.event(
                "tool_call",
                {
                    "tool": name,
                    "args": args,
                    "ok": result.ok,
                    "latency_ms": int((time.time() - started) * 1000),
                    "output": result.output[:4000],
                },
            )
            return result
        except Exception as exc:
            self.tracer.event("tool_error", {"tool": name, "error": str(exc)})
            return ToolResult(False, f"Tool error: {exc}")

    def _fallback_chat(self, user_message: str) -> TurnResult:
        """Rule-based mode for when no LLM is configured."""
        text = user_message.strip()
        lower = text.lower()
        if lower.startswith("remember ") or lower.startswith("记住"):
            content = re.sub(r"^(remember\s+|记住[:：]?\s*)", "", text, flags=re.I)
            self.memory.add("fact", content, source="user")
            return TurnResult("已记住。")
        if "list" in lower and "file" in lower or "列" in text and "文件" in text:
            result = self.tools.call("list_files", {"path": "."})
            return TurnResult(result.output, [result.output], [] if result.ok else ["list_files"])
        if lower.startswith("read "):
            result = self.tools.call("read_file", {"path": text.split(maxsplit=1)[1]})
            return TurnResult(result.output, [result.output], [] if result.ok else ["read_file"])
        if lower.startswith("search "):
            result = self.tools.call("web_search", {"query": text.split(maxsplit=1)[1]})
            return TurnResult(result.output, [result.output], [] if result.ok else ["web_search"])
        help_text = (
            "未配置 OPENAI_API_KEY，当前处于规则模式。\n"
            "可用：remember <内容>、read <path>、search <query>，或使用 /run 直接调用工具。\n"
            "也可以用 /todo、/context、/agents 查看 todolist、上下文和多 agent 角色。\n"
            "配置 OPENAI_API_KEY 后即可启用完整规划-工具调用 Agent。"
        )
        return TurnResult(help_text)
