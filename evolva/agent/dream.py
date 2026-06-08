from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from evolva.agent.evolution import EvolutionReport
from evolva.agent.evolution_analyzer import (
    EvalEvolutionAnalyzer,
    EvolutionAnalysis,
    EvolutionProposal,
    TraceEvolutionAnalyzer,
    apply_proposals,
)


@dataclass
class DreamInsight:
    """A distilled improvement opportunity found during an offline dream pass."""

    id: str
    category: str
    title: str
    description: str
    evidence: list[str] = field(default_factory=list)
    recommendation: str = ""
    confidence: float = 0.75
    source: str = "dream"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DreamEvidence:
    """A single local signal collected during a Dreaming pass."""

    id: str
    source: str
    category: str
    summary: str
    refs: list[str] = field(default_factory=list)
    weight: float = 0.7

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DreamHypothesis:
    """A falsifiable improvement claim derived from Dream evidence."""

    id: str
    category: str
    claim: str
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 0.75
    proposed_feedback: str = ""
    apply_reason: str = ""
    source: str = "dream"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DreamAction:
    """A concrete action proposed by the Dreaming loop."""

    id: str
    kind: str
    title: str
    detail: str
    hypothesis_id: str | None = None
    applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DreamReport:
    """Auditable output of Evolva's trace/eval/memory reflection loop."""

    dream_id: str
    generated_at: str
    inspected: dict[str, int]
    stages: list[str] = field(default_factory=list)
    evidence: list[DreamEvidence] = field(default_factory=list)
    hypotheses: list[DreamHypothesis] = field(default_factory=list)
    actions: list[DreamAction] = field(default_factory=list)
    rejections: list[str] = field(default_factory=list)
    insights: list[DreamInsight] = field(default_factory=list)
    applied: int = 0
    mode: str = "analyze"
    report_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = [item.to_dict() for item in self.evidence]
        data["hypotheses"] = [item.to_dict() for item in self.hypotheses]
        data["actions"] = [item.to_dict() for item in self.actions]
        data["insights"] = [insight.to_dict() for insight in self.insights]
        return data


