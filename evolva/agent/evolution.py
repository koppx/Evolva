from __future__ import annotations

import re
from dataclasses import dataclass

from evolva.agent.memory import MemoryStore
from evolva.agent.skills import SkillStore


@dataclass
class EvolutionReport:
    lesson: str
    skill_name: str | None = None
    skill_path: str | None = None


class SelfEvolutionEngine:
    """Turns feedback and reflections into persistent lessons and skills."""

    def __init__(self, memory: MemoryStore, skills: SkillStore):
        self.memory = memory
        self.skills = skills

    def evolve(self, feedback: str, *, task: str = "", outcome: str = "") -> EvolutionReport:
        feedback = feedback.strip() or "No explicit feedback; summarize recent outcome."
        lesson = self._lesson_from(feedback, task=task, outcome=outcome)
        self.memory.add("lesson", lesson, confidence=0.85, source="self_evolution")
        skill_name = self._skill_name(feedback or task or lesson)
        skill_body = (
            f"## Lesson\n{lesson}\n\n"
            "## Procedure\n"
            "1. Detect when this lesson applies before acting.\n"
            "2. Add an explicit checklist item to the plan.\n"
            "3. Verify the result and record failures as new lessons.\n"
        )
        path = self.skills.upsert(skill_name, skill_body)
        return EvolutionReport(lesson=lesson, skill_name=skill_name, skill_path=str(path))

    def reflect_after_turn(self, user_message: str, final_answer: str, failed_tools: list[str]) -> EvolutionReport | None:
        if not failed_tools and len(final_answer) < 4000:
            return None
        feedback = "Tool failures occurred: " + ", ".join(failed_tools) if failed_tools else "Long answer; improve concision and verification."
        return self.evolve(feedback, task=user_message, outcome=final_answer[:1000])

    def _lesson_from(self, feedback: str, *, task: str, outcome: str) -> str:
        bits = [f"Feedback: {feedback}"]
        if task:
            bits.append(f"Task context: {task[:300]}")
        if outcome:
            bits.append(f"Outcome context: {outcome[:300]}")
        bits.append("Future behavior: convert the feedback into a pre-action checklist and verify it before final response.")
        return " | ".join(bits)

    def _skill_name(self, text: str) -> str:
        words = re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", text.lower())[:5]
        if not words:
            return "evolved_skill"
        # Keep ASCII-ish names readable; Chinese words are converted later by SkillStore sanitizer.
        return "evolved_" + "_".join(words)
