from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evolva.agent.core import EvolvaAgent
from evolva.tools.base import ToolResult


@dataclass
class WorkflowResult:
    workflow_id: str
    ok: bool
    outputs: dict[str, Any] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)


class WorkflowEngine:
    """A tiny workflow DAG/state-machine runner backed by Evolva tools and role agents."""

    def __init__(self, agent: EvolvaAgent):
        self.agent = agent

    def run_file(self, path: Path) -> WorkflowResult:
        data = json.loads(path.read_text(encoding="utf-8"))
        return self.run(data)

    def run(self, spec: dict[str, Any]) -> WorkflowResult:
        workflow_id = str(spec.get("id") or time.strftime("workflow_%Y%m%d_%H%M%S"))
        outputs: dict[str, Any] = {}
        logs: list[str] = []
        nodes = spec.get("nodes", [])
        for node in nodes:
            node_id = str(node.get("id") or f"node_{len(outputs) + 1}")
            kind = node.get("type", "agent")
            try:
                if kind == "tool":
                    result = self._run_tool_node(node, outputs)
                elif kind == "role":
                    result = self._run_role_node(node, outputs)
                elif kind == "agent":
                    result = self._run_agent_node(node, outputs)
                else:
                    result = ToolResult(False, f"Unknown workflow node type: {kind}")
            except Exception as exc:
                result = ToolResult(False, f"Workflow node error: {exc}")
            outputs[node_id] = result.output
            logs.append(f"[{node_id}/{kind}] ok={result.ok}\n{result.output}")
            self.agent.context.add("artifact", f"Workflow {workflow_id} node {node_id} ok={result.ok}\n{result.output[:1000]}")
            if not result.ok and not node.get("continue_on_error", False):
                return WorkflowResult(workflow_id, False, outputs, logs)
        return WorkflowResult(workflow_id, True, outputs, logs)

    def _run_tool_node(self, node: dict[str, Any], outputs: dict[str, Any]) -> ToolResult:
        name = str(node["tool"])
        args = self._render(node.get("args", {}), outputs)
        return self.agent._call_tool(name, args)

    def _run_role_node(self, node: dict[str, Any], outputs: dict[str, Any]) -> ToolResult:
        role = str(node.get("role", "planner"))
        task = str(self._render(node.get("task", ""), outputs))
        context = json.dumps(outputs, ensure_ascii=False)
        return self.agent._call_tool("delegate_agent", {"role": role, "task": task, "context_text": context})

    def _run_agent_node(self, node: dict[str, Any], outputs: dict[str, Any]) -> ToolResult:
        prompt = str(self._render(node.get("prompt", node.get("task", "")), outputs))
        result = self.agent.chat(prompt)
        return ToolResult(not result.failed_tools, result.answer, result)

    def _render(self, value: Any, outputs: dict[str, Any]) -> Any:
        if isinstance(value, str):
            rendered = value
            for key, output in outputs.items():
                rendered = rendered.replace("{{" + key + "}}", str(output))
            return rendered
        if isinstance(value, list):
            return [self._render(v, outputs) for v in value]
        if isinstance(value, dict):
            return {k: self._render(v, outputs) for k, v in value.items()}
        return value
