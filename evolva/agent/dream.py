from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from hashlib import sha256
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
    """A concrete action proposed by the Dream quality loop."""

    id: str
    kind: str
    title: str
    detail: str
    hypothesis_id: str | None = None
    applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DreamVerifier:
    """A deterministic check that must pass before a Dream candidate is promoted."""

    type: str
    command: str = ""
    expected: str = "pass"
    target: str = ""
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DreamCandidate:
    """A staged, evidence-backed improvement candidate.

    Candidates are the durable unit of Dreaming. Unlike a prose insight, a
    candidate carries affected surfaces, a proposed change, a verifier, risk, and
    lifecycle status so Evolva can review, apply, verify, promote, or reject it
    without turning every reflection into long-term memory immediately.
    """

    id: str
    title: str
    category: str
    evidence_ids: list[str] = field(default_factory=list)
    affected_surfaces: list[str] = field(default_factory=list)
    proposed_change: dict[str, Any] = field(default_factory=dict)
    verifier: DreamVerifier | None = None
    risk: str = "medium"
    confidence: float = 0.75
    status: str = "proposed"
    hypothesis_id: str | None = None
    source: str = "dream"
    fingerprint: str = ""
    verification: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        if not self.updated_at:
            self.updated_at = self.created_at
        if self.verifier is not None and not isinstance(self.verifier, DreamVerifier):
            self.verifier = DreamVerifier(**self.verifier)
        if not self.fingerprint:
            material = json.dumps(
                {
                    "category": self.category,
                    "title": self.title,
                    "change": self.proposed_change,
                    "evidence": sorted(self.evidence_ids),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            self.fingerprint = sha256(material.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.verifier is not None:
            data["verifier"] = self.verifier.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DreamCandidate":
        payload = dict(data)
        verifier = payload.get("verifier")
        if isinstance(verifier, dict):
            payload["verifier"] = DreamVerifier(**verifier)
        return cls(**payload)


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
    candidates: list[DreamCandidate] = field(default_factory=list)
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
        data["candidates"] = [item.to_dict() for item in self.candidates]
        data["insights"] = [insight.to_dict() for insight in self.insights]
        return data


@dataclass
class DreamVerificationResult:
    """Result of checking one staged Dream candidate against its verifier."""

    candidate_id: str
    ok: bool
    verifier_type: str
    status: str
    detail: str
    checked_at: str = ""

    def __post_init__(self) -> None:
        if not self.checked_at:
            self.checked_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DreamBacklog:
    """Persistent index for Dream candidates and their lifecycle."""

    version: int = 1
    candidates: list[DreamCandidate] = field(default_factory=list)
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "updated_at": self.updated_at,
            "candidates": [item.to_dict() for item in self.candidates],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DreamBacklog":
        return cls(
            version=int(data.get("version", 1)),
            updated_at=str(data.get("updated_at", "")),
            candidates=[DreamCandidate.from_dict(item) for item in data.get("candidates", [])],
        )


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
        self.backlog_path = self.dreams_dir / "backlog.json"

    def run(
        self,
        *,
        trace_limit: int = 20,
        eval_report: Path | None = None,
        apply: bool = False,
        min_confidence: float | None = None,
    ) -> DreamReport:
        """Analyze recent evidence and optionally apply high-confidence improvements.

        This is an Evolva-native Dream quality loop: collect local evidence, generate
        hypotheses, critique them with deterministic drift guards, plan actions,
        and optionally promote only safe/high-confidence findings into the
        self-evolution layer. The loop stays local-first and records every
        candidate with the verifier needed for later regression confirmation.
        """
        min_confidence = min_confidence if min_confidence is not None else self.APPLY_CONFIDENCE_THRESHOLD
        trace_analysis = TraceEvolutionAnalyzer(self.agent.tracer).analyze(limit=trace_limit)
        eval_analysis = EvalEvolutionAnalyzer(self.agent.config.eval_results_dir).analyze_file(eval_report)
        status = self.agent.evolution.status(recent=8)

        proposals = self._dedupe_proposals(trace_analysis.proposals + eval_analysis.proposals)
        evidence = self._collect_evidence(trace_analysis, eval_analysis, status, proposals)
        hypotheses = self._generate_hypotheses(proposals, evidence, status)
        rejections, accepted = self._critique_hypotheses(hypotheses, evidence, min_confidence=min_confidence)
        candidates = self._generate_candidates(hypotheses, accepted, evidence, proposals)
        candidates = self._merge_backlog(candidates).candidates
        actions = self._plan_actions(hypotheses, accepted, candidates=candidates, apply=apply)

        insights = [self._insight_from_hypothesis(item, evidence) for item in hypotheses]
        insights.extend(self._status_insights(status, proposals))
        insights = self._dedupe_insights(insights)

        applied_reports: list[EvolutionReport] = []
        require_verification = bool(getattr(self.agent.config, "dream_require_verification", True))
        if apply and not require_verification:
            accepted_ids = {item.id for item in accepted}
            applicable = [
                proposal
                for proposal in proposals
                if proposal.confidence >= min_confidence and f"hyp_{proposal.id}" in accepted_ids
            ]
            applied_reports = apply_proposals(self.agent.evolution, applicable)
            for action in actions:
                if action.kind == "stage_lesson" and action.hypothesis_id in accepted_ids:
                    action.applied = True
            applied_hypotheses = {f"hyp_{proposal.id}" for proposal in applicable}
            for candidate in candidates:
                if candidate.hypothesis_id in applied_hypotheses:
                    candidate.status = "applied"
                    candidate.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            candidates = self._merge_backlog(candidates).candidates
        elif apply and require_verification:
            for action in actions:
                if action.kind == "stage_lesson":
                    action.kind = "verify_before_promotion"
                    action.title = "Verify candidate before promotion"
                    action.detail += " Verification is required before writing Memory / Skill."

        report = DreamReport(
            dream_id=time.strftime("dream_%Y%m%d_%H%M%S"),
            generated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            inspected={
                "traces": trace_analysis.inspected,
                "eval_results": eval_analysis.inspected,
                "lessons": int(status.get("total_lessons", 0)),
                "proposals": len(proposals),
            },
            stages=["collect", "hypothesize", "critique", "candidate", "verify", "apply" if apply else "archive"],
            evidence=evidence,
            hypotheses=hypotheses,
            actions=actions,
            candidates=candidates,
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
            f"- Candidates: {len(report.candidates)}",
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
        if report.candidates:
            lines.append("Candidates:")
            for candidate in report.candidates[:8]:
                verifier = candidate.verifier.type if candidate.verifier else "missing-verifier"
                surfaces = ",".join(candidate.affected_surfaces) or "unknown"
                lines.append(
                    f"- {candidate.id} [{candidate.status}/{candidate.risk}/{candidate.confidence:.2f}] "
                    f"{candidate.title} surfaces={surfaces} verifier={verifier}"
                )
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

    def _generate_candidates(
        self,
        hypotheses: list[DreamHypothesis],
        accepted: list[DreamHypothesis],
        evidence: list[DreamEvidence],
        proposals: list[EvolutionProposal],
    ) -> list[DreamCandidate]:
        """Create staged improvement candidates from accepted hypotheses."""
        accepted_ids = {item.id for item in accepted}
        proposal_by_hypothesis = {f"hyp_{proposal.id}": proposal for proposal in proposals}
        evidence_by_id = {item.id: item for item in evidence}
        candidates: list[DreamCandidate] = []
        for hypothesis in hypotheses:
            if hypothesis.id not in accepted_ids:
                continue
            verifier = self._verifier_for(hypothesis, proposal_by_hypothesis.get(hypothesis.id))
            if verifier is None:
                continue
            candidate = DreamCandidate(
                id=f"cand_{hypothesis.id.removeprefix('hyp_')}",
                title=self._title_for_hypothesis(hypothesis),
                category=hypothesis.category,
                evidence_ids=hypothesis.evidence_ids,
                affected_surfaces=self._affected_surfaces(hypothesis),
                proposed_change={
                    "kind": "evolution_lesson",
                    "feedback": hypothesis.proposed_feedback,
                    "category": hypothesis.category,
                    "trigger": f"dream:{hypothesis.source}",
                    "evidence_refs": [ref for ev_id in hypothesis.evidence_ids for ref in evidence_by_id.get(ev_id, DreamEvidence(ev_id, "", "", "")).refs[:5]],
                },
                verifier=verifier,
                risk=self._risk_for(hypothesis),
                confidence=hypothesis.confidence,
                status="accepted",
                hypothesis_id=hypothesis.id,
                source=hypothesis.source,
            )
            candidates.append(candidate)
        return self._dedupe_candidates(candidates)

    def _plan_actions(
        self,
        hypotheses: list[DreamHypothesis],
        accepted: list[DreamHypothesis],
        *,
        candidates: list[DreamCandidate],
        apply: bool,
    ) -> list[DreamAction]:
        accepted_ids = {item.id for item in accepted}
        candidate_by_hypothesis = {item.hypothesis_id: item for item in candidates}
        actions: list[DreamAction] = []
        for item in hypotheses:
            if item.id in accepted_ids:
                candidate = candidate_by_hypothesis.get(item.id)
                kind = "stage_lesson" if apply else "review_candidate"
                title = "Stage candidate for promotion" if apply else "Review candidate before staging"
                verifier = candidate.verifier.type if candidate and candidate.verifier else "missing-verifier"
                detail = (item.apply_reason or "Review this hypothesis against its evidence before promotion.") + f" Verifier: {verifier}."
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

    def load_backlog(self) -> DreamBacklog:
        """Load the persistent Dream candidate backlog."""
        if not self.backlog_path.exists():
            return DreamBacklog()
        try:
            return DreamBacklog.from_dict(json.loads(self.backlog_path.read_text(encoding="utf-8")))
        except Exception:
            return DreamBacklog()

    def write_backlog(self, backlog: DreamBacklog) -> Path:
        """Persist the Dream candidate backlog."""
        backlog.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.backlog_path.write_text(json.dumps(backlog.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return self.backlog_path

    def render_backlog(self, *, limit: int = 20) -> str:
        """Render the Dream backlog as a compact status view."""
        backlog = self.load_backlog()
        rows = backlog.candidates[-limit:]
        counts: dict[str, int] = {}
        for item in backlog.candidates:
            counts[item.status] = counts.get(item.status, 0) + 1
        lines = ["Dream backlog", "- Total candidates: " + str(len(backlog.candidates))]
        if counts:
            lines.append("- Status: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        for item in rows:
            verifier = item.verifier.type if item.verifier else "missing-verifier"
            lines.append(f"- {item.id} [{item.status}/{item.risk}/{item.confidence:.2f}] {item.title} verifier={verifier}")
        if not rows:
            lines.append("- No candidates yet. Run /dream after collecting traces or eval reports.")
        return "\n".join(lines)

    def render_status(self) -> str:
        """Render production-facing Dream gate and promotion status."""
        backlog = self.load_backlog()
        counts: dict[str, int] = {}
        for item in backlog.candidates:
            counts[item.status] = counts.get(item.status, 0) + 1
        pending = counts.get("accepted", 0) + counts.get("applied", 0)
        verified = counts.get("verified", 0)
        promoted = counts.get("promoted", 0)
        gate_required = bool(getattr(self.agent.config, "dream_require_verification", True))
        lines = [
            "Dream status",
            f"- Verification gate: {'required' if gate_required else 'legacy immediate apply'}",
            f"- Backlog: total={len(backlog.candidates)} pending_verification={pending} verified={verified} promoted={promoted}",
        ]
        if counts:
            lines.append("- Status counts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        if verified:
            lines.append("- Next: run /dream verify --promote to promote verified candidates.")
        elif pending:
            lines.append("- Next: run /dream verify before promotion.")
        else:
            lines.append("- Next: run /dream after collecting trace or eval evidence.")
        if backlog.updated_at:
            lines.append(f"- Updated: {backlog.updated_at}")
        return "\n".join(lines)

    def verify_backlog(
        self,
        *,
        tasks_path: Path | None = None,
        limit: int = 20,
        promote: bool = False,
    ) -> list[DreamVerificationResult]:
        """Verify staged candidates and optionally promote verified lessons.

        Eval verifiers run through the local JSONL eval harness when a task file is
        available. Trace-pattern verifiers inspect the latest trace analysis and
        pass when the candidate's category no longer appears as a pending trace
        proposal. Manual-review verifiers stay explicit and never auto-pass.
        """
        backlog = self.load_backlog()
        candidates = [item for item in backlog.candidates if item.status in {"accepted", "applied", "verified"}]
        candidates = candidates[-limit:]
        trace_analysis: EvolutionAnalysis | None = None
        eval_pass_cache: dict[Path, bool] = {}
        results: list[DreamVerificationResult] = []

        for candidate in candidates:
            verifier = candidate.verifier
            if verifier is None:
                result = DreamVerificationResult(candidate.id, False, "missing", candidate.status, "Candidate has no verifier.")
            elif verifier.type == "eval":
                eval_path = tasks_path or self._default_eval_tasks_path()
                if eval_path is None or not eval_path.exists():
                    result = DreamVerificationResult(candidate.id, False, verifier.type, candidate.status, "No eval task file available for verification.")
                else:
                    eval_path = eval_path.resolve()
                    if eval_path not in eval_pass_cache:
                        from evolva.eval.harness import EvalHarness

                        harness = EvalHarness(self.agent.config, assume_yes=True)
                        eval_pass_cache[eval_path] = all(item.passed for item in harness.run_file(eval_path))
                    ok = eval_pass_cache[eval_path]
                    result = DreamVerificationResult(
                        candidate.id,
                        ok,
                        verifier.type,
                        "verified" if ok else candidate.status,
                        f"Eval verifier {'passed' if ok else 'failed'}: {eval_path}",
                    )
            elif verifier.type == "trace_pattern":
                if trace_analysis is None:
                    trace_analysis = TraceEvolutionAnalyzer(self.agent.tracer).analyze(limit=limit)
                pending_categories = {proposal.category for proposal in trace_analysis.proposals}
                ok = candidate.category not in pending_categories
                result = DreamVerificationResult(
                    candidate.id,
                    ok,
                    verifier.type,
                    "verified" if ok else candidate.status,
                    "Trace pattern absent in latest window." if ok else "Trace pattern still appears in latest window.",
                )
            else:
                result = DreamVerificationResult(candidate.id, False, verifier.type, candidate.status, verifier.expected or "Manual review required.")

            candidate.verification = result.to_dict()
            candidate.updated_at = result.checked_at
            if result.ok and self._status_rank(result.status) > self._status_rank(candidate.status):
                candidate.status = result.status
            if promote and candidate.status == "verified":
                promoted_report = self._promote_candidate(candidate)
                candidate.status = "promoted"
                candidate.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                candidate.verification["promoted_at"] = candidate.updated_at
                if promoted_report is not None:
                    candidate.verification["evolution_fingerprint"] = promoted_report.fingerprint
                    result.detail += f"; promoted_at={candidate.updated_at}"
            results.append(result)

        if candidates:
            self.write_backlog(backlog)
        return results

    def render_verification(self, results: list[DreamVerificationResult]) -> str:
        """Render Dream verifier results for CLI/TUI users."""
        passed = sum(1 for item in results if item.ok)
        lines = [f"Dream verification: {passed}/{len(results)} passed"]
        for item in results:
            mark = "PASS" if item.ok else "WAIT"
            lines.append(f"- {mark} {item.candidate_id} verifier={item.verifier_type} status={item.status} detail={item.detail}")
        if not results:
            lines.append("- No accepted/applied candidates to verify.")
        return "\n".join(lines)

    def _merge_backlog(self, candidates: list[DreamCandidate]) -> DreamBacklog:
        backlog = self.load_backlog()
        by_fingerprint = {item.fingerprint: item for item in backlog.candidates}
        changed = False
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        incoming_fingerprints: set[str] = set()
        for candidate in candidates:
            incoming_fingerprints.add(candidate.fingerprint)
            existing = by_fingerprint.get(candidate.fingerprint)
            if existing is None:
                backlog.candidates.append(candidate)
                by_fingerprint[candidate.fingerprint] = candidate
                changed = True
                continue
            existing.updated_at = now
            existing.confidence = max(existing.confidence, candidate.confidence)
            existing.evidence_ids = sorted(set(existing.evidence_ids) | set(candidate.evidence_ids))
            existing.verification = candidate.verification or existing.verification
            if self._status_rank(candidate.status) > self._status_rank(existing.status):
                existing.status = candidate.status
            changed = True
        if changed:
            self.write_backlog(backlog)
        elif not self.backlog_path.exists():
            self.write_backlog(backlog)
        if incoming_fingerprints:
            return DreamBacklog(
                version=backlog.version,
                updated_at=backlog.updated_at,
                candidates=[item for item in backlog.candidates if item.fingerprint in incoming_fingerprints],
            )
        return backlog

    def _status_rank(self, status: str) -> int:
        return {"rejected": -1, "proposed": 0, "accepted": 1, "applied": 2, "verified": 3, "promoted": 4}.get(status, 0)

    def _promote_candidate(self, candidate: DreamCandidate) -> EvolutionReport | None:
        change = candidate.proposed_change or {}
        if change.get("kind") != "evolution_lesson":
            return None
        feedback = str(change.get("feedback") or "").strip()
        if not feedback:
            return None
        evidence = [*candidate.evidence_ids, *[str(item) for item in change.get("evidence_refs", [])]]
        return self.agent.evolution.evolve(
            feedback,
            trigger=f"dream_promote:{candidate.source}",
            category=candidate.category,
            evidence=evidence,
            confidence=candidate.confidence,
        )

    def _default_eval_tasks_path(self) -> Path | None:
        path = self.agent.config.root / "evals" / "tasks" / "smoke.jsonl"
        return path if path.exists() else None

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

    def _dedupe_candidates(self, candidates: list[DreamCandidate]) -> list[DreamCandidate]:
        out: list[DreamCandidate] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate.fingerprint in seen:
                continue
            seen.add(candidate.fingerprint)
            out.append(candidate)
        return out

    def _verifier_for(self, hypothesis: DreamHypothesis, proposal: EvolutionProposal | None) -> DreamVerifier | None:
        if hypothesis.source == "eval":
            target = "latest eval report"
            if proposal is not None and proposal.task:
                target = proposal.task
            return DreamVerifier(
                type="eval",
                command="evolva eval evals/tasks/smoke.jsonl --yes",
                expected="pass",
                target=target,
                rationale="Eval-derived Dream candidates must be verified against the regression harness before durable promotion.",
            )
        if hypothesis.source == "trace":
            return DreamVerifier(
                type="trace_pattern",
                expected="failure pattern reduced or absent in the next comparable trace window",
                target=", ".join(hypothesis.evidence_ids),
                rationale="Trace-derived candidates need a later trace window to confirm the failure pattern stopped recurring.",
            )
        return DreamVerifier(
            type="manual_review",
            expected="approved by maintainer after evidence review",
            target=hypothesis.id,
            rationale="Status-derived candidates require human review before becoming durable behavior.",
        )

    def _affected_surfaces(self, hypothesis: DreamHypothesis) -> list[str]:
        surfaces = ["memory", "skill"]
        if hypothesis.source == "eval":
            surfaces.append("eval")
        if hypothesis.source == "trace":
            surfaces.append("trace")
        if hypothesis.category in {"tool_failure", "safety"}:
            surfaces.append("tooling")
        if hypothesis.category in {"workflow", "verification"}:
            surfaces.append("workflow")
        return list(dict.fromkeys(surfaces))

    def _risk_for(self, hypothesis: DreamHypothesis) -> str:
        if hypothesis.category == "safety":
            return "high"
        if hypothesis.confidence >= 0.86 and hypothesis.source == "eval":
            return "low"
        if hypothesis.confidence >= 0.80:
            return "medium"
        return "high"

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
