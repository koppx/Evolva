from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from evolva.agent.llm import extract_json_object
from evolva.loops.registry import LoopRegistry
from evolva.loops.runner import validate_loop_spec
from evolva.loops.spec import LoopSpec

LoopIntentType = Literal["web_feature", "code_feature", "bugfix", "docs", "release", "analysis", "data_task"]
DraftStatus = Literal[
    "draft",
    "awaiting_confirmation",
    "confirmed",
    "dry_run_failed",
    "ready_to_run",
    "running",
    "completed",
    "cancelled",
    "needs_user_review",
]

RESERVED_LOOP_COMMANDS = {
    "list",
    "show",
    "validate",
    "dry-run",
    "run",
    "plan",
    "revise",
    "approve",
    "accept",
    "confirm",
    "execute",
    "save",
    "show-draft",
    "cancel",
    "help",
}


@dataclass
class DraftExecutionLimits:
    max_total_phases: int = 12
    max_repair_rounds: int = 1
    max_phase_retries: int = 1
    max_duration_seconds: int = 1800
    max_tool_calls: int = 40
    max_command_runs: int = 10
    max_file_changes: int = 30

    @classmethod
    def for_intent(cls, intent_type: str, complexity: str = "medium") -> "DraftExecutionLimits":
        if intent_type in {"analysis", "docs"}:
            return cls(max_total_phases=8, max_duration_seconds=900, max_tool_calls=20, max_command_runs=4, max_file_changes=10)
        if intent_type == "web_feature":
            return cls(max_total_phases=10, max_duration_seconds=1800, max_tool_calls=35, max_command_runs=8, max_file_changes=25)
        if intent_type in {"bugfix", "code_feature"}:
            return cls(max_total_phases=12, max_duration_seconds=2400, max_tool_calls=40, max_command_runs=10, max_file_changes=30)
        if intent_type == "release":
            return cls(max_total_phases=8, max_duration_seconds=1800, max_tool_calls=25, max_command_runs=8, max_file_changes=5)
        if intent_type == "data_task":
            return cls(max_total_phases=10, max_duration_seconds=2400, max_tool_calls=35, max_command_runs=8, max_file_changes=20)
        return cls()

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "DraftExecutionLimits":
        if not isinstance(data, dict):
            return cls()
        values = {}
        for key in cls.__dataclass_fields__:
            if key in data:
                try:
                    values[key] = int(data[key])
                except (TypeError, ValueError):
                    pass
        return cls(**values)

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass
class DraftPhase:
    id: str
    title: str
    purpose: str
    type: Literal["agent", "tool", "dream", "role"] = "agent"
    depends_on: list[str] = field(default_factory=list)
    expected_output: str = ""
    user_visible: bool = True
    requires_user_confirmation: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DraftPhase":
        return cls(
            id=str(data.get("id", "phase")),
            title=str(data.get("title", "")),
            purpose=str(data.get("purpose", "")),
            type=str(data.get("type", "agent")),  # type: ignore[arg-type]
            depends_on=[str(item) for item in data.get("depends_on", [])],
            expected_output=str(data.get("expected_output", "")),
            user_visible=bool(data.get("user_visible", True)),
            requires_user_confirmation=bool(data.get("requires_user_confirmation", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DraftCheckpoint:
    id: str
    after_phase: str
    type: Literal["phase_success", "command_success", "output_contains", "browser_check", "manual_confirmation"]
    description: str
    required: bool = True
    command: str = ""
    expected_contains: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DraftCheckpoint":
        return cls(
            id=str(data.get("id", "checkpoint")),
            after_phase=str(data.get("after_phase", data.get("after", ""))),
            type=str(data.get("type", "phase_success")),  # type: ignore[arg-type]
            description=str(data.get("description", "")),
            required=bool(data.get("required", True)),
            command=str(data.get("command", "")),
            expected_contains=str(data.get("expected_contains", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LoopDraft:
    draft_id: str
    user_request: str
    intent_type: LoopIntentType
    goal: str
    assumptions: list[str]
    open_questions: list[str]
    phases: list[DraftPhase]
    checkpoints: list[DraftCheckpoint]
    command_candidates: list[str]
    risks: list[str]
    execution_limits: DraftExecutionLimits
    loop_spec: LoopSpec
    workflow_spec: dict[str, Any] | None = None
    status: DraftStatus = "awaiting_confirmation"
    revisions: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    saved_path: str = ""
    validation_errors: list[str] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)
    planner_source: str = "heuristic"
    planner_model: str = ""
    planner_warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LoopDraft":
        return cls(
            draft_id=str(data.get("draft_id", "draft")),
            user_request=str(data.get("user_request", "")),
            intent_type=str(data.get("intent_type", "code_feature")),  # type: ignore[arg-type]
            goal=str(data.get("goal", "")),
            assumptions=[str(item) for item in data.get("assumptions", [])],
            open_questions=[str(item) for item in data.get("open_questions", [])],
            phases=[DraftPhase.from_dict(dict(item)) for item in data.get("phases", [])],
            checkpoints=[DraftCheckpoint.from_dict(dict(item)) for item in data.get("checkpoints", [])],
            command_candidates=[str(item) for item in data.get("command_candidates", [])],
            risks=[str(item) for item in data.get("risks", [])],
            execution_limits=DraftExecutionLimits.from_dict(data.get("execution_limits")),
            loop_spec=LoopSpec.from_dict(dict(data.get("loop_spec") or {"id": "draft", "phases": []})),
            workflow_spec=data.get("workflow_spec"),
            status=str(data.get("status", "awaiting_confirmation")),  # type: ignore[arg-type]
            revisions=[str(item) for item in data.get("revisions", [])],
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            saved_path=str(data.get("saved_path", "")),
            validation_errors=[str(item) for item in data.get("validation_errors", [])],
            validation_warnings=[str(item) for item in data.get("validation_warnings", [])],
            planner_source=str(data.get("planner_source", "heuristic")),
            planner_model=str(data.get("planner_model", "")),
            planner_warnings=[str(item) for item in data.get("planner_warnings", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["execution_limits"] = self.execution_limits.to_dict()
        data["phases"] = [item.to_dict() for item in self.phases]
        data["checkpoints"] = [item.to_dict() for item in self.checkpoints]
        data["loop_spec"] = self.loop_spec.to_dict()
        return data


class LoopIntentAnalyzer:
    """Small deterministic intent analyzer for offline, out-of-the-box planning."""

    WEB_KEYWORDS = {"web", "网页", "页面", "landing", "frontend", "前端", "react", "vue", "html", "css", "组件", "移动端", "响应式", "pricing", "faq"}
    BUG_KEYWORDS = {"bug", "fix", "修复", "报错", "失败", "错误", "crash", "异常", "不对", "broken"}
    DOC_KEYWORDS = {"文档", "readme", "docs", "说明", "教程", "手册", "markdown", "md"}
    RELEASE_KEYWORDS = {"发布", "release", "上线", "部署", "版本", "打包"}
    ANALYSIS_KEYWORDS = {"分析", "调研", "方案", "review", "评审", "看看", "诊断", "检查"}
    DATA_KEYWORDS = {"数据", "csv", "excel", "表格", "清洗", "etl", "dataset", "jsonl"}

    def analyze(self, request: str) -> tuple[LoopIntentType, str, list[str], list[str], str]:
        text = request.strip()
        lowered = text.lower()
        tokens = set(re.findall(r"[\w\-]+", lowered)) | {char for char in text if "\u4e00" <= char <= "\u9fff"}
        haystack = lowered + " " + text

        if self._contains(haystack, self.WEB_KEYWORDS):
            intent: LoopIntentType = "web_feature"
        elif self._contains(haystack, self.BUG_KEYWORDS):
            intent = "bugfix"
        elif self._contains(haystack, self.DOC_KEYWORDS):
            intent = "docs"
        elif self._contains(haystack, self.RELEASE_KEYWORDS):
            intent = "release"
        elif self._contains(haystack, self.DATA_KEYWORDS):
            intent = "data_task"
        elif self._contains(haystack, self.ANALYSIS_KEYWORDS):
            intent = "analysis"
        else:
            intent = "code_feature"

        complexity = "large" if len(text) > 180 or any(word in haystack for word in ["大型", "重构", "迁移", "全量", "复杂"]) else "medium"
        assumptions = [
            "默认先生成计划和 Loop spec，不直接执行。",
            "执行前会先进行 strict validate / dry-run。",
            "只使用模板内的安全命令候选，所有 shell 命令必须 allowlist。",
        ]
        if intent == "web_feature":
            assumptions.append("会先识别当前项目的前端框架和可用构建命令，再实施页面或组件改动。")
        if intent == "analysis":
            assumptions.append("分析类任务默认不修改文件，除非用户在计划中确认需要落盘报告。")
        open_questions: list[str] = []
        if any(word in haystack for word in ["登录", "支付", "权限", "认证", "auth", "payment"]):
            open_questions.append("需求涉及认证/支付/权限等高风险范围，执行前需要确认边界和验收口径。")
        goal = self._goal(intent, text)
        # Keep tokens used to avoid linter complaining in future changes; currently useful for debugging intent extensions.
        _ = tokens
        return intent, goal, assumptions, open_questions, complexity

    def _contains(self, haystack: str, keywords: set[str]) -> bool:
        return any(keyword.lower() in haystack for keyword in keywords)

    def _goal(self, intent: str, request: str) -> str:
        prefix = {
            "web_feature": "交付一个可验证的网页/前端功能",
            "bugfix": "定位并修复一个可回归验证的问题",
            "docs": "产出结构化、可审阅的文档改动",
            "release": "完成发布前检查与风险报告",
            "analysis": "完成基于证据的分析并输出建议",
            "data_task": "完成数据处理任务并验证结果",
            "code_feature": "交付一个可测试的代码功能改动",
        }.get(intent, "交付用户请求的工程任务")
        return f"{prefix}：{request.strip()}"


class LoopSpecSynthesizer:
    def synthesize(self, draft: LoopDraft) -> LoopSpec:
        data = self._spec_data(
            draft_id=draft.draft_id,
            request=draft.user_request,
            intent_type=draft.intent_type,
            goal=draft.goal,
            command_candidates=draft.command_candidates,
            limits=draft.execution_limits,
            draft_phases=draft.phases,
        )
        return LoopSpec.from_dict(data)

    def build_initial_spec(
        self,
        *,
        draft_id: str,
        request: str,
        intent_type: str,
        goal: str,
        command_candidates: list[str],
        limits: DraftExecutionLimits,
        draft_phases: list[DraftPhase] | None = None,
    ) -> LoopSpec:
        return LoopSpec.from_dict(
            self._spec_data(
                draft_id=draft_id,
                request=request,
                intent_type=intent_type,
                goal=goal,
                command_candidates=command_candidates,
                limits=limits,
                draft_phases=draft_phases,
            )
        )

    def _spec_data(
        self,
        *,
        draft_id: str,
        request: str,
        intent_type: str,
        goal: str,
        command_candidates: list[str],
        limits: DraftExecutionLimits,
        draft_phases: list[DraftPhase] | None = None,
    ) -> dict[str, Any]:
        safe_id = safe_loop_id(goal or request, prefix=f"generated-{intent_type}")
        phases = self._phases_from_draft(draft_phases or [], intent_type, request, goal, command_candidates, limits)
        if not phases:
            phases = self._phases_for(intent_type, request, goal, command_candidates, limits)
        gates = [{"after": phases[-1]["id"], "type": "phase_success"}] if phases else []
        for phase in phases:
            if phase.get("type") == "tool" and phase.get("tool") == "shell":
                gates.append({"after": phase["id"], "type": "phase_success"})
        return {
            "id": safe_id,
            "name": f"Generated {intent_type.replace('_', ' ').title()} Loop",
            "description": f"Generated from Loop Planner draft {draft_id}. User request: {request}",
            "trigger": {"type": "manual", "source": "loop_planner", "draft_id": draft_id},
            "command_allowlist": sanitize_command_candidates(command_candidates),
            "execution_limits": limits.to_dict(),
            "phases": phases,
            "gates": gates,
            "artifacts": ["trace", "loop_report", "implementation_summary"],
        }

    def _phases_from_draft(
        self,
        draft_phases: list[DraftPhase],
        intent_type: str,
        request: str,
        goal: str,
        command_candidates: list[str],
        limits: DraftExecutionLimits,
    ) -> list[dict[str, Any]]:
        if not draft_phases:
            return []
        safe_commands = sanitize_command_candidates(command_candidates)
        primary_command = choose_primary_command(safe_commands, intent_type) if safe_commands else ""
        output: list[dict[str, Any]] = []
        known_ids: set[str] = set()
        for idx, phase in enumerate(draft_phases[: limits.max_total_phases], start=1):
            phase_id = sanitize_identifier(phase.id or phase.title or f"phase_{idx}", fallback=f"phase_{idx}")
            if phase_id in known_ids:
                phase_id = f"{phase_id}_{idx}"
            deps = [dep for dep in phase.depends_on if dep in known_ids]
            known_ids.add(phase_id)
            purpose = phase.purpose or phase.title
            expected = phase.expected_output or "可审阅的阶段输出"
            if phase.type == "tool" and ("验证" in phase.title or "verify" in phase_id or "test" in phase_id or primary_command):
                if not primary_command:
                    continue
                output.append(
                    {
                        "id": phase_id,
                        "type": "tool",
                        "tool": "shell",
                        "depends_on": deps,
                        "args": {"command": primary_command},
                        "timeout": command_timeout(primary_command, intent_type),
                        "retries": min(1, limits.max_phase_retries),
                    }
                )
                continue
            prior_context = "\n".join(f"- {dep}: {{{{{dep}}}}}" for dep in deps) or "- none"
            confirmation_note = (
                "\nThis phase follows user confirmation of the draft/open questions. "
                "If the remaining information is still insufficient, stop and explain the blocker instead of guessing."
                if phase.requires_user_confirmation
                else ""
            )
            prompt = (
                f"Loop phase: {phase.title or phase_id}\n"
                f"User request: {{{{user_request}}}}\n"
                f"Concrete request: {request}\n"
                f"Overall goal: {goal}\n"
                f"Phase purpose: {purpose}\n"
                f"Expected output: {expected}\n"
                f"Previous phase outputs:\n{prior_context}\n"
                "Operate like a production coding agent: inspect only the minimum context needed, "
                "make concrete progress, finish with final once this phase's expected output is satisfied, "
                "and do not keep reading files after enough evidence is available. "
                "Respect existing project style, keep changes scoped, avoid destructive actions, "
                "and clearly report evidence, assumptions, blockers, and residual risks."
                f"{confirmation_note}"
            )
            output.append(
                {
                    "id": phase_id,
                    "type": phase.type if phase.type in {"agent", "role", "dream"} else "agent",
                    "depends_on": deps,
                    "prompt": prompt,
                    "timeout": 300 if phase_id != "implementation" else 600,
                    "retries": min(1, limits.max_phase_retries) if phase_id == "implementation" else 0,
                }
            )
        if output and output[-1]["id"] != "final_report" and len(output) < limits.max_total_phases:
            output.append(
                {
                    "id": "final_report",
                    "type": "agent",
                    "depends_on": [output[-1]["id"]],
                    "prompt": "Write the final report: completed work, validation evidence, user-visible behavior, residual risks, and exact next steps.",
                    "timeout": 180,
                    "retries": 0,
                }
            )
        return output

    def _phases_for(self, intent_type: str, request: str, goal: str, command_candidates: list[str], limits: DraftExecutionLimits) -> list[dict[str, Any]]:
        base_context = (
            "User request: {{user_request}}\n"
            f"Concrete request: {request}\n"
            "Respect existing project style, avoid unrelated changes, and report residual risks."
        )
        phases: list[dict[str, Any]] = [
            {
                "id": "context_scan",
                "type": "agent",
                "prompt": f"Scan the repository and identify relevant files, framework, commands, and risks for this task.\n{base_context}",
                "timeout": min(300, limits.max_duration_seconds),
                "retries": 0,
            }
        ]
        if intent_type == "analysis":
            phases.extend(
                [
                    {
                        "id": "analysis",
                        "type": "agent",
                        "depends_on": ["context_scan"],
                        "prompt": f"Produce an evidence-based analysis for the request. Cite inspected files/commands when available.\nGoal: {goal}\nContext: {{{{context_scan}}}}",
                        "timeout": 300,
                        "retries": 0,
                    },
                    {
                        "id": "final_report",
                        "type": "agent",
                        "depends_on": ["analysis"],
                        "prompt": "Summarize conclusions, evidence, risks, and recommended next steps. Include what was not executed.",
                        "timeout": 180,
                        "retries": 0,
                    },
                ]
            )
            return phases

        design_prompt = {
            "web_feature": "Create a concise product/page design: sections, content hierarchy, responsive behavior, states, and acceptance criteria.",
            "bugfix": "Create a bug investigation plan: suspected surfaces, reproduction strategy, fix criteria, and regression tests.",
            "docs": "Create a documentation outline and acceptance criteria. Preserve existing docs style.",
            "release": "Create a release readiness checklist with risk areas, commands, and go/no-go criteria.",
            "data_task": "Create a data task plan: inputs, transformations, validation checks, and output artifacts.",
        }.get(intent_type, "Create a concise implementation plan with files to inspect, acceptance criteria, and risks.")
        phases.append(
            {
                "id": "design_plan",
                "type": "agent",
                "depends_on": ["context_scan"],
                "prompt": f"{design_prompt}\nGoal: {goal}\nRepository scan: {{{{context_scan}}}}",
                "timeout": 300,
                "retries": 0,
            }
        )
        if intent_type != "release":
            phases.append(
                {
                    "id": "implementation",
                    "type": "agent",
                    "depends_on": ["design_plan"],
                    "prompt": "Implement the confirmed plan. Keep changes scoped, safe, and auditable. If blocked, explain instead of guessing.\nPlan: {{design_plan}}",
                    "timeout": 600,
                    "retries": min(1, limits.max_phase_retries),
                }
            )
            verification_dep = "implementation"
        else:
            verification_dep = "design_plan"

        if command_candidates:
            command = choose_primary_command(command_candidates, intent_type)
            phases.append(
                {
                    "id": "verification",
                    "type": "tool",
                    "tool": "shell",
                    "depends_on": [verification_dep],
                    "args": {"command": command},
                    "timeout": command_timeout(command, intent_type),
                    "retries": min(1, limits.max_phase_retries),
                }
            )
            final_dep = "verification"
        else:
            final_dep = verification_dep
        phases.append(
            {
                "id": "final_report",
                "type": "agent",
                "depends_on": [final_dep],
                "prompt": "Write the final report: changes or analysis completed, validation evidence, residual risks, and exact next commands for the user.",
                "timeout": 180,
                "retries": 0,
            }
        )
        return phases[: limits.max_total_phases]


class LLMLoopPlanner:
    """LLM-first planner for generic `/loop <request>` decomposition.

    The LLM produces a product/workflow draft only. It never executes tools.
    Every model field is normalized and sanitized before it becomes a LoopDraft.
    """

    VALID_INTENTS = {"web_feature", "code_feature", "bugfix", "docs", "release", "analysis", "data_task"}
    VALID_PHASE_TYPES = {"agent", "tool", "dream", "role"}
    VALID_CHECKPOINT_TYPES = {"phase_success", "command_success", "output_contains", "browser_check", "manual_confirmation"}

    def __init__(self) -> None:
        self.last_warnings: list[str] = []

    def try_create_draft(self, request: str, *, agent: Any | None, synthesizer: LoopSpecSynthesizer) -> LoopDraft | None:
        self.last_warnings = []
        if agent is None:
            self.last_warnings.append("LLM planner skipped: no agent was provided; using heuristic fallback.")
            return None
        llm = getattr(agent, "llm", None)
        if llm is None or not getattr(llm, "available", False):
            self.last_warnings.append("LLM planner unavailable: model/API key is not configured; using heuristic fallback.")
            return None
        try:
            planner_temperature = getattr(getattr(agent, "config", None), "temperature", None)
            response = llm.chat(self._messages(request, agent=agent), temperature=planner_temperature)
            data = extract_json_object(response.content)
        except Exception as exc:
            self.last_warnings.append(f"LLM planner failed: {exc}; using heuristic fallback.")
            return None
        if not isinstance(data, dict):
            self.last_warnings.append("LLM planner returned no valid JSON object; using heuristic fallback.")
            return None
        try:
            normalized, warnings = self._normalize(data, request=request, agent=agent)
        except Exception as exc:
            self.last_warnings.append(f"LLM planner output was invalid: {exc}; using heuristic fallback.")
            return None
        self.last_warnings.extend(warnings)
        draft_id = time.strftime("draft_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
        phases: list[DraftPhase] = normalized["phases"]
        command_candidates: list[str] = normalized["command_candidates"]
        limits: DraftExecutionLimits = normalized["execution_limits"]
        spec = synthesizer.build_initial_spec(
            draft_id=draft_id,
            request=request,
            intent_type=normalized["intent_type"],
            goal=normalized["goal"],
            command_candidates=command_candidates,
            limits=limits,
            draft_phases=phases,
        )
        model = str(getattr(getattr(agent, "config", None), "model", ""))
        return LoopDraft(
            draft_id=draft_id,
            user_request=request,
            intent_type=normalized["intent_type"],
            goal=normalized["goal"],
            assumptions=normalized["assumptions"],
            open_questions=normalized["open_questions"],
            phases=phases,
            checkpoints=normalized["checkpoints"],
            command_candidates=command_candidates,
            risks=normalized["risks"],
            execution_limits=limits,
            loop_spec=spec,
            status="awaiting_confirmation",
            planner_source="llm",
            planner_model=model,
            planner_warnings=self.last_warnings.copy(),
        )

    def _messages(self, request: str, *, agent: Any) -> list[dict[str, Any]]:
        tools = []
        try:
            tools = sorted(str(item) for item in agent.tools.names())[:80]
        except Exception:
            pass
        sandbox = ""
        try:
            sandbox = str(agent.sandbox.describe())[:1200]
        except Exception:
            pass
        system = """
You are Evolva's production Loop Engineering planner.
Decompose a user's natural-language engineering request into a safe, reviewable loop draft.

Return JSON only. No markdown. No comments.

Schema:
{
  "intent_type": "web_feature|code_feature|bugfix|docs|release|analysis|data_task",
  "goal": "string",
  "complexity": "small|medium|large",
  "assumptions": ["string"],
  "open_questions": ["string"],
  "phases": [
    {"id":"context_scan","title":"上下文扫描","purpose":"string","type":"agent|tool|role|dream","depends_on":[],"expected_output":"string"}
  ],
  "checkpoints": [
    {"id":"plan_review","after_phase":"design_plan","type":"phase_success|command_success|output_contains|browser_check|manual_confirmation","description":"string","required":true,"command":""}
  ],
  "command_candidates": ["npm run build"],
  "risks": ["string"],
  "execution_limits": {
    "max_total_phases": 10,
    "max_repair_rounds": 1,
    "max_phase_retries": 1,
    "max_duration_seconds": 1800,
    "max_tool_calls": 35,
    "max_command_runs": 8,
    "max_file_changes": 25
  }
}

Rules:
- This is planning only. Do not execute or claim execution.
- Include context_scan, design_plan (unless pure analysis may use analysis), and final_report phases.
- Phases must form a DAG and dependencies should reference previous phases only.
- Use LLM reasoning to tailor phases/checkpoints to the user's exact request, not generic boilerplate.
- Add manual_confirmation checkpoints for payments, auth, permissions, data deletion, deploy/release, production traffic, or unclear UX/product scope.
- Shell command candidates must be low-risk validation/build/test commands only.
- Do not include destructive or external side-effect commands such as rm, git push, deploy, publish, curl pipe sh, chmod, chown, kill, brew install, npm publish, terraform apply.
- Prefer commands such as npm run build, npm run lint, npm run test, npm test, pnpm build/test/lint, yarn build/test/lint, python -m pytest -q, .venv/bin/python -m pytest -q.
""".strip()
        user = (
            f"User request:\n{request}\n\n"
            f"Available tools (for awareness only; do not call them): {tools}\n"
            f"Sandbox summary: {sandbox}\n"
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def _normalize(self, data: dict[str, Any], *, request: str, agent: Any) -> tuple[dict[str, Any], list[str]]:
        warnings: list[str] = []
        fallback_intent, fallback_goal, fallback_assumptions, fallback_questions, complexity = LoopIntentAnalyzer().analyze(request)
        intent = str(data.get("intent_type", fallback_intent))
        if intent not in self.VALID_INTENTS:
            warnings.append(f"LLM planner emitted invalid intent `{intent}`; using `{fallback_intent}`.")
            intent = fallback_intent
        goal = normalize_request(str(data.get("goal") or fallback_goal))
        assumptions = sanitize_string_list(data.get("assumptions")) or fallback_assumptions
        open_questions = sanitize_string_list(data.get("open_questions")) or fallback_questions
        risks = sanitize_string_list(data.get("risks"))
        if not risks:
            risks = ["LLM 生成的是计划草案；执行前仍需要 confirm 校验。"]
        risks.append("LLM planner output has been sanitized before execution.")
        if "complexity" in data and str(data.get("complexity")) in {"small", "medium", "large"}:
            complexity = str(data["complexity"])
        limits = clamp_execution_limits(DraftExecutionLimits.for_intent(intent, complexity), data.get("execution_limits"), warnings)
        commands = sanitize_command_candidates(data.get("command_candidates"), warnings=warnings)
        repo_commands = repo_validation_candidates_for(intent, root=getattr(getattr(agent, "config", None), "root", None))
        if repo_commands:
            if commands and repo_commands != commands:
                warnings.append("Adjusted validation command candidates to match the detected local repository.")
            commands = repo_commands
        if not commands:
            commands = command_candidates_for(intent)
        phases = self._normalize_phases(data.get("phases"), intent=intent, limits=limits, warnings=warnings)
        checkpoints = self._normalize_checkpoints(data.get("checkpoints"), phases=phases, commands=commands, intent=intent, open_questions=open_questions, warnings=warnings)
        return (
            {
                "intent_type": intent,
                "goal": goal,
                "assumptions": assumptions,
                "open_questions": open_questions,
                "risks": dedupe(risks),
                "execution_limits": limits,
                "command_candidates": commands,
                "phases": phases,
                "checkpoints": checkpoints,
            },
            warnings,
        )

    def _normalize_phases(self, raw: Any, *, intent: str, limits: DraftExecutionLimits, warnings: list[str]) -> list[DraftPhase]:
        raw_items = raw if isinstance(raw, list) else []
        phases: list[DraftPhase] = []
        seen: set[str] = set()
        for idx, item in enumerate(raw_items[: limits.max_total_phases], start=1):
            if not isinstance(item, dict):
                continue
            phase_id = sanitize_identifier(str(item.get("id") or item.get("title") or f"phase_{idx}"), fallback=f"phase_{idx}")
            if phase_id in seen:
                phase_id = f"{phase_id}_{idx}"
            title = normalize_request(str(item.get("title") or phase_id.replace("_", " ")))
            purpose = normalize_request(str(item.get("purpose") or title))
            phase_type = str(item.get("type") or "agent")
            if phase_type not in self.VALID_PHASE_TYPES:
                warnings.append(f"Phase `{phase_id}` had invalid type `{phase_type}`; using agent.")
                phase_type = "agent"
            deps = []
            raw_deps = item.get("depends_on") or []
            if isinstance(raw_deps, str):
                raw_deps = [raw_deps]
            if isinstance(raw_deps, list):
                for dep in raw_deps:
                    dep_id = sanitize_identifier(str(dep), fallback="")
                    if dep_id and dep_id in seen and dep_id not in deps:
                        deps.append(dep_id)
                    elif dep_id:
                        warnings.append(f"Dropped dependency `{dep_id}` from `{phase_id}` because it does not reference a previous phase.")
            phases.append(
                DraftPhase(
                    id=phase_id,
                    title=title,
                    purpose=purpose,
                    type=phase_type,  # type: ignore[arg-type]
                    depends_on=deps,
                    expected_output=normalize_request(str(item.get("expected_output") or "可审阅的阶段输出")),
                    user_visible=bool(item.get("user_visible", True)),
                )
            )
            seen.add(phase_id)
        phases = ensure_required_phases(phases, intent=intent, limits=limits)
        return phases[: limits.max_total_phases]

    def _normalize_checkpoints(
        self,
        raw: Any,
        *,
        phases: list[DraftPhase],
        commands: list[str],
        intent: str,
        open_questions: list[str],
        warnings: list[str],
    ) -> list[DraftCheckpoint]:
        raw_items = raw if isinstance(raw, list) else []
        phase_ids = {phase.id for phase in phases}
        checkpoints: list[DraftCheckpoint] = []
        seen: set[str] = set()
        for idx, item in enumerate(raw_items, start=1):
            if not isinstance(item, dict):
                continue
            checkpoint_id = sanitize_identifier(str(item.get("id") or f"checkpoint_{idx}"), fallback=f"checkpoint_{idx}")
            if checkpoint_id in seen:
                checkpoint_id = f"{checkpoint_id}_{idx}"
            after = sanitize_identifier(str(item.get("after_phase") or item.get("after") or ""), fallback="")
            if after not in phase_ids:
                warnings.append(f"Dropped checkpoint `{checkpoint_id}` because phase `{after}` is missing.")
                continue
            checkpoint_type = str(item.get("type") or "phase_success")
            if checkpoint_type == "browser_check":
                # LoopSpec gates do not execute browser checks yet; keep it as a visible manual gate.
                checkpoint_type = "manual_confirmation"
            if checkpoint_type not in self.VALID_CHECKPOINT_TYPES:
                warnings.append(f"Checkpoint `{checkpoint_id}` had invalid type `{checkpoint_type}`; using phase_success.")
                checkpoint_type = "phase_success"
            command = str(item.get("command") or "")
            if command and command not in commands:
                command = ""
                warnings.append(f"Dropped checkpoint command for `{checkpoint_id}` because it is not in repository-adjusted command candidates.")
            checkpoints.append(
                DraftCheckpoint(
                    id=checkpoint_id,
                    after_phase=after,
                    type=checkpoint_type,  # type: ignore[arg-type]
                    description=normalize_request(str(item.get("description") or f"{after} checkpoint")),
                    required=bool(item.get("required", True)),
                    command=command,
                    expected_contains=str(item.get("expected_contains") or ""),
                )
            )
            seen.add(checkpoint_id)
        required = checkpoints_for(intent, commands, open_questions)
        existing = {item.id for item in checkpoints}
        for item in required:
            if item.after_phase in phase_ids and item.id not in existing:
                checkpoints.append(item)
        return checkpoints


class LoopPlanner:
    def __init__(self) -> None:
        self.intent_analyzer = LoopIntentAnalyzer()
        self.llm_planner = LLMLoopPlanner()
        self.synthesizer = LoopSpecSynthesizer()

    def create_draft(self, request: str, *, agent: Any | None = None) -> LoopDraft:
        request = normalize_request(request)
        if not request:
            raise ValueError("loop request cannot be empty")
        llm_draft = self.llm_planner.try_create_draft(request, agent=agent, synthesizer=self.synthesizer)
        if llm_draft is not None:
            return llm_draft
        warnings = self.llm_planner.last_warnings.copy()
        intent_type, goal, assumptions, open_questions, complexity = self.intent_analyzer.analyze(request)
        limits = DraftExecutionLimits.for_intent(intent_type, complexity)
        phases = draft_phases_for(intent_type)
        command_candidates = repo_validation_candidates_for(intent_type, root=getattr(getattr(agent, "config", None), "root", None))
        checkpoints = checkpoints_for(intent_type, command_candidates, open_questions)
        risks = risks_for(intent_type, open_questions)
        draft_id = time.strftime("draft_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
        spec = self.synthesizer.build_initial_spec(
            draft_id=draft_id,
            request=request,
            intent_type=intent_type,
            goal=goal,
            command_candidates=command_candidates,
            limits=limits,
            draft_phases=phases,
        )
        return LoopDraft(
            draft_id=draft_id,
            user_request=request,
            intent_type=intent_type,
            goal=goal,
            assumptions=assumptions,
            open_questions=open_questions,
            phases=phases,
            checkpoints=checkpoints,
            command_candidates=command_candidates,
            risks=risks,
            execution_limits=limits,
            loop_spec=spec,
            status="awaiting_confirmation",
            planner_source="heuristic",
            planner_warnings=warnings,
        )

    def revise_draft(self, draft: LoopDraft, feedback: str) -> LoopDraft:
        feedback = normalize_request(feedback)
        if not feedback:
            raise ValueError("revision feedback cannot be empty")
        draft.revisions.append(feedback)
        draft.user_request = f"{draft.user_request}\n\nRevision: {feedback}"
        draft.goal = f"{draft.goal}\n修订要求：{feedback}"
        draft.status = "awaiting_confirmation"
        draft.updated_at = time.time()
        # Heuristic refinements that users commonly ask for.
        lowered = feedback.lower()
        if any(word in lowered or word in feedback for word in ["不要执行", "只计划", "plan only"]):
            draft.open_questions.append("用户要求只生成计划，不执行。")
        if any(word in lowered or word in feedback for word in ["测试", "test", "lint", "检查"]):
            for command in ["npm run test", "npm run lint"]:
                if command not in draft.command_candidates and draft.intent_type == "web_feature":
                    draft.command_candidates.append(command)
        draft.loop_spec = self.synthesizer.synthesize(draft)
        return draft

    def accept_user_review(self, draft: LoopDraft, confirmation: str) -> LoopDraft:
        confirmation = normalize_request(confirmation)
        if not confirmation:
            raise ValueError("confirmation cannot be empty")
        draft.revisions.append(f"User review confirmation: {confirmation}")
        draft.assumptions.append(f"用户已确认/补充：{confirmation}")
        draft.open_questions = []
        first_manual_gate_index = len(draft.phases)
        phase_indexes = {phase.id: idx for idx, phase in enumerate(draft.phases)}
        for checkpoint in draft.checkpoints:
            if checkpoint.type == "manual_confirmation" and checkpoint.required:
                first_manual_gate_index = min(first_manual_gate_index, phase_indexes.get(checkpoint.after_phase, first_manual_gate_index))
        for phase in draft.phases:
            phase_index = phase_indexes.get(phase.id, 0)
            if phase_index >= first_manual_gate_index or (first_manual_gate_index == len(draft.phases) and phase_index >= len(draft.phases) // 2):
                phase.requires_user_confirmation = True
        draft.checkpoints = [checkpoint for checkpoint in draft.checkpoints if checkpoint.type != "manual_confirmation"]
        draft.status = "awaiting_confirmation"
        draft.loop_spec = self.synthesizer.synthesize(draft)
        draft.updated_at = time.time()
        return draft

    def confirm_draft(self, draft: LoopDraft, *, agent: Any | None = None) -> LoopDraft:
        draft.loop_spec = self.synthesizer.synthesize(draft)
        validation = validate_loop_spec(draft.loop_spec, agent=agent, strict_policy=agent is not None)
        draft.validation_errors = validation.errors
        draft.validation_warnings = validation.warnings
        draft.status = "ready_to_run" if validation.ok and not draft.open_questions else "needs_user_review" if draft.open_questions else "dry_run_failed"
        draft.updated_at = time.time()
        return draft


def normalize_request(text: str) -> str:
    return " ".join(text.strip().split())


def safe_loop_id(text: str, *, prefix: str = "generated-loop") -> str:
    raw = text.lower()
    raw = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", raw).strip("-")
    ascii_parts = re.findall(r"[a-z0-9]+", raw)
    slug = "-".join(ascii_parts[:8]) if ascii_parts else uuid.uuid4().hex[:8]
    return f"{prefix}-{slug}"[:80].strip("-")


def sanitize_identifier(text: str, *, fallback: str) -> str:
    raw = text.strip().lower().replace("-", "_")
    raw = re.sub(r"[^a-z0-9_]+", "_", raw).strip("_")
    raw = re.sub(r"_+", "_", raw)
    return raw[:48] or fallback


def sanitize_string_list(value: Any, *, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = normalize_request(str(item))
        if text and text not in result:
            result.append(text[:500])
        if len(result) >= limit:
            break
    return result


def dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result


SAFE_COMMAND_PREFIXES = (
    "npm run build",
    "npm run lint",
    "npm run test",
    "npm test",
    "pnpm build",
    "pnpm lint",
    "pnpm test",
    "pnpm run build",
    "pnpm run lint",
    "pnpm run test",
    "yarn build",
    "yarn lint",
    "yarn test",
    "yarn run build",
    "yarn run lint",
    "yarn run test",
    "python -m pytest -q",
    ".venv/bin/python -m pytest -q",
)
DANGEROUS_COMMAND_PATTERNS = re.compile(
    r"(^|\s)(rm|sudo|chmod|chown|kill|pkill|curl|wget|ssh|scp|rsync|dd|mkfs|brew|apt|pip\s+install|npm\s+publish|pnpm\s+publish|yarn\s+publish|git\s+push|git\s+reset|git\s+checkout|deploy|terraform\s+apply|kubectl\s+apply)(\s|$)|[;&|`$<>]",
    re.IGNORECASE,
)


def sanitize_command_candidates(value: Any, *, warnings: list[str] | None = None) -> list[str]:
    raw_items = value if isinstance(value, list) else []
    result: list[str] = []
    for item in raw_items:
        command = normalize_request(str(item))
        if not command:
            continue
        if DANGEROUS_COMMAND_PATTERNS.search(command):
            if warnings is not None:
                warnings.append(f"Dropped unsafe command candidate: `{command}`.")
            continue
        if not any(command == prefix or command.startswith(prefix + " ") for prefix in SAFE_COMMAND_PREFIXES):
            if warnings is not None:
                warnings.append(f"Dropped non-allowlisted command candidate: `{command}`.")
            continue
        if command not in result:
            result.append(command)
    return result[:8]


def repo_validation_candidates_for(intent_type: str, *, root: Path | None = None) -> list[str]:
    """Return low-risk validation commands tailored to the current repository.

    The LLM planner may not know whether the local repo is Node, Python, static
    HTML, or docs-only. This deterministic pass keeps generated LoopSpecs useful
    out of the box without hardcoding a product workflow: prefer commands that
    the current repo can actually run, then fall back to intent defaults.
    """

    if root is None:
        return command_candidates_for(intent_type)
    root = Path(root)
    commands: list[str] = []
    if root.joinpath("package.json").exists():
        package_text = root.joinpath("package.json").read_text(encoding="utf-8", errors="replace")[:20000]
        if '"build"' in package_text:
            commands.append("npm run build")
        if '"lint"' in package_text:
            commands.append("npm run lint")
        if '"test"' in package_text:
            commands.append("npm run test")
    has_pyproject = root.joinpath("pyproject.toml").exists()
    has_tests = root.joinpath("tests").exists()
    if has_pyproject or has_tests:
        if root.joinpath(".venv/bin/python").exists():
            commands.append(".venv/bin/python -m pytest -q")
        commands.append("python -m pytest -q")
    return dedupe(commands or command_candidates_for(intent_type))


def clamp_execution_limits(defaults: DraftExecutionLimits, value: Any, warnings: list[str]) -> DraftExecutionLimits:
    raw = value if isinstance(value, dict) else {}
    ranges = {
        "max_total_phases": (3, 14),
        "max_repair_rounds": (0, 3),
        "max_phase_retries": (0, 2),
        "max_duration_seconds": (300, 7200),
        "max_tool_calls": (5, 120),
        "max_command_runs": (0, 30),
        "max_file_changes": (0, 100),
    }
    values = defaults.to_dict()
    for key, (low, high) in ranges.items():
        if key not in raw:
            continue
        try:
            proposed = int(raw[key])
        except (TypeError, ValueError):
            warnings.append(f"Ignored invalid execution limit `{key}`.")
            continue
        clamped = max(low, min(high, proposed))
        if clamped != proposed:
            warnings.append(f"Clamped execution limit `{key}` from {proposed} to {clamped}.")
        values[key] = clamped
    return DraftExecutionLimits.from_dict(values)


def ensure_required_phases(phases: list[DraftPhase], *, intent: str, limits: DraftExecutionLimits) -> list[DraftPhase]:
    result = phases.copy()
    ids = {phase.id for phase in result}
    if "context_scan" not in ids:
        result.insert(0, DraftPhase("context_scan", "上下文扫描", "识别项目结构、相关文件、可用命令和风险", expected_output="上下文证据和约束"))
    ids = {phase.id for phase in result}
    ids = {phase.id for phase in result}
    design_aliases = {"design_plan", "product_design", "implementation_plan", "plan", "planning"}
    if intent == "analysis":
        if "analysis" not in ids and len(result) < limits.max_total_phases:
            result.append(DraftPhase("analysis", "证据分析", "基于上下文形成分析结论", depends_on=[result[-1].id], expected_output="证据、结论和建议"))
    elif not (ids & design_aliases) and len(result) < limits.max_total_phases:
        insert_at = next((idx for idx, phase in enumerate(result) if phase.id == "final_report"), len(result))
        dep = result[insert_at - 1].id if insert_at > 0 else "context_scan"
        result.insert(insert_at, DraftPhase("design_plan", "设计/实施计划", "把需求转成明确验收标准、检查点和文件级计划", depends_on=[dep], expected_output="可确认的产品/工程计划"))
    ids = {phase.id for phase in result}
    if "final_report" not in ids and len(result) < limits.max_total_phases:
        result.append(DraftPhase("final_report", "最终报告", "汇总执行结果、验证证据、风险和后续建议", depends_on=[result[-1].id], expected_output="Loop report"))
    # Re-sanitize dependencies after insertions.
    seen: set[str] = set()
    previous_id = ""
    for phase in result:
        phase.depends_on = [dep for dep in phase.depends_on if dep in seen]
        if not phase.depends_on and previous_id and phase.id != "context_scan":
            phase.depends_on = [previous_id]
        seen.add(phase.id)
        previous_id = phase.id
    return result


def command_candidates_for(intent_type: str) -> list[str]:
    if intent_type == "web_feature":
        return ["npm run build", "npm run lint", "npm run test"]
    if intent_type in {"bugfix", "code_feature"}:
        return [".venv/bin/python -m pytest -q", "python -m pytest -q", "npm test"]
    if intent_type == "docs":
        return []
    if intent_type == "release":
        return [".venv/bin/python -m pytest -q", "npm run build"]
    if intent_type == "data_task":
        return [".venv/bin/python -m pytest -q", "python -m pytest -q"]
    return []


def choose_primary_command(commands: list[str], intent_type: str) -> str:
    if not commands:
        return ""
    preferred = {
        "web_feature": ["npm run build", "npm run test", "npm run lint"],
        "release": [".venv/bin/python -m pytest -q", "npm run build"],
        "bugfix": [".venv/bin/python -m pytest -q", "python -m pytest -q", "npm test"],
        "code_feature": [".venv/bin/python -m pytest -q", "python -m pytest -q", "npm test"],
    }.get(intent_type, commands)
    for command in preferred:
        if command in commands:
            return command
    return commands[0]


def command_timeout(command: str, intent_type: str) -> int:
    if "pytest" in command:
        return 300
    if "build" in command:
        return 300 if intent_type == "web_feature" else 600
    return 180


def draft_phases_for(intent_type: str) -> list[DraftPhase]:
    if intent_type == "analysis":
        return [
            DraftPhase("context_scan", "上下文扫描", "识别相关文件、证据来源和约束", expected_output="仓库结构、相关文件、风险点"),
            DraftPhase("analysis", "证据分析", "基于上下文形成分析结论", depends_on=["context_scan"], expected_output="分析结论和证据"),
            DraftPhase("final_report", "最终报告", "输出结论、风险和建议", depends_on=["analysis"], expected_output="可交付报告"),
        ]
    common = [
        DraftPhase("context_scan", "上下文扫描", "识别项目结构、框架、可用命令和风险", expected_output="相关文件、框架、命令候选"),
        DraftPhase("design_plan", "设计/实施计划", "把需求转成明确验收标准和文件级计划", depends_on=["context_scan"], expected_output="阶段计划和验收标准"),
    ]
    if intent_type != "release":
        common.append(DraftPhase("implementation", "实施", "按确认后的计划进行最小必要改动", depends_on=["design_plan"], expected_output="代码/文档/配置改动"))
    verification_dep = "implementation" if intent_type != "release" else "design_plan"
    final_dep = verification_dep
    if command_candidates_for(intent_type):
        common.append(DraftPhase("verification", "自动验证", "运行安全 allowlist 内的检查命令", type="tool", depends_on=[verification_dep], expected_output="验证命令结果"))
        final_dep = "verification"
    common.extend(
        [
            DraftPhase("final_report", "最终报告", "汇总改动、验证、风险和运行方式", depends_on=[final_dep], expected_output="Loop report"),
        ]
    )
    return common


def checkpoints_for(intent_type: str, commands: list[str], open_questions: list[str]) -> list[DraftCheckpoint]:
    checkpoints = [
        DraftCheckpoint("plan_review", "design_plan", "phase_success", "设计/实施计划必须生成并可读。", True),
        DraftCheckpoint("final_report", "final_report", "phase_success", "最终报告必须包含结果、验证证据和剩余风险。", True),
    ]
    if commands:
        checkpoints.insert(1, DraftCheckpoint("command_check", "verification", "command_success", f"验证命令成功：{choose_primary_command(commands, intent_type)}", True, command=choose_primary_command(commands, intent_type)))
    if intent_type == "web_feature":
        checkpoints.append(DraftCheckpoint("responsive_acceptance", "implementation", "manual_confirmation", "页面关键区块和移动端表现需要人工或浏览器检查确认。", True))
    if open_questions:
        checkpoints.append(DraftCheckpoint("human_risk_gate", "design_plan", "manual_confirmation", "存在高风险或开放问题，执行前需要用户确认。", True))
    return checkpoints


def risks_for(intent_type: str, open_questions: list[str]) -> list[str]:
    risks = ["生成计划来自启发式模板，执行前需要用户确认。", "仓库实际命令可能不同，dry-run/上下文扫描应提示替换。"]
    if intent_type == "web_feature":
        risks.extend(["视觉质量和响应式效果需要浏览器或人工验收。", "如果项目不是 npm 前端项目，需要把验证命令改为实际命令。"])
    elif intent_type == "bugfix":
        risks.append("如果缺少可复现测试，修复可能无法证明没有回归。")
    elif intent_type == "release":
        risks.append("发布检查只报告风险，不应自动执行真实发布。")
    elif intent_type == "analysis":
        risks.append("分析结果依赖可读取的本地证据，可能需要用户补充业务背景。")
    risks.extend(open_questions)
    return risks


class LoopDraftSession:
    def __init__(self, path: Path, *, loops_dir: Path | None = None):
        self.path = path
        self.loops_dir = loops_dir
        self.planner = LoopPlanner()

    @classmethod
    def for_agent(cls, agent: Any) -> "LoopDraftSession":
        root = Path(agent.config.root)
        return cls(root / "evolva" / "runtime" / "loop_draft.json", loops_dir=agent.config.loops_dir)

    def load(self) -> LoopDraft | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return LoopDraft.from_dict(data)
        except Exception:
            return None

    def save(self, draft: LoopDraft) -> LoopDraft:
        draft.updated_at = time.time()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(draft.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return draft

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def plan(self, request: str, *, agent: Any | None = None) -> LoopDraft:
        return self.save(self.planner.create_draft(request, agent=agent))

    def revise(self, feedback: str) -> LoopDraft:
        draft = self.require_draft()
        return self.save(self.planner.revise_draft(draft, feedback))

    def accept_review(self, confirmation: str) -> LoopDraft:
        draft = self.require_draft()
        return self.save(self.planner.accept_user_review(draft, confirmation))

    def confirm(self, *, agent: Any | None = None) -> LoopDraft:
        draft = self.require_draft()
        return self.save(self.planner.confirm_draft(draft, agent=agent))

    def mark_running(self) -> LoopDraft:
        draft = self.require_draft()
        draft.status = "running"
        return self.save(draft)

    def restore_ready(self) -> LoopDraft:
        """Return a failed/interrupted execution draft to an executable state.

        Execution failures should not force users to re-confirm an unchanged,
        already dry-run validated LoopSpec. Keeping the draft ready makes the
        recovery path obvious: fix the environment/problem and run execute
        again, or revise the draft if the plan itself needs changing.
        """

        draft = self.require_draft()
        draft.status = "ready_to_run"
        return self.save(draft)

    def mark_completed(self) -> LoopDraft:
        draft = self.require_draft()
        draft.status = "completed"
        return self.save(draft)

    def save_loop(self, name: str = "") -> Path:
        draft = self.require_draft()
        if name:
            draft.loop_spec.id = safe_loop_id(name, prefix="generated")
            draft.loop_spec.name = name
        registry = LoopRegistry(self.loops_dir)
        path = registry.write_template(draft.loop_spec)
        draft.saved_path = str(path)
        self.save(draft)
        return path

    def require_draft(self) -> LoopDraft:
        draft = self.load()
        if draft is None:
            raise ValueError("No active loop draft. Use `/loop <request>` or `/loop plan <request>` first.")
        return draft


def render_loop_draft(draft: LoopDraft, *, show_spec: bool = False) -> str:
    planner = draft.planner_source
    if draft.planner_model:
        planner = f"{planner} ({draft.planner_model})"
    lines = [
        f"Loop Draft: {draft.draft_id}",
        f"- Status: {draft.status}",
        f"- Planner: {planner}",
        f"- Intent: {draft.intent_type}",
        f"- Goal: {draft.goal}",
        "",
        "Phases:",
    ]
    for idx, phase in enumerate(draft.phases, start=1):
        deps = f" deps={','.join(phase.depends_on)}" if phase.depends_on else ""
        lines.append(f"{idx}. {phase.title} [{phase.id}/{phase.type}]{deps}")
        if phase.purpose:
            lines.append(f"   - {phase.purpose}")
        if phase.expected_output:
            lines.append(f"   - Output: {phase.expected_output}")
    lines.append("")
    lines.append("Checkpoints:")
    for checkpoint in draft.checkpoints:
        required = "required" if checkpoint.required else "optional"
        command = f" command=`{checkpoint.command}`" if checkpoint.command else ""
        lines.append(f"- [{required}] {checkpoint.description} ({checkpoint.type} after {checkpoint.after_phase}){command}")
    lines.append("")
    lines.append("Execution limits:")
    for key, value in draft.execution_limits.to_dict().items():
        lines.append(f"- {key}: {value}")
    if draft.command_candidates:
        lines.append("")
        lines.append("Command candidates / allowlist:")
        lines.extend(f"- {command}" for command in draft.command_candidates)
    if draft.assumptions:
        lines.append("")
        lines.append("Assumptions:")
        lines.extend(f"- {item}" for item in draft.assumptions)
    if draft.open_questions:
        lines.append("")
        lines.append("Open questions / human gates:")
        lines.extend(f"- {item}" for item in draft.open_questions)
    if draft.risks:
        lines.append("")
        lines.append("Risks:")
        lines.extend(f"- {item}" for item in draft.risks)
    if draft.validation_errors or draft.validation_warnings:
        lines.append("")
        lines.append("Validation:")
        lines.extend(f"- Warning: {item}" for item in draft.validation_warnings)
        lines.extend(f"- Error: {item}" for item in draft.validation_errors)
    if draft.planner_warnings:
        lines.append("")
        lines.append("Planner warnings:")
        lines.extend(f"- {item}" for item in draft.planner_warnings)
    lines.extend(
        [
            "",
            "Next actions:",
            "- /loop revise <修改意见>",
            "- /loop confirm        # strict validate + dry-run，不执行",
            "- /loop execute        # 仅在 confirm 通过后执行",
            "- /loop save <name>    # 保存为可复用 Loop",
            "- /loop cancel",
        ]
    )
    if show_spec:
        lines.append("")
        lines.append("Generated LoopSpec:")
        lines.append(json.dumps(draft.loop_spec.to_dict(), ensure_ascii=False, indent=2))
    return "\n".join(lines)


def render_confirmed_draft(draft: LoopDraft) -> str:
    status = "ready" if draft.status == "ready_to_run" else draft.status
    lines = [f"Loop confirmation: {draft.draft_id}", f"- Status: {status}"]
    if draft.validation_warnings:
        lines.extend(f"- Warning: {item}" for item in draft.validation_warnings)
    if draft.validation_errors:
        lines.extend(f"- Error: {item}" for item in draft.validation_errors)
    if draft.open_questions:
        lines.append("- Human confirmation required before execution because open questions exist.")
        lines.extend(f"  - {item}" for item in draft.open_questions)
        lines.append("Next: /loop revise <补充细节> or /loop approve <确认说明> or /loop cancel")
        return "\n".join(lines)
    if draft.status == "ready_to_run":
        lines.append("- Dry-run: ok")
        lines.append("- Execution: not run")
        lines.append("Next: /loop execute or /loop save <name>")
    else:
        lines.append("Next: /loop revise <修改意见> or /loop cancel")
    return "\n".join(lines)


def first_loop_token(rest: str) -> str:
    return rest.split(maxsplit=1)[0] if rest.split(maxsplit=1) else ""


def is_natural_language_loop(rest: str) -> bool:
    if not rest.strip():
        return False
    return first_loop_token(rest) not in RESERVED_LOOP_COMMANDS
