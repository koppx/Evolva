from __future__ import annotations

import json
from dataclasses import dataclass

from evolva.agent.llm import OpenAICompatibleLLM
from evolva.agent.memory import MemoryStore
from evolva.agent.skills import SkillStore
from evolva.agent.todo import TodoStore


@dataclass(frozen=True)
class AgentRole:
    name: str
    description: str
    system_prompt: str


DEFAULT_ROLES: dict[str, AgentRole] = {
    "planner": AgentRole("planner", "Breaks work into actionable plans", "You are Evolva Planner. Produce concise steps, dependencies, and risks."),
    "researcher": AgentRole("researcher", "Finds and summarizes information", "You are Evolva Researcher. Identify facts needed, sources to inspect, and uncertainties."),
    "coder": AgentRole("coder", "Implements code changes", "You are Evolva Coder. Propose concrete code edits and verification commands."),
    "reviewer": AgentRole("reviewer", "Reviews results for bugs and gaps", "You are Evolva Reviewer. Find missing requirements, risks, and test gaps."),
}


class MultiAgentCoordinator:
    """Role-based collaboration harness backed by the same LLM and shared state."""

    def __init__(self, llm: OpenAICompatibleLLM, memory: MemoryStore, skills: SkillStore, todos: TodoStore):
        self.llm = llm
        self.memory = memory
        self.skills = skills
        self.todos = todos
        self.roles = dict(DEFAULT_ROLES)

    def list_roles(self) -> str:
        return "\n".join(f"- {r.name}: {r.description}" for r in self.roles.values())

    def delegate(self, role: str, task: str, *, context: str = "") -> str:
        role_obj = self.roles.get(role)
        if role_obj is None:
            raise KeyError(f"unknown agent role: {role}")
        if not task.strip():
            raise ValueError("task is required")
        self.todos.add(f"Sub-agent {role_obj.name}: {task[:120]}", detail=context[:500], owner=role_obj.name)
        if not self.llm.available:
            return self._fallback(role_obj, task, context)
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
        return self.llm.chat(messages, temperature=0.2).content.strip()

    def collaborate(self, task: str, *, roles: list[str] | None = None, context: str = "") -> str:
        chosen = roles or ["planner", "researcher", "coder", "reviewer"]
        outputs: dict[str, str] = {}
        running_context = context
        for role in chosen:
            output = self.delegate(role, task, context=running_context)
            outputs[role] = output
            running_context += f"\n\n[{role}]\n{output}"
        return json.dumps(outputs, ensure_ascii=False, indent=2)

    def _fallback(self, role: AgentRole, task: str, context: str) -> str:
        if role.name == "planner":
            return f"Planner fallback:\n1. Clarify goal: {task}\n2. Create todos.\n3. Use tools to inspect state.\n4. Implement safely.\n5. Verify."
        if role.name == "reviewer":
            return "Reviewer fallback:\n- Check all explicit requirements.\n- Run compile/tests.\n- Search for stale names and missing docs."
        return f"{role.name.title()} fallback: inspect relevant files and report findings. Context: {context[:300] or 'none'}"
