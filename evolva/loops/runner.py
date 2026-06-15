from __future__ import annotations

import json
import shlex
import time
from dataclasses import dataclass, field
from hashlib import sha256
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

    def run(self, identifier: str | LoopSpec, *, resume: bool = False) -> LoopRunResult:
        spec = self.load(identifier) if isinstance(identifier, str) else identifier
        result = LoopRunResult.new(spec.id)
        result.spec_fingerprint = loop_spec_fingerprint(spec)
        validation = validate_loop_spec(spec, agent=self.agent, strict_policy=True)
        if not validation.ok:
            result.status = "validation_failed"
            result.ended_at = time.time()
            result.phase_results.append(LoopPhaseResult("validation", "validator", False, "\n".join(validation.errors), result.started_at, result.ended_at))
            return self._persist(result)
        owns_trace = self.agent.tracer.current is None
        if owns_trace:
            result.trace_run_id = self.agent.tracer.start(
                f"loop:{spec.id}",
                meta={"runtime": "loop", "loop_id": spec.id, "loop_version": spec.version},
            )
        else:
            result.trace_run_id = self.agent.tracer.current_run_id
        outputs: dict[str, str] = {}
        gates_by_phase: dict[str, list[LoopGate]] = {}
        for gate in spec.gates:
            gates_by_phase.setdefault(gate.after, []).append(gate)
        budget = LoopExecutionBudget.from_spec(spec)
        try:
            order = spec.validate_order()
            phases = {phase.id: phase for phase in spec.phases}
            result.phase_fingerprints = {phase.id: loop_phase_fingerprint(phase) for phase in spec.phases}
        except ValueError as exc:
            result.status = "planning_failed"
            result.ended_at = time.time()
            result.phase_results.append(LoopPhaseResult("planning", "planner", False, str(exc), result.started_at, result.ended_at))
            self.agent.tracer.event("loop_planning_failed", {"run_id": result.run_id, "loop_id": spec.id, "error": str(exc)})
            if owns_trace:
                self.agent.tracer.end(str(exc), status=result.status)
            return self._persist(result)

        self.agent.tracer.event("loop_start", {"run_id": result.run_id, "loop": spec.to_dict(), "order": order})
        resume_state = self._load_resume_state(spec) if resume else None
        if resume_state:
            resume_outputs = self._compatible_resume_outputs(resume_state, result.phase_fingerprints)
            self.agent.tracer.event("loop_resume", {"run_id": result.run_id, "from": resume_state.get("path"), "completed_phases": sorted(resume_outputs)})
            outputs.update(resume_outputs)
        for phase_id in order:
            budget_error = budget.check_before_phase()
            if budget_error:
                result.status = "budget_exceeded"
                result.phase_results.append(self._budget_phase_result(phase_id, budget_error, result.started_at))
                self.agent.tracer.event("loop_budget_exceeded", {"run_id": result.run_id, "loop_id": spec.id, "phase": phase_id, "reason": budget_error})
                break
            phase = phases[phase_id]
            if resume_state and phase_id in outputs:
                phase_result = LoopPhaseResult(
                    phase.id,
                    phase.type,
                    True,
                    outputs[phase_id],
                    result.started_at,
                    result.started_at,
                    attempts=0,
                    attempt_results=[{"attempt": 0, "ok": True, "resumed": True, "source_run_id": resume_state.get("run_id", "")}],
                )
                result.phase_results.append(phase_result)
                self.agent.tracer.event("loop_phase_resumed", {"run_id": result.run_id, "loop_id": spec.id, "phase": phase_result.to_dict()})
                continue
            phase_result = self._run_phase(phase, outputs, spec, budget)
            if phase_result.ok:
                for gate in gates_by_phase.get(phase_id, []):
                    budget_error = budget.check_before_gate(gate)
                    if budget_error:
                        phase_result.gate_results.append({"gate": gate.type, "after": gate.after, "ok": False, "reason": budget_error})
                        phase_result.ok = False
                        break
                    gate_result = self._evaluate_gate(gate, phase_result, outputs, spec, budget)
                    phase_result.gate_results.append(gate_result)
            if any(not item.get("ok") for item in phase_result.gate_results):
                phase_result.ok = False
            result.phase_results.append(phase_result)
            outputs[phase.id] = phase_result.output
            result.artifact_records.extend(phase_result.artifacts)
            self.agent.tracer.event("loop_phase", {"run_id": result.run_id, "loop_id": spec.id, "phase": phase_result.to_dict()})
            self.agent.context.add(
                "artifact",
                f"Loop {spec.id} phase {phase.id} ok={phase_result.ok}\n{phase_result.output[:1000]}",
                meta={"loop_id": spec.id, "loop_run_id": result.run_id, "phase_id": phase.id},
            )
            budget_error = budget.check_after_phase(result)
            if budget_error:
                result.status = "budget_exceeded"
                self.agent.tracer.event("loop_budget_exceeded", {"run_id": result.run_id, "loop_id": spec.id, "phase": phase_id, "reason": budget_error})
                break
            if budget.last_error:
                result.status = "budget_exceeded"
                self.agent.tracer.event("loop_budget_exceeded", {"run_id": result.run_id, "loop_id": spec.id, "phase": phase_id, "reason": budget.last_error})
                break
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
        if owns_trace:
            self.agent.tracer.end(render_loop_result(result), status=result.status)
        return self._persist(result)

    def _budget_phase_result(self, phase_id: str, reason: str, started_at: float) -> LoopPhaseResult:
        ended_at = time.time()
        return LoopPhaseResult(phase_id, "budget", False, f"Loop execution budget exceeded: {reason}", started_at, ended_at, attempts=0)

    def _run_phase(self, phase: LoopPhase, outputs: dict[str, str], spec: LoopSpec, budget: "LoopExecutionBudget") -> LoopPhaseResult:
        started = time.time()
        attempts: list[dict[str, Any]] = []
        max_attempts = max(1, phase.retries + 1)
        final_ok = False
        final_output = ""
        final_artifacts: list[dict[str, Any]] = []
        final_ended = started
        for attempt in range(1, max_attempts + 1):
            attempt_started = time.time()
            budget_error = budget.check_before_attempt(phase)
            if budget_error:
                ok, output, artifacts = False, f"Loop execution budget exceeded: {budget_error}", []
            else:
                ok, output, artifacts = self._run_phase_once(phase, outputs, spec, budget)
            attempt_ended = time.time()
            attempts.append(
                {
                    "attempt": attempt,
                    "ok": ok,
                    "output": output[:4000],
                    "started_at": attempt_started,
                    "ended_at": attempt_ended,
                    "duration_ms": int((attempt_ended - attempt_started) * 1000),
                }
            )
            final_ok = ok
            final_output = output
            final_artifacts = artifacts
            final_ended = attempt_ended
            if ok:
                break
            if budget.last_error:
                break
            if attempt < max_attempts:
                self.agent.tracer.event(
                    "loop_phase_retry",
                    {"phase_id": phase.id, "attempt": attempt, "max_attempts": max_attempts, "output": output[:1000]},
                )
        return LoopPhaseResult(
            phase.id,
            phase.type,
            final_ok,
            final_output,
            started,
            final_ended,
            attempts=len(attempts),
            attempt_results=attempts,
            artifacts=final_artifacts,
        )

    def _run_phase_once(self, phase: LoopPhase, outputs: dict[str, str], spec: LoopSpec, budget: "LoopExecutionBudget") -> tuple[bool, str, list[dict[str, Any]]]:
        try:
            if phase.type == "tool":
                budget_error = budget.register_tool_phase(phase)
                if budget_error:
                    return False, f"Loop execution budget exceeded: {budget_error}", []
                if not phase.tool:
                    tool_result = ToolResult(False, "Loop tool phase is missing `tool`")
                else:
                    args = self._phase_args(phase, outputs)
                    if phase.tool == "shell":
                        command_error = self._check_command_allowed(str(args.get("command", "")), [*spec.command_allowlist, *phase.allowlist])
                        if command_error:
                            return False, command_error, []
                    tool_result = self.agent._call_tool(phase.tool, args)
                ok = tool_result.ok
                output = tool_result.output
                artifacts = self._extract_artifacts(tool_result, producer=phase.id)
                budget_error = budget.register_artifacts(artifacts)
                if budget_error:
                    return False, f"{output}\nLoop execution budget exceeded: {budget_error}".strip(), artifacts
            elif phase.type == "agent":
                prompt = str(self._render(phase.prompt, outputs))
                turn = self.agent.chat(prompt)
                ok = not turn.failed_tools
                output = turn.answer
                artifacts = []
            elif phase.type == "role":
                budget_error = budget.register_tool_call("delegate_agent")
                if budget_error:
                    return False, f"Loop execution budget exceeded: {budget_error}", []
                role = phase.role or "planner"
                task = str(self._render(phase.prompt, outputs))
                tool_result = self.agent._call_tool("delegate_agent", {"role": role, "task": task, "context_text": json.dumps(outputs, ensure_ascii=False)})
                ok = tool_result.ok
                output = tool_result.output
                artifacts = self._extract_artifacts(tool_result, producer=phase.id)
                budget_error = budget.register_artifacts(artifacts)
                if budget_error:
                    return False, f"{output}\nLoop execution budget exceeded: {budget_error}".strip(), artifacts
            elif phase.type == "dream":
                ok, output = self._run_dream_phase(phase, outputs)
                artifacts = []
            else:
                ok, output = False, f"Unknown loop phase type: {phase.type}"
                artifacts = []
        except Exception as exc:
            ok, output = False, f"Loop phase error: {exc}"
            artifacts = []
        return ok, output, artifacts

    def _phase_args(self, phase: LoopPhase, outputs: dict[str, str]) -> dict[str, Any]:
        args = self._render(phase.args, outputs)
        if not isinstance(args, dict):
            return {}
        if phase.timeout is not None and phase.tool in {"shell", "python_exec"} and "timeout" not in args:
            args = {**args, "timeout": phase.timeout}
        return args

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

    def _evaluate_gate(self, gate: LoopGate, phase_result: LoopPhaseResult, outputs: dict[str, str], spec: LoopSpec, budget: "LoopExecutionBudget") -> dict[str, Any]:
        if gate.type == "phase_success":
            return {"gate": gate.type, "after": gate.after, "ok": phase_result.ok}
        if gate.type == "command_success":
            if not gate.command:
                return {"gate": gate.type, "after": gate.after, "ok": False, "reason": "missing command"}
            args: dict[str, Any] = {"command": self._render(gate.command, {**outputs, gate.after: phase_result.output}), "cwd": gate.cwd}
            command_error = self._check_command_allowed(str(args["command"]), [*spec.command_allowlist, *gate.allowlist])
            if command_error:
                return {"gate": gate.type, "after": gate.after, "ok": False, "command": args["command"], "cwd": gate.cwd, "reason": command_error}
            if gate.timeout is not None:
                args["timeout"] = gate.timeout
            budget_error = budget.register_command_run()
            if budget_error:
                return {"gate": gate.type, "after": gate.after, "ok": False, "command": args["command"], "cwd": gate.cwd, "reason": budget_error}
            result = self.agent._call_tool("shell", args)
            return {
                "gate": gate.type,
                "after": gate.after,
                "ok": result.ok,
                "command": args["command"],
                "cwd": gate.cwd,
                "output": result.output[:4000],
            }
        if gate.type == "output_contains":
            ok = bool(gate.expected_contains and gate.expected_contains in phase_result.output)
            return {"gate": gate.type, "after": gate.after, "ok": ok, "expected_contains": gate.expected_contains}
        return {"gate": gate.type, "after": gate.after, "ok": False, "reason": "unknown gate type"}

    def _check_command_allowed(self, command: str, allowlist: list[str]) -> str:
        if not command.strip():
            return "shell command is empty"
        allowed, reason = command_matches_allowlist(command, allowlist)
        if not allowed:
            return reason
        policy = self.agent.policy.check_tool("shell", {"command": command})
        if not policy.allowed:
            return f"policy denied command: {policy.reason}"
        return ""

    def _extract_artifacts(self, tool_result: ToolResult, *, producer: str) -> list[dict[str, Any]]:
        if not isinstance(tool_result.data, dict):
            return []
        artifact = tool_result.data.get("artifact")
        if artifact is None:
            return []
        raw_items = artifact if isinstance(artifact, list) else [artifact]
        items: list[dict[str, Any]] = []
        for raw in raw_items:
            if isinstance(raw, dict):
                item = dict(raw)
                item.setdefault("producer_phase", producer)
                items.append(item)
        return items

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

    def _load_resume_state(self, spec: LoopSpec) -> dict[str, Any] | None:
        paths = sorted(self.runs_dir.glob("loop_*.json"), reverse=True)
        for path in paths:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("loop_id") != spec.id or data.get("status") not in {"failed", "completed_with_gate_failures"}:
                continue
            outputs = data.get("outputs") or {}
            if not isinstance(outputs, dict) or not outputs:
                continue
            data["path"] = str(path)
            return data
        return None

    def _compatible_resume_outputs(self, state: dict[str, Any], current_phase_fingerprints: dict[str, str]) -> dict[str, str]:
        outputs = state.get("outputs") or {}
        if not isinstance(outputs, dict):
            return {}
        previous_phase_fingerprints = state.get("phase_fingerprints") or {}
        if isinstance(previous_phase_fingerprints, dict) and previous_phase_fingerprints:
            return {
                str(phase_id): str(output)
                for phase_id, output in outputs.items()
                if previous_phase_fingerprints.get(str(phase_id)) == current_phase_fingerprints.get(str(phase_id))
            }
        return {}