class DreamEngine:
    """Run Evolva's local-first dream loop over traces, evals, and evolution state.

    Dream is intentionally deterministic and offline-testable: it does not call an
    LLM. It inspects recent execution evidence, converts trace/eval proposals into
    higher-level insights, records an auditable report, and can optionally apply
    high-confidence lessons into Memory/Skill through the existing evolution gate.
    """

    APPLY_CONFIDENCE_THRESHOLD = 0.72

    def __init__(self, agent: Any, dreams_dir: Path | None = None):
        self.agent = agent
        self.dreams_dir = dreams_dir or agent.config.dreams_dir
        self.dreams_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        *,
        trace_limit: int = 20,
        eval_report: Path | None = None,
        apply: bool = False,
        min_confidence: float | None = None,
    ) -> DreamReport:
        """Analyze recent evidence and optionally apply high-confidence improvements.

        This is an Evolva-native Dreaming loop: collect local evidence, generate
        hypotheses, critique them with deterministic drift guards, plan actions,
        and optionally promote only safe/high-confidence findings into the
        self-evolution layer. It is inspired by background reflection workflows;
        it does not depend on or claim access to any closed-source Codex internals.
        """
        min_confidence = min_confidence if min_confidence is not None else self.APPLY_CONFIDENCE_THRESHOLD
        trace_analysis = TraceEvolutionAnalyzer(self.agent.tracer).analyze(limit=trace_limit)
        eval_analysis = EvalEvolutionAnalyzer(self.agent.config.eval_results_dir).analyze_file(eval_report)
        status = self.agent.evolution.status(recent=8)

        proposals = self._dedupe_proposals(trace_analysis.proposals + eval_analysis.proposals)
        evidence = self._collect_evidence(trace_analysis, eval_analysis, status, proposals)
        hypotheses = self._generate_hypotheses(proposals, evidence, status)
        rejections, accepted = self._critique_hypotheses(hypotheses, evidence, min_confidence=min_confidence)
        actions = self._plan_actions(hypotheses, accepted, apply=apply)

        insights = [self._insight_from_hypothesis(item, evidence) for item in hypotheses]
        insights.extend(self._status_insights(status, proposals))
        insights = self._dedupe_insights(insights)

        applied_reports: list[EvolutionReport] = []
        if apply:
            accepted_ids = {item.id for item in accepted}
            applicable = [
                proposal
                for proposal in proposals
                if proposal.confidence >= min_confidence and f"hyp_{proposal.id}" in accepted_ids
            ]
            applied_reports = apply_proposals(self.agent.evolution, applicable)
            for action in actions:
                if action.kind == "apply_lesson" and action.hypothesis_id in accepted_ids:
                    action.applied = True

        report = DreamReport(
            dream_id=time.strftime("dream_%Y%m%d_%H%M%S"),
            generated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            inspected={
                "traces": trace_analysis.inspected,
                "eval_results": eval_analysis.inspected,
                "lessons": int(status.get("total_lessons", 0)),
                "proposals": len(proposals),
            },
            stages=["collect", "hypothesize", "critique", "plan", "apply" if apply else "archive"],
            evidence=evidence,
            hypotheses=hypotheses,
            actions=actions,
            rejections=rejections,
            insights=insights,
            applied=len(applied_reports),
            mode="apply" if apply else "analyze",
        )
        path = self.write_report(report)
        report.report_path = str(path)
        self._record_context(report, applied_reports)
        self.agent.tracer.event("dream", {"report": report.to_dict()})
        return report

    def write_report(self, report: DreamReport) -> Path:
        """Persist a JSON dream report and return its path."""
        path = self.dreams_dir / f"{report.dream_id}.json"
        payload = report.to_dict()
        payload["report_path"] = str(path)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def render(self, report: DreamReport) -> str:
        """Render a compact report for CLI/TUI users."""
        lines = [
            "Dream report",
            f"- ID: {report.dream_id}",
            f"- Mode: {report.mode}",
            f"- Stages: {' -> '.join(report.stages)}",
            "- Inspected: " + ", ".join(f"{k}={v}" for k, v in report.inspected.items()),
            f"- Evidence: {len(report.evidence)}",
            f"- Hypotheses: {len(report.hypotheses)}",
            f"- Actions: {len(report.actions)}",
            f"- Rejections: {len(report.rejections)}",
            f"- Insights: {len(report.insights)}",
            f"- Applied: {report.applied}",
        ]
        if report.report_path:
            lines.append(f"- Report: {report.report_path}")
        for insight in report.insights:
            evidence = ", ".join(insight.evidence[:4]) if insight.evidence else "none"
            lines.append(f"- {insight.id} [{insight.category}/{insight.confidence:.2f}] {insight.title}")
            lines.append(f"  {insight.description}")
            lines.append(f"  Next: {insight.recommendation}")
            lines.append(f"  Evidence: {evidence}")
        if report.actions:
            lines.append("Actions:")
            for action in report.actions[:8]:
                marker = "applied" if action.applied else action.kind
                lines.append(f"- {action.id} [{marker}] {action.title}")
        if report.rejections:
            lines.append("Rejected by drift guard:")
            lines.extend(f"- {item}" for item in report.rejections[:8])
        if not report.insights:
            lines.append("- No new opportunities found. Keep collecting traces/evals.")
        return "\n".join(lines)

    def _collect_evidence(
        self,
        trace_analysis: EvolutionAnalysis,
        eval_analysis: EvolutionAnalysis,
        status: dict[str, Any],
        proposals: list[EvolutionProposal],
    ) -> list[DreamEvidence]:
        evidence: list[DreamEvidence] = []
        for proposal in proposals:
            evidence.append(
                DreamEvidence(
                    id=f"ev_{proposal.id}",
                    source=proposal.source,
                    category=proposal.category,
                    summary=proposal.feedback,
                    refs=proposal.evidence[:10],
                    weight=proposal.confidence,
                )
            )
        total_lessons = int(status.get("total_lessons", 0))
        skill_stats = status.get("skill_stats", {}) or {}
        evidence.append(
            DreamEvidence(
                id="ev_evolution_status",
                source="memory",
                category="workflow",
                summary=(
                    f"Evolution state: lessons={total_lessons}, "
                    f"skills={skill_stats.get('total', 0)}, evolved_skills={skill_stats.get('evolved', 0)}."
                ),
                refs=[f"trace_inspected={trace_analysis.inspected}", f"eval_inspected={eval_analysis.inspected}"],
                weight=0.65 if total_lessons == 0 else 0.78,
            )
        )
        return self._dedupe_evidence(evidence)

    def _generate_hypotheses(
        self,
        proposals: list[EvolutionProposal],
        evidence: list[DreamEvidence],
        status: dict[str, Any],
    ) -> list[DreamHypothesis]:
        hypotheses: list[DreamHypothesis] = []
        evidence_ids = {item.id for item in evidence}
        for proposal in proposals:
            ev_id = f"ev_{proposal.id}"
            hypotheses.append(
                DreamHypothesis(
                    id=f"hyp_{proposal.id}",
                    category=proposal.category,
                    claim=proposal.feedback,
                    evidence_ids=[ev_id] if ev_id in evidence_ids else [],
                    confidence=proposal.confidence,
                    proposed_feedback=proposal.feedback,
                    apply_reason=self._recommendation_for(proposal),
                    source=proposal.source,
                )
            )

        total_lessons = int(status.get("total_lessons", 0))
        if total_lessons == 0 and not proposals:
            hypotheses.append(
                DreamHypothesis(
                    id="hyp_bootstrap_evolution_loop",
                    category="workflow",
                    claim="The evolution loop needs more trace/eval evidence before it should write durable lessons.",
                    evidence_ids=["ev_evolution_status"],
                    confidence=0.64,
                    proposed_feedback="Collect several real traces and at least one eval report before applying new self-evolution lessons.",
                    apply_reason="Observe only; bootstrap signals are intentionally below the apply threshold.",
                    source="status",
                )
            )

        return self._dedupe_hypotheses(hypotheses)

    def _critique_hypotheses(
        self,
        hypotheses: list[DreamHypothesis],
        evidence: list[DreamEvidence],
        *,
        min_confidence: float,
    ) -> tuple[list[str], list[DreamHypothesis]]:
        evidence_ids = {item.id for item in evidence}
        accepted: list[DreamHypothesis] = []
        rejections: list[str] = []
        for item in hypotheses:
            reasons = []
            if item.confidence < min_confidence:
                reasons.append(f"confidence {item.confidence:.2f} < {min_confidence:.2f}")
            if not item.evidence_ids or not any(ev_id in evidence_ids for ev_id in item.evidence_ids):
                reasons.append("missing local evidence")
            if self.agent.memory.find_similar("lesson", item.proposed_feedback, threshold=0.88) is not None:
                reasons.append("near-duplicate lesson already exists")
            if item.id == "hyp_bootstrap_evolution_loop":
                reasons.append("bootstrap signal is observe-only")
            if reasons:
                rejections.append(f"{item.id}: " + "; ".join(reasons))
            else:
                accepted.append(item)
        return rejections, accepted

    def _plan_actions(self, hypotheses: list[DreamHypothesis], accepted: list[DreamHypothesis], *, apply: bool) -> list[DreamAction]:
        accepted_ids = {item.id for item in accepted}
        actions: list[DreamAction] = []
        for item in hypotheses:
            if item.id in accepted_ids:
                kind = "apply_lesson" if apply else "observe_only"
                title = "Promote lesson" if apply else "Review before applying"
                detail = item.apply_reason or "Review this hypothesis against its evidence before promotion."
            elif item.source == "eval":
                kind = "rerun_eval"
                title = "Rerun eval after fix"
                detail = "Keep this eval failure visible until a later Dream pass has stronger evidence."
            else:
                kind = "observe_only"
                title = "Keep collecting evidence"
                detail = "The drift guard rejected automatic promotion for now."
            actions.append(
                DreamAction(
                    id=f"act_{item.id.removeprefix('hyp_')}",
                    kind=kind,
                    title=title,
                    detail=detail,
                    hypothesis_id=item.id,
                )
            )
        return actions

    def _dedupe_proposals(self, proposals: list[EvolutionProposal]) -> list[EvolutionProposal]:
        out: list[EvolutionProposal] = []
        seen: set[tuple[str, str, str]] = set()
        for proposal in proposals:
            key = (proposal.source, proposal.category, proposal.feedback)
            if key in seen:
                continue
            seen.add(key)
            out.append(proposal)
        return out

    def _insight_from_hypothesis(self, hypothesis: DreamHypothesis, evidence: list[DreamEvidence]) -> DreamInsight:
        by_id = {item.id: item for item in evidence}
        refs: list[str] = []
        for ev_id in hypothesis.evidence_ids:
            item = by_id.get(ev_id)
            if item is not None:
                refs.extend(item.refs or [item.summary])
        return DreamInsight(
            id=f"dream_{hypothesis.id.removeprefix('hyp_')}",
            category=hypothesis.category,
            title=self._title_for_hypothesis(hypothesis),
            description=hypothesis.claim,
            evidence=refs[:10],
            recommendation=hypothesis.apply_reason or "Review the hypothesis and gather more trace/eval evidence.",
            confidence=hypothesis.confidence,
            source=hypothesis.source,
        )

    def _status_insights(self, status: dict[str, Any], proposals: list[EvolutionProposal]) -> list[DreamInsight]:
        insights: list[DreamInsight] = []
        total_lessons = int(status.get("total_lessons", 0))
        skill_stats = status.get("skill_stats", {}) or {}
        evolved_skills = int(skill_stats.get("evolved", 0) or 0)
        categories = dict(status.get("lesson_categories", {}) or {})
        proposal_categories = {proposal.category for proposal in proposals}

        if total_lessons == 0 and not proposals:
            insights.append(
                DreamInsight(
                    id="dream_bootstrap_evolution_loop",
                    category="workflow",
                    title="Bootstrap the evolution loop with richer evidence",
                    description="No lessons or pending proposals were found, so future sessions need more trace/eval evidence before evolution can compound.",
                    evidence=["total_lessons=0", "proposals=0"],
                    recommendation="Run real tasks, keep tracing enabled, then run `evolva dream` or `evolva eval ...` to seed lessons.",
                    confidence=0.64,
                )
            )
        if total_lessons > evolved_skills:
            insights.append(
                DreamInsight(
                    id="dream_materialize_lessons_as_skills",
                    category="workflow",
                    title="Materialize important lessons as reusable skills",
                    description=f"Memory contains {total_lessons} lesson(s), but only {evolved_skills} evolved skill(s) are visible.",
                    evidence=[f"total_lessons={total_lessons}", f"evolved_skills={evolved_skills}"],
                    recommendation="Review high-value lessons and ensure they exist as Markdown skills with explicit checklists.",
                    confidence=0.78,
                )
            )
        missing = sorted(proposal_categories - set(categories))
        if missing:
            insights.append(
                DreamInsight(
                    id="dream_uncovered_proposal_categories",
                    category="verification",
                    title="Close uncovered proposal categories",
                    description="Recent trace/eval proposals surfaced categories that are not yet represented in long-term lessons.",
                    evidence=["missing=" + ",".join(missing[:6])],
                    recommendation="Run `evolva dream --apply` after reviewing the report to convert high-confidence categories into lessons.",
                    confidence=0.82,
                )
            )
        return insights

    def _dedupe_insights(self, insights: list[DreamInsight]) -> list[DreamInsight]:
        out: list[DreamInsight] = []
        seen: set[str] = set()
        for insight in insights:
            if insight.id in seen:
                continue
            seen.add(insight.id)
            out.append(insight)
        return out

    def _dedupe_evidence(self, evidence: list[DreamEvidence]) -> list[DreamEvidence]:
        out: list[DreamEvidence] = []
        seen: set[str] = set()
        for item in evidence:
            if item.id in seen:
                continue
            seen.add(item.id)
            out.append(item)
        return out

    def _dedupe_hypotheses(self, hypotheses: list[DreamHypothesis]) -> list[DreamHypothesis]:
        out: list[DreamHypothesis] = []
        seen: set[str] = set()
        for item in hypotheses:
            if item.id in seen:
                continue
            seen.add(item.id)
            out.append(item)
        return out

    def _record_context(self, report: DreamReport, applied_reports: list[EvolutionReport]) -> None:
        summary = f"Dream {report.dream_id}: insights={len(report.insights)} applied={report.applied} mode={report.mode}"
        meta: dict[str, Any] = {
            "dream_id": report.dream_id,
            "report_path": report.report_path,
            "inspected": report.inspected,
            "applied_fingerprints": [item.fingerprint for item in applied_reports],
        }
        self.agent.context.add("summary", summary, role="system", meta=meta)

    def _title_for_hypothesis(self, hypothesis: DreamHypothesis) -> str:
        mapping = {
            "tool_failure": "Hypothesis: harden failed tool patterns",
            "safety": "Hypothesis: tune guardrail workflow",
            "quality": "Hypothesis: improve answer quality",
            "workflow": "Hypothesis: strengthen completion workflow",
            "verification": "Hypothesis: add verification habit",
        }
        return mapping.get(hypothesis.category, "Hypothesis: distill a reusable behavior")

    def _recommendation_for(self, proposal: EvolutionProposal) -> str:
        if proposal.source == "eval":
            return "Add or update a lesson/skill, then rerun the failing eval report to confirm recovery."
        if proposal.source == "trace":
            return "Apply the proposal only if evidence matches the current workflow; verify on the next similar run."
        return "Review the insight and convert it into a specific checklist before applying."
