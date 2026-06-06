from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from evolva.agent.context import ContextStore
from evolva.agent.evolution import SelfEvolutionEngine
from evolva.agent.images import user_content_with_images
from evolva.agent.llm import OpenAICompatibleLLM
from evolva.agent.memory import MemoryStore
from evolva.agent.mcp import MCPManager
from evolva.agent.multi_agent import MultiAgentCoordinator
from evolva.agent.policy import PolicyConfig, PolicyEngine
from evolva.agent.sandbox import Sandbox, SandboxPolicy
from evolva.agent.skills import SkillStore
from evolva.agent.todo import TodoStore
from evolva.agent.tracing import TraceRecorder
from evolva.agent.langgraph_runtime import EvolvaLangGraphRuntime
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
        self.mcp = MCPManager(self.config.mcp_config_file, root=self.config.root)
        self.llm = OpenAICompatibleLLM(self.config)
        self.coordinator = MultiAgentCoordinator(self.llm, self.memory, self.skills, self.todos)
        self.tools: ToolRegistry = build_registry(
            self.sandbox,
            self.memory,
            self.skills,
            self.context,
            self.todos,
            self.coordinator,
            self.policy,
            self.mcp,
            self.config.repo_index_file,
        )
        self.evolution = SelfEvolutionEngine(self.memory, self.skills)
        self.graph_runtime = EvolvaLangGraphRuntime(self)
        self.assume_yes = assume_yes
        self.confirmer = confirmer
        self.history: list[dict[str, Any]] = []

    def chat(self, user_message: str, image_sources: list[str] | None = None) -> TurnResult:
        self.tracer.start(
            user_message,
            meta={
                "runtime": "langgraph",
                "graph_nodes": self.graph_nodes(),
                "model": self.config.model,
                "llm_available": self.llm.available,
                "max_steps": self.config.max_steps,
                "images": image_sources or [],
            },
        )
        if not self.llm.available:
            if image_sources:
                result = TurnResult("未配置 OPENAI_API_KEY，当前规则模式无法理解图片。请配置支持视觉的 OpenAI-compatible 模型后重试。")
                self.tracer.end(result.answer, status="fallback_no_vision")
                return result
            result = self._fallback_chat(user_message)
            self.tracer.end(result.answer, status="fallback")
            return result

        state = self.graph_runtime.run(user_message, image_sources=image_sources)
        final = state.get("final", "")
        failed_tools = state.get("failed_tools", [])
        self.tracer.end(final, status="completed" if not failed_tools else "completed_with_tool_failures")
        return TurnResult(answer=final, tool_logs=state.get("tool_logs", []), failed_tools=failed_tools)

    def graph_nodes(self) -> list[str]:
        """Return the explicit LangGraph node names used by the runtime."""
        return ["prepare", "llm", "tool", "observe", "persist", "auto_evolve"]

    def _messages(self, user_message: str, scratch: str, image_sources: list[str] | None = None) -> list[dict[str, Any]]:
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
        messages.append({"role": "user", "content": user_content_with_images(user_message, image_sources, root=self.config.root)})
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