@dataclass
class LoopExecutionBudget:
    """Runtime guardrails for generated and hand-written Loop specs.

    Validation proves the declared limits are well formed; this object enforces
    the limits while the run is in progress so a generated loop cannot silently
    grow into an unbounded execution.
    """

    started_at: float = field(default_factory=time.time)
    max_duration_seconds: int = 0
    max_tool_calls: int = 0
    max_command_runs: int = 0
    max_file_changes: int = 0
    tool_calls: int = 0
    command_runs: int = 0
    file_changes: int = 0
    last_error: str = ""

    @classmethod
    def from_spec(cls, spec: LoopSpec) -> "LoopExecutionBudget":
        limits = spec.execution_limits if isinstance(spec.execution_limits, dict) else {}
        return cls(
            max_duration_seconds=_positive_int(limits.get("max_duration_seconds")),
            max_tool_calls=_positive_int(limits.get("max_tool_calls")),
            max_command_runs=_positive_int(limits.get("max_command_runs")),
            max_file_changes=_positive_int(limits.get("max_file_changes")),
        )

    def check_before_phase(self) -> str:
        return self._record_error(self._duration_error())

    def check_before_attempt(self, phase: LoopPhase) -> str:
        if phase.timeout and self.max_duration_seconds:
            remaining = self.max_duration_seconds - (time.time() - self.started_at)
            if remaining <= 0:
                return self._record_error(f"max_duration_seconds={self.max_duration_seconds} exceeded")
            if phase.timeout > remaining:
                phase.timeout = max(1, int(remaining))
        return self._record_error(self._duration_error())

    def check_before_gate(self, gate: LoopGate) -> str:
        if gate.timeout and self.max_duration_seconds:
            remaining = self.max_duration_seconds - (time.time() - self.started_at)
            if remaining <= 0:
                return self._record_error(f"max_duration_seconds={self.max_duration_seconds} exceeded")
            if gate.timeout > remaining:
                gate.timeout = max(1, int(remaining))
        return self._record_error(self._duration_error())

    def check_after_phase(self, result: LoopRunResult) -> str:
        return self._record_error(self._duration_error() or self._file_change_error(len(result.artifact_records)))

    def register_tool_phase(self, phase: LoopPhase) -> str:
        error = self.register_tool_call(phase.tool or "")
        if error:
            return error
        if phase.tool == "shell":
            return self.register_command_run()
        return ""

    def register_tool_call(self, tool_name: str = "") -> str:
        self.tool_calls += 1
        if self.max_tool_calls and self.tool_calls > self.max_tool_calls:
            return self._record_error(f"max_tool_calls={self.max_tool_calls} exceeded before `{tool_name or 'tool'}`")
        return self._record_error(self._duration_error())

    def register_command_run(self) -> str:
        self.command_runs += 1
        if self.max_command_runs and self.command_runs > self.max_command_runs:
            return self._record_error(f"max_command_runs={self.max_command_runs} exceeded")
        return self._record_error(self._duration_error())

    def register_artifacts(self, artifacts: list[dict[str, Any]]) -> str:
        self.file_changes += sum(1 for item in artifacts if item.get("kind", "file") == "file" and item.get("path"))
        return self._record_error(self._file_change_error(self.file_changes))

    def _duration_error(self) -> str:
        if self.max_duration_seconds and time.time() - self.started_at > self.max_duration_seconds:
            return f"max_duration_seconds={self.max_duration_seconds} exceeded"
        return ""

    def _file_change_error(self, count: int) -> str:
        if self.max_file_changes and count > self.max_file_changes:
            return f"max_file_changes={self.max_file_changes} exceeded"
        return ""

    def _record_error(self, error: str) -> str:
        if error:
            self.last_error = error
        return error


