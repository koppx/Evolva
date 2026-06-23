from __future__ import annotations

import json
import time
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from evolva.agent.llm import extract_json_object
from evolva.tools.base import ToolResult


class EvolvaGraphState(TypedDict, total=False):
    user_message: str
    image_sources: list[str]
    scratch: str
    step: int
    final: str
    tool_logs: list[str]
    failed_tools: list[str]
    stopped_by_limit: bool
    last_action: dict[str, Any] | None
    last_tool_name: str | None
    last_tool_args: dict[str, Any]
    route: str
    llm_timeout: int
    execution_bounds: Any


class EvolvaLangGraphRuntime:
    """LangGraph runtime for Evolva's plan-act-observe-evolve loop.

    The graph keeps Evolva's existing public API while making the agent loop explicit:

    prepare -> llm -> route(action)
      - final -> persist -> auto_evolve -> END
      - tool  -> tool -> observe -> llm
      - stop  -> persist -> auto_evolve -> END
    """

    def __init__(self, agent: Any):
        self.agent = agent
        self.graph = self._build_graph()

    def run(
        self,
        user_message: str,
        image_sources: list[str] | None = None,
        llm_timeout: int | None = None,
        execution_bounds: Any | None = None,
    ) -> EvolvaGraphState:
        initial: EvolvaGraphState = {
            "user_message": user_message,
            "image_sources": image_sources or [],
            "scratch": "",
            "step": 0,
            "final": "",
            "tool_logs": [],
            "failed_tools": [],
            "stopped_by_limit": False,
            "last_action": None,
            "last_tool_name": None,
            "last_tool_args": {},
            "route": "llm",
        }
        if llm_timeout is not None:
            initial["llm_timeout"] = int(llm_timeout)
        if execution_bounds is not None:
            initial["execution_bounds"] = execution_bounds
        return self.graph.invoke(initial)

    def _build_graph(self):
        graph = StateGraph(EvolvaGraphState)
        graph.add_node("prepare", self._prepare)
        graph.add_node("llm", self._llm)
        graph.add_node("tool", self._tool)
        graph.add_node("observe", self._observe)
        graph.add_node("persist", self._persist)
        graph.add_node("auto_evolve", self._auto_evolve)

        graph.add_edge(START, "prepare")
        graph.add_conditional_edges("prepare", self._route_after_prepare, {"llm": "llm", "persist": "persist"})
        graph.add_conditional_edges("llm", self._route_after_llm, {"tool": "tool", "persist": "persist"})
        graph.add_edge("tool", "observe")
        graph.add_conditional_edges("observe", self._route_after_observe, {"llm": "llm", "persist": "persist"})
        graph.add_edge("persist", "auto_evolve")
        graph.add_edge("auto_evolve", END)
        return graph.compile()

    def _prepare(self, state: EvolvaGraphState) -> dict[str, Any]:
        self.agent.tracer.event("langgraph_node", {"node": "prepare"})
        return {"route": "llm"}

    def _route_after_prepare(self, state: EvolvaGraphState) -> Literal["llm", "persist"]:
        return "persist" if state.get("final") else "llm"

    def _llm(self, state: EvolvaGraphState) -> dict[str, Any]:
        step = int(state.get("step", 0)) + 1
        scratch = state.get("scratch", "")
        messages = self.agent._messages(state["user_message"], scratch, image_sources=state.get("image_sources") or None)
        self.agent.tracer.event(
            "langgraph_node",
            {"node": "llm", "step": step, "scratch_chars": len(scratch)},
        )
        self.agent.tracer.event("prompt", {"message_count": len(messages), "scratch_chars": len(scratch), "system_chars": len(messages[0]["content"])})
        timeout = int(state.get("llm_timeout") or getattr(self.agent.config, "request_timeout", 180))
        started = time.time()
        try:
            response = self.agent.llm.chat(messages, timeout=timeout)
        except TypeError as exc:
            if "timeout" not in str(exc):
                raise
            response = self.agent.llm.chat(messages)
        raw = response.content
        self.agent.tracer.event(
            "llm_response",
            {
                "raw": raw[:4000],
                "latency_ms": int((time.time() - started) * 1000),
                "attempts": getattr(response, "attempts", 1),
                "retries": getattr(response, "retries", 0),
                "model": getattr(self.agent.config, "model", ""),
            },
        )
        action = extract_json_object(raw)
        if not action:
            return {"step": step, "final": raw.strip(), "route": "persist", "last_action": None}
        if action.get("final"):
            return {"step": step, "final": str(action["final"]), "route": "persist", "last_action": action}
        tool = action.get("tool")
        if not tool:
            return {"step": step, "final": str(action.get("thought", "Done.")), "route": "persist", "last_action": action}
        name = str(tool.get("name") or "")
        args = tool.get("args") or {}
        if not isinstance(args, dict):
            args = {}
        return {"step": step, "last_action": action, "last_tool_name": name, "last_tool_args": args, "route": "tool"}

    def _route_after_llm(self, state: EvolvaGraphState) -> Literal["tool", "persist"]:
        if state.get("route") == "tool" and state.get("last_tool_name"):
            return "tool"
        return "persist"

    def _tool(self, state: EvolvaGraphState) -> dict[str, Any]:
        name = state.get("last_tool_name") or ""
        args = state.get("last_tool_args") or {}
        self.agent.tracer.event("langgraph_node", {"node": "tool", "tool": name})
        result: ToolResult = self.agent._call_tool(name, args)
        log = f"TOOL {name}({json.dumps(args, ensure_ascii=False)}) -> ok={result.ok}\n{result.output}"
        tool_logs = [*state.get("tool_logs", []), log]
        failed_tools = list(state.get("failed_tools", []))
        if not result.ok:
            failed_tools.append(name)
        bounds = state.get("execution_bounds")
        if bounds and bounds.max_file_changes is not None and name in {"write_file", "shell", "python_exec"}:
            baseline = set(getattr(bounds, "baseline_modified_files", frozenset()) or [])
            current = self.agent.modified_file_paths() if hasattr(self.agent, "modified_file_paths") else set()
            changed = len(current - baseline)
            if changed > bounds.max_file_changes:
                failed_tools.append(name)
                over_budget = f"Loop execution budget exceeded: max_file_changes={bounds.max_file_changes} exceeded after `{name}` ({changed} changed files)."
                log += f"\n{over_budget}"
                tool_logs[-1] = log
                result = ToolResult(False, f"{result.output}\n{over_budget}", result.data)
        scratch = (state.get("scratch") or "") + "\n" + log[:4000]
        return {"tool_logs": tool_logs, "failed_tools": failed_tools, "scratch": scratch}

    def _observe(self, state: EvolvaGraphState) -> dict[str, Any]:
        step = int(state.get("step", 0))
        self.agent.tracer.event("langgraph_node", {"node": "observe", "step": step})
        if step >= self.agent.config.max_steps:
            tool_logs = state.get("tool_logs", [])
            final = "达到最大执行步数，已停止。已完成的工具结果如下：\n" + "\n".join(tool_logs[-3:])
            return {"final": final, "route": "persist", "stopped_by_limit": True}
        return {"route": "llm"}

    def _route_after_observe(self, state: EvolvaGraphState) -> Literal["llm", "persist"]:
        return "persist" if state.get("final") else "llm"

    def _persist(self, state: EvolvaGraphState) -> dict[str, Any]:
        self.agent.tracer.event("langgraph_node", {"node": "persist"})
        user_message = state["user_message"]
        image_sources = state.get("image_sources") or []
        final = state.get("final") or ""
        history_user = user_message if not image_sources else f"{user_message}\n[Images: {', '.join(image_sources)}]"
        self.agent.history.append({"role": "user", "content": history_user})
        self.agent.history.append({"role": "assistant", "content": final})
        self.agent.context.add("message", history_user, role="user")
        self.agent.context.add("message", final, role="assistant")
        self.agent.tracer.event("context_write", {"items": 2})
        return {"final": final}

    def _auto_evolve(self, state: EvolvaGraphState) -> dict[str, Any]:
        self.agent.tracer.event("langgraph_node", {"node": "auto_evolve"})
        if self.agent.config.auto_evolve:
            report = self.agent.evolution.reflect_after_turn(state["user_message"], state.get("final", ""), state.get("failed_tools", []))
            payload = {"failed_tools": state.get("failed_tools", []), "report": report.to_dict() if report else None}
            self.agent.tracer.event("auto_evolve", payload)
            if report:
                self.agent.context.add("decision", report.summary(), role="evolution", meta={"evolution": report.to_dict()})
        return {}
