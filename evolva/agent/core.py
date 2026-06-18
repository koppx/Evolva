from __future__ import annotations

import re
from pathlib import Path
from dataclasses import dataclass, field, replace
from typing import Any

from evolva.agent.context import ContextStore
from evolva.agent.artifacts import ArtifactManifest
from evolva.agent.dream import DreamEngine
from evolva.agent.evolution import SelfEvolutionEngine
from evolva.agent.images import user_content_with_images
from evolva.agent.llm import OpenAICompatibleLLM
from evolva.agent.memory import MemoryStore
from evolva.agent.mcp import MCPManager
from evolva.agent.multi_agent import MultiAgentCoordinator
from evolva.agent.observability import ObservabilitySink
from evolva.agent.policy import PolicyConfig, PolicyDecision, PolicyEngine
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
    stopped_by_limit: bool = False


@dataclass(frozen=True)
class AgentExecutionBounds:
    max_file_changes: int | None = None
    baseline_modified_files: frozenset[str] = field(default_factory=frozenset)


class EvolvaAgent:
    def __init__(self, config: AgentConfig | None = None, *, assume_yes: bool = False, confirmer: Any | None = None):
        self.config = config or AgentConfig()
        self.config.ensure_dirs()
        self.memory = MemoryStore(self.config.memory_file)
        self.skills = SkillStore(self.config.skills_dir)
        self.context = ContextStore(self.config.context_file)
        self.todos = TodoStore(self.config.todo_file)
        self.sandbox = Sandbox(
            SandboxPolicy(
                self.config.root,
                self.config.workspace,
                self.config.sandbox_allow_shell,
                backend=self.config.sandbox_backend,
                container_image=self.config.sandbox_container_image,
                container_network=self.config.sandbox_container_network,
                container_read_only=self.config.sandbox_container_read_only,
                container_memory=self.config.sandbox_container_memory,
                container_cpus=self.config.sandbox_container_cpus,
                container_pids_limit=self.config.sandbox_container_pids_limit,
                container_user=self.config.sandbox_container_user,
            )
        )
        self.policy = PolicyEngine(PolicyConfig(self.config.root, self.config.workspace, profile=self.config.profile))
        self.observability = ObservabilitySink(self.config.metrics_file, self.config.alerts_file, enabled=self.config.observability_enabled)
        self.tracer = TraceRecorder(self.config.traces_dir, enabled=self.config.tracing_enabled, observability=self.observability)
        self.artifacts = ArtifactManifest(self.config.artifacts_file, self.config.root)
        self.mcp = MCPManager(self.config.mcp_config_file, root=self.config.root)
        self.llm = OpenAICompatibleLLM(self.config)
        self.coordinator = MultiAgentCoordinator(self.llm, self.memory, self.skills, self.todos)
        self.evolution = SelfEvolutionEngine(self.memory, self.skills)
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
            self._run_dream_tool,
        )
        self.graph_runtime = EvolvaLangGraphRuntime(self)
        self.assume_yes = assume_yes
        self.confirmer = confirmer
        self.history: list[dict[str, Any]] = []

    def set_model(self, model: str) -> str:
        """Switch the active OpenAI-compatible model for subsequent turns."""
        model = model.strip()
        if not model:
            raise ValueError("model name cannot be empty")
        self.config = replace(self.config, model=model)
        self.llm = OpenAICompatibleLLM(self.config)
        self.coordinator.llm = self.llm
        self.context.add("decision", f"Switched model to {model}", role="system", meta={"model": model})
        return model

    def update_llm_config(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        temperature: float | None = None,
    ) -> AgentConfig:
        """Update active provider settings without recreating the whole agent.

        TUI configuration uses this to make newly entered credentials effective
        immediately for the next turn.
        """

        updates: dict[str, Any] = {}
        if api_key is not None:
            updates["api_key"] = api_key.strip()
        if model is not None:
            model = model.strip()
            if not model:
                raise ValueError("model name cannot be empty")
            updates["model"] = model
        if base_url is not None:
            base_url = base_url.strip().rstrip("/")
            if not base_url:
                raise ValueError("base_url cannot be empty")
            updates["base_url"] = base_url
        if temperature is not None:
            updates["temperature"] = float(temperature)
        if not updates:
            return self.config
        self.config = replace(self.config, **updates)
        self.llm = OpenAICompatibleLLM(self.config)
        self.coordinator.llm = self.llm
        safe_updates = {key: ("configured" if key == "api_key" and value else value) for key, value in updates.items()}
        self.context.add("decision", "Updated LLM runtime configuration", role="system", meta=safe_updates)
        return self.config

    def _run_dream_tool(self, limit: int = 20, apply: bool = False, verify: bool = False) -> tuple[str, dict[str, Any]]:
        """Tool adapter for running the Dream loop from evals or agent actions."""
        engine = DreamEngine(self)
        if verify:
            results = engine.verify_backlog(limit=limit)
            return engine.render_verification(results), {"verification": [item.to_dict() for item in results]}
        report = engine.run(trace_limit=limit, apply=apply)
        return engine.render(report), report.to_dict()

    def chat(
        self,
        user_message: str,
        image_sources: list[str] | None = None,
        llm_timeout: int | None = None,
        execution_bounds: AgentExecutionBounds | None = None,
    ) -> TurnResult:
        meta = {
            "runtime": "langgraph",
            "graph_nodes": self.graph_nodes(),
            "model": self.config.model,
            "llm_available": self.llm.available,
            "max_steps": self.config.max_steps,
            "images": image_sources or [],
        }
        owns_trace = self.tracer.current is None
        if owns_trace:
            self.tracer.start(user_message, meta=meta)
        else:
            self.tracer.event("agent_chat_start", {"user_input": user_message, **meta})
        if not self.llm.available:
            if image_sources:
                result = TurnResult("未配置 OPENAI_API_KEY，当前规则模式无法理解图片。请配置支持视觉的 OpenAI-compatible 模型后重试。")
                if owns_trace:
                    self.tracer.end(result.answer, status="fallback_no_vision")
                else:
                    self.tracer.event("agent_chat_end", {"status": "fallback_no_vision", "answer": result.answer[:4000]})
                return result
            result = self._fallback_chat(user_message)
            if owns_trace:
                self.tracer.end(result.answer, status="fallback")
            else:
                self.tracer.event("agent_chat_end", {"status": "fallback", "answer": result.answer[:4000]})
            return result

        state = self.graph_runtime.run(user_message, image_sources=image_sources, llm_timeout=llm_timeout, execution_bounds=execution_bounds)
        final = state.get("final", "")
        failed_tools = state.get("failed_tools", [])
        stopped_by_limit = bool(state.get("stopped_by_limit", False))
        status = "stopped_by_limit" if stopped_by_limit else "completed" if not failed_tools else "completed_with_tool_failures"
        if owns_trace:
            self.tracer.end(final, status=status)
        else:
            self.tracer.event("agent_chat_end", {"status": status, "answer": final[:4000], "failed_tools": failed_tools})
        return TurnResult(answer=final, tool_logs=state.get("tool_logs", []), failed_tools=failed_tools, stopped_by_limit=stopped_by_limit)

    def graph_nodes(self) -> list[str]:
        """Return the explicit LangGraph node names used by the runtime."""
        return ["prepare", "llm", "tool", "observe", "persist", "auto_evolve"]

    def count_modified_files(self) -> int:
        return len(self.modified_file_paths())

    def modified_file_paths(self) -> set[str]:
        """Best-effort count of files changed under the sandbox root.

        Prefer Git when available because it captures modifications, additions,
        deletions, renames, and untracked files consistently. Fall back to zero
        for non-git workspaces rather than blocking legitimate local tasks.
        """

        try:
            import subprocess

            proc = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.config.root,
                text=True,
                capture_output=True,
                timeout=10,
            )
        except Exception:
            return set()
        if proc.returncode != 0:
            return set()
        paths: set[str] = set()
        for line in proc.stdout.splitlines():
            if not line:
                continue
            raw_path = line[3:] if len(line) > 3 else line
            if " -> " in raw_path:
                raw_path = raw_path.split(" -> ", 1)[1]
            raw_path = raw_path.strip().strip('"')
            if not raw_path:
                continue
            try:
                resolved = (self.config.root / raw_path).resolve()
                resolved.relative_to(Path(self.config.root).resolve())
            except Exception:
                continue
            paths.add(raw_path)
        return paths

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
            try:
                tool = self.tools.get(name)
            except KeyError as exc:
                policy = PolicyDecision(False, "high", f"Unknown tool: {name}", False, [], [], ["unknown_tool"])
                self.tracer.event("policy_decision", {"tool": name, "args": args, **policy.to_dict()})
                return ToolResult(False, f"Tool error: {exc}")
            policy = self.policy.check_tool(name, args, capabilities=tool.capabilities)
            self.tracer.event("policy_decision", {"tool": name, "args": args, **policy.to_dict()})
            if not policy.allowed:
                return ToolResult(False, f"Policy denied `{name}`: {policy.reason}", policy.to_dict())
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
            event_id = self.tracer.event(
                "tool_call",
                {
                    "tool": name,
                    "args": args,
                    "ok": result.ok,
                    "latency_ms": int((time.time() - started) * 1000),
                    "output": result.output[:4000],
                },
            )
            self._record_tool_artifacts(name, result, event_id or "")
            return result
        except Exception as exc:
            self.tracer.event("tool_error", {"tool": name, "error": str(exc)})
            return ToolResult(False, f"Tool error: {exc}")

    def _record_tool_artifacts(self, tool_name: str, result: ToolResult, event_id: str) -> None:
        """Persist artifact provenance from tool results into manifest and trace."""

        if not result.ok or not isinstance(result.data, dict):
            return
        artifact = result.data.get("artifact")
        if artifact is None:
            return
        artifacts = artifact if isinstance(artifact, list) else [artifact]
        for item in artifacts:
            if not isinstance(item, dict) or not item.get("path"):
                continue
            try:
                path = (self.config.root / str(item["path"])).resolve()
                record = self.artifacts.record_file(
                    path,
                    producer=tool_name,
                    run_id=self.tracer.current_run_id,
                    event_id=event_id,
                    kind=str(item.get("kind", "file")),
                    metadata={k: v for k, v in item.items() if k not in {"path", "absolute_path", "kind"}},
                )
                self.tracer.event("artifact", record.to_dict(), parent_id=event_id)
            except Exception as exc:
                self.tracer.event("artifact_error", {"tool": tool_name, "artifact": item, "error": str(exc)}, parent_id=event_id)

    def _fallback_chat(self, user_message: str) -> TurnResult:
        """Rule-based mode for when no LLM is configured."""
        text = user_message.strip()
        lower = text.lower()
        if lower.startswith("remember ") or lower.startswith("记住"):
            content = re.sub(r"^(remember\s+|记住[:：]?\s*)", "", text, flags=re.I)
            self.memory.add("fact", content, source="user")
            return TurnResult("已记住。")
        if "list" in lower and "file" in lower or "列" in text and "文件" in text:
            result = self._call_tool("list_files", {"path": "."})
            return TurnResult(result.output, [result.output], [] if result.ok else ["list_files"])
        if lower.startswith("read "):
            result = self._call_tool("read_file", {"path": text.split(maxsplit=1)[1]})
            return TurnResult(result.output, [result.output], [] if result.ok else ["read_file"])
        if lower.startswith("search "):
            result = self._call_tool("web_search", {"query": text.split(maxsplit=1)[1]})
            return TurnResult(result.output, [result.output], [] if result.ok else ["web_search"])
        help_text = (
            "未配置 OPENAI_API_KEY，当前处于规则模式。\n"
            "可用：remember <内容>、read <path>、search <query>，或使用 /run 直接调用工具。\n"
            "也可以用 /todo、/context、/agents 查看 todolist、上下文和多 agent 角色。\n"
            "配置 OPENAI_API_KEY 后即可启用完整规划-工具调用 Agent。"
        )
        return TurnResult(help_text)