class LoopValidationResult:
    def __init__(self, spec: LoopSpec, *, errors: list[str] | None = None, warnings: list[str] | None = None):
        self.spec = spec
        self.errors = errors or []
        self.warnings = warnings or []

    @property
    def ok(self) -> bool:
        return not self.errors


def command_matches_allowlist(command: str, allowlist: list[str]) -> tuple[bool, str]:
    if not allowlist:
        return False, "shell command requires an explicit allowlist entry"
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return False, f"shell command cannot be parsed: {exc}"
    if not parts:
        return False, "shell command is empty"
    executable = Path(parts[0]).name
    for raw in allowlist:
        pattern = raw.strip()
        if not pattern:
            continue
        if pattern.endswith("*") and command.startswith(pattern[:-1]):
            return True, ""
        if command == pattern or executable == pattern:
            return True, ""
    return False, f"shell command `{command}` is not allowed by allowlist {allowlist}"


def loop_spec_fingerprint(spec: LoopSpec) -> str:
    payload = spec.to_dict()
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def loop_phase_fingerprint(phase: LoopPhase) -> str:
    payload = phase.to_dict()
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def validate_loop_spec(spec: LoopSpec, *, agent: Any | None = None, strict_policy: bool = False) -> LoopValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        order = spec.validate_order()
    except ValueError as exc:
        order = []
        errors.append(str(exc))
    phase_ids = {phase.id for phase in spec.phases}
    known_tools = set(agent.tools.names()) if agent is not None else set()
    known_phase_types = {"tool", "agent", "role", "dream"}
    known_gate_types = {"phase_success", "command_success", "output_contains"}
    if not spec.phases:
        errors.append("loop must define at least one phase")
    limits = spec.execution_limits if isinstance(spec.execution_limits, dict) else {}
    positive_limit_keys = {
        "max_total_phases",
        "max_repair_rounds",
        "max_phase_retries",
        "max_duration_seconds",
        "max_tool_calls",
        "max_command_runs",
        "max_file_changes",
    }
    for key in sorted(set(limits) & positive_limit_keys):
        try:
            value = int(limits[key])
        except (TypeError, ValueError):
            errors.append(f"execution_limits.{key} must be an integer")
            continue
        if value < 0 or (key != "max_repair_rounds" and value == 0):
            errors.append(f"execution_limits.{key} must be positive")
    max_total_phases = int(limits.get("max_total_phases", 0) or 0) if str(limits.get("max_total_phases", "")).isdigit() else 0
    if max_total_phases and len(spec.phases) > max_total_phases:
        errors.append(f"loop has {len(spec.phases)} phases but execution_limits.max_total_phases is {max_total_phases}")
    max_phase_retries = int(limits.get("max_phase_retries", -1)) if str(limits.get("max_phase_retries", "")).lstrip("-").isdigit() else -1
    for phase in spec.phases:
        if phase.type not in known_phase_types:
            errors.append(f"phase {phase.id} has unknown type {phase.type}")
        if phase.type == "tool":
            if not phase.tool:
                errors.append(f"phase {phase.id} is type=tool but missing tool")
            elif agent is not None and phase.tool not in known_tools:
                errors.append(f"phase {phase.id} references unknown tool {phase.tool}")
        if phase.type == "agent" and not phase.prompt:
            errors.append(f"phase {phase.id} is type=agent but missing prompt")
        if phase.type == "role" and not (phase.prompt or phase.args):
            warnings.append(f"role phase {phase.id} has no prompt/task")
        if phase.retries < 0:
            errors.append(f"phase {phase.id} retries must be >= 0")
        if max_phase_retries >= 0 and phase.retries > max_phase_retries:
            errors.append(f"phase {phase.id} retries {phase.retries} exceeds execution_limits.max_phase_retries {max_phase_retries}")
        if phase.timeout is not None and phase.timeout <= 0:
            errors.append(f"phase {phase.id} timeout must be > 0")
        if phase.type == "tool" and phase.tool == "shell":
            args = phase.args if isinstance(phase.args, dict) else {}
            command = str(args.get("command", ""))
            allowed, reason = command_matches_allowlist(command, phase.allowlist or spec.command_allowlist)
            if not allowed:
                errors.append(f"phase {phase.id}: {reason}")
            if strict_policy and agent is not None and command:
                policy = agent.policy.check_tool("shell", {"command": command})
                if not policy.allowed:
                    errors.append(f"phase {phase.id}: policy denied command: {policy.reason}")
    for gate in spec.gates:
        if gate.after and gate.after not in phase_ids:
            errors.append(f"gate references missing phase {gate.after}")
        if gate.type not in known_gate_types:
            errors.append(f"gate after {gate.after} has unknown type {gate.type}")
        if gate.type == "output_contains" and not gate.expected_contains:
            errors.append(f"output_contains gate after {gate.after} is missing expected_contains")
        if gate.type == "command_success":
            if agent is not None and "shell" not in known_tools:
                errors.append(f"command_success gate after {gate.after} requires missing tool shell")
            if not gate.command:
                errors.append(f"command_success gate after {gate.after} is missing command")
            allowed, reason = command_matches_allowlist(gate.command, [*spec.command_allowlist, *gate.allowlist])
            if not allowed:
                errors.append(f"gate after {gate.after}: {reason}")
            if strict_policy and agent is not None and gate.command:
                policy = agent.policy.check_tool("shell", {"command": gate.command})
                if not policy.allowed:
                    errors.append(f"gate after {gate.after}: policy denied command: {policy.reason}")
        if gate.timeout is not None and gate.timeout <= 0:
            errors.append(f"gate after {gate.after} timeout must be > 0")
    return LoopValidationResult(spec, errors=errors, warnings=warnings)


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
    if result.trace_run_id:
        lines.append(f"- Trace: {result.trace_run_id}")
    for phase in result.phase_results:
        gate_text = ""
        if phase.gate_results:
            gate_text = " gates=" + ",".join(f"{item.get('gate')}:{'ok' if item.get('ok') else 'fail'}" for item in phase.gate_results)
        attempt_text = f" attempts={phase.attempts}" if phase.attempts != 1 else ""
        lines.append(f"- [{phase.phase_id}/{phase.type}] ok={phase.ok} duration={phase.duration_ms}ms{attempt_text}{gate_text}")
        if phase.output:
            lines.append("  " + " ".join(phase.output.split())[:500])
    if result.path:
        lines.append(f"- Report: {result.path}")
    return "\n".join(lines)


def render_loop_validation(spec: LoopSpec, *, agent: Any | None = None, strict_policy: bool = False) -> str:
    validation = validate_loop_spec(spec, agent=agent, strict_policy=strict_policy)
    order = [] if validation.errors else spec.validate_order()
    lines = [
        f"Loop validation: {spec.id}",
        f"- Status: {'ok' if validation.ok else 'failed'}",
        f"- Version: {spec.version}",
        f"- Phases: {len(spec.phases)}",
        f"- Gates: {len(spec.gates)}",
        f"- Order: {', '.join(order) or '(none)'}",
    ]
    lines.extend(f"- Warning: {warning}" for warning in validation.warnings)
    lines.extend(f"- Error: {error}" for error in validation.errors)
    if validation.errors:
        raise ValueError("\n".join(validation.errors))
    return "\n".join(lines)
