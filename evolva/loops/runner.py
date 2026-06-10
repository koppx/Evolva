from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from evolva.agent.dream import DreamEngine
from evolva.loops.registry import LoopRegistry
from evolva.loops.spec import LoopGate, LoopPhase, LoopPhaseResult, LoopRunResult, LoopSpec
from evolva.tools.base import ToolResult


class LoopRunner:
    """Execute Evolva loops as auditable phase graphs.

    A loop is intentionally higher-level than a workflow: it names a repeatable
    agent practice, runs deterministic phases, evaluates gates, records trace
    evidence, and exposes outputs that Dream/Eval can consume later.
    """

    def __init__(self, agent: Any, *, loops_dir: Path | None = None):
        self.agent = agent
        self.registry = LoopRegistry(loops_dir or agent.config.loops_dir)
        self.runs_dir = agent.config.loop_runs_dir
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def list_specs(self) -> list[LoopSpec]:
        return self.registry.list_specs()

    def load(self, identifier: str) -> LoopSpec:
        return self.registry.load(identifier)

    def run(self, identifier: str | LoopSpec) -> LoopRunResult:
        spec = self.load(identifier) if isinstance(identifier, str) else identifier
        result = LoopRunResult.new(spec.id)
        outputs: dict[str, str] = {}
        gates_by_phase: dict[str, list[LoopGate]] = {}
        for gate in spec.gates:
            gates_by_phase.setdefault(gate.after, []).append(gate)
        try:
            order = spec.validate_order()
            phases = {phase.id: phase for phase in spec.phases}
        except ValueError as exc:
            result.status = "planning_failed"
            result.ended_at = time.time()
            result.phase_results.append(LoopPhaseResult("planning", "planner", False, str(exc), result.started_at, result.ended_at))
            return self._persist(result)

        self.agent.tracer.event("loop_start", {"run_id": result.run_id, "loop": spec.to_dict(), "order": order})
        for phase_id in order:
            phase = phases[phase_id]
            phase_result = self._run_phase(phase, outputs)
            phase_result.gate_results = [self._evaluate_gate(gate, phase_result) for gate in gates_by_phase.get(phase_id, [])]
            if any(not item.get("ok") for item in phase_result.gate_results):
                phase_result.ok = False
            result.phase_results.append(phase_result)
            outputs[phase.id] = phase_result.output
            self.agent.tracer.event("loop_phase", {"run_id": result.run_id, "loop_id": spec.id, "phase": phase_result.to_dict()})
            self.agent.context.add(
                "artifact",
                f"Loop {spec.id} phase {phase.id} ok={phase_result.ok}\n{phase_result.output[:1000]}",
                meta={"loop_id": spec.id, "loop_run_id": result.run_id, "phase_id": phase.id},
            )
            if not phase_result.ok and not phase.continue_on_error:
                result.status = "failed"
                break
        else:
            result.status = "completed"
        result.outputs = outputs
        result.ok = result.status == "completed" and all(item.ok for item in result.phase_results)
        if result.ok:
            result.status = "completed"
        elif result.status == "completed":
            result.status = "completed_with_gate_failures"
        result.artifacts = list(spec.artifacts)
        result.ended_at = time.time()
        self.agent.tracer.event("loop_end", {"run": result.to_dict()})
        return self._persist(result)

    def _run_phase(self, phase: LoopPhase, outputs: dict[str, str]) -> LoopPhaseResult:
        started = time.time()
        try:
            if phase.type == "tool":
                if not phase.tool:
                    tool_result = ToolResult(False, "Loop tool phase is missing `tool`")
                else:
                    tool_result = self.agent._call_tool(phase.tool, self._render(phase.args, outputs))
                ok = tool_result.ok
                output = tool_result.output
            elif phase.type == "agent":
                prompt = str(self._render(phase.prompt, outputs))
                turn = self.agent.chat(prompt)
                ok = not turn.failed_tools
                output = turn.answer
            elif phase.type == "role":
                role = phase.role or "planner"
                task = str(self._render(phase.prompt, outputs))
                tool_result = self.agent._call_tool("delegate_agent", {"role": role, "task": task, "context_text": json.dumps(outputs, ensure_ascii=False)})
                ok = tool_result.ok
                output = tool_result.output
            elif phase.type == "dream":
                ok, output = self._run_dream_phase(phase, outputs)
            else:
                ok, output = False, f"Unknown loop phase type: {phase.type}"
        except Exception as exc:
            ok, output = False, f"Loop phase error: {exc}"
        return LoopPhaseResult(phase.id, phase.type, ok, output, started, time.time())

    def _run_dream_phase(self, phase: LoopPhase, outputs: dict[str, str]) -> tuple[bool, str]:
        engine = DreamEngine(self.agent)
        args = self._render(phase.args, outputs)
        action = str(args.get("action") or phase.action or "run")
        # Raw JSON specs may carry action outside args. Preserve compatibility.
        if not action or action == "None":
            action = "run"
        limit = int(args.get("limit", 20))
        if action in {"backlog", "candidates", "status"}:
            return True, engine.render_backlog(limit=limit)
        if action == "verify":
            results = engine.verify_backlog(limit=limit, promote=bool(args.get("promote", False)))
            return all(item.ok for item in results), engine.render_verification(results)
        report = engine.run(trace_limit=limit, apply=bool(args.get("apply", False)), min_confidence=args.get("min_confidence"))
        return True, engine.render(report)

    def _evaluate_gate(self, gate: LoopGate, phase_result: LoopPhaseResult) -> dict[str, Any]:
        if gate.type in {"phase_success", "command_success"}:
            return {"gate": gate.type, "after": gate.after, "ok": phase_result.ok}
        if gate.type == "output_contains":
            ok = bool(gate.expected_contains and gate.expected_contains in phase_result.output)
            return {"gate": gate.type, "after": gate.after, "ok": ok, "expected_contains": gate.expected_contains}
        return {"gate": gate.type, "after": gate.after, "ok": False, "reason": "unknown gate type"}

    def _render(self, value: Any, outputs: dict[str, str]) -> Any:
        if isinstance(value, str):
            rendered = value
            for key, output in outputs.items():
                rendered = rendered.replace("{{" + key + "}}", str(output))
            return rendered
        if isinstance(value, list):
            return [self._render(item, outputs) for item in value]
        if isinstance(value, dict):
            return {key: self._render(item, outputs) for key, item in value.items()}
        return value

    def _persist(self, result: LoopRunResult) -> LoopRunResult:
        path = self.runs_dir / f"{result.run_id}.json"
        result.path = str(path)
        path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return result


def render_loop_specs(specs: list[LoopSpec]) -> str:
    lines = ["Loops"]
    for spec in specs:
        phase_count = len(spec.phases)
        lines.append(f"- {spec.id}: {spec.name} ({phase_count} phases)")
        if spec.description:
            lines.append(f"  {spec.description}")
    return "\n".join(lines)


def render_loop_result(result: LoopRunResult) -> str:
    lines = [
        f"Loop run: {result.run_id}",
        f"- Loop: {result.loop_id}",
        f"- Status: {result.status}",
        f"- Duration: {result.duration_ms} ms",
    ]
    for phase in result.phase_results:
        gate_text = ""
        if phase.gate_results:
            gate_text = " gates=" + ",".join(f"{item.get('gate')}:{'ok' if item.get('ok') else 'fail'}" for item in phase.gate_results)
        lines.append(f"- [{phase.phase_id}/{phase.type}] ok={phase.ok} duration={phase.duration_ms}ms{gate_text}")
        if phase.output:
            lines.append("  " + " ".join(phase.output.split())[:500])
    if result.path:
        lines.append(f"- Report: {result.path}")
    return "\n".join(lines)
