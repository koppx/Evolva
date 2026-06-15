from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LoopPhase:
    """One deterministic phase inside an Evolva loop."""

    id: str
    type: str = "tool"
    name: str = ""
    tool: str | None = None
    role: str | None = None
    action: str = ""
    prompt: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    continue_on_error: bool = False
    promotion: bool = False
    timeout: int | None = None
    retries: int = 0
    allowlist: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, previous_id: str | None = None, idx: int = 0) -> "LoopPhase":
        phase_id = str(data.get("id") or f"phase_{idx + 1}")
        if "depends_on" in data:
            deps_raw = data.get("depends_on") or []
            deps = [str(deps_raw)] if isinstance(deps_raw, str) else [str(item) for item in deps_raw]
        else:
            deps = [previous_id] if previous_id else []
        return cls(
            id=phase_id,
            type=str(data.get("type", "tool")),
            name=str(data.get("name") or phase_id),
            tool=data.get("tool"),
            role=data.get("role"),
            action=str(data.get("action", "")),
            prompt=str(data.get("prompt") or data.get("task") or ""),
            args=dict(data.get("args") or {}),
            depends_on=deps,
            continue_on_error=bool(data.get("continue_on_error", False)),
            promotion=bool(data.get("promotion", False)),
            timeout=int(data["timeout"]) if data.get("timeout") is not None else None,
            retries=int(data.get("retries", 0)),
            allowlist=[str(item) for item in data.get("allowlist", data.get("command_allowlist", []))],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LoopGate:
    """A quality gate evaluated after a phase completes."""

    after: str
    type: str = "phase_success"
    expected_contains: str = ""
    command: str = ""
    cwd: str = "."
    timeout: int | None = None
    allowlist: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LoopGate":
        return cls(
            after=str(data.get("after") or data.get("phase") or ""),
            type=str(data.get("type", "phase_success")),
            expected_contains=str(data.get("expected_contains", "")),
            command=str(data.get("command", "")),
            cwd=str(data.get("cwd", ".")),
            timeout=int(data["timeout"]) if data.get("timeout") is not None else None,
            allowlist=[str(item) for item in data.get("allowlist", data.get("command_allowlist", []))],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LoopSpec:
    """Portable loop definition used by TUI, CLI, Eval, and Dream."""

    id: str
    name: str = ""
    description: str = ""
    trigger: dict[str, Any] = field(default_factory=lambda: {"type": "manual"})
    phases: list[LoopPhase] = field(default_factory=list)
    gates: list[LoopGate] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    command_allowlist: list[str] = field(default_factory=list)
    execution_limits: dict[str, Any] = field(default_factory=dict)
    version: str = "1"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LoopSpec":
        loop_id = str(data.get("id") or data.get("name") or "loop")
        raw_phases = data.get("phases", data.get("nodes", [])) or []
        phases: list[LoopPhase] = []
        previous_id: str | None = None
        seen: set[str] = set()
        for idx, raw in enumerate(raw_phases):
            phase = LoopPhase.from_dict(dict(raw), previous_id=previous_id, idx=idx)
            if phase.id in seen:
                raise ValueError(f"duplicate loop phase id: {phase.id}")
            seen.add(phase.id)
            phases.append(phase)
            previous_id = phase.id
        phase_ids = {phase.id for phase in phases}
        for phase in phases:
            for dep in phase.depends_on:
                if dep not in phase_ids:
                    raise ValueError(f"phase {phase.id} depends on missing phase {dep}")
        gates = [LoopGate.from_dict(dict(item)) for item in data.get("gates", [])]
        for gate in gates:
            if gate.after and gate.after not in phase_ids:
                raise ValueError(f"gate references missing phase {gate.after}")
        return cls(
            id=loop_id,
            name=str(data.get("name") or loop_id),
            description=str(data.get("description", "")),
            trigger=dict(data.get("trigger") or {"type": "manual"}),
            phases=phases,
            gates=gates,
            artifacts=[str(item) for item in data.get("artifacts", [])],
            command_allowlist=[str(item) for item in data.get("command_allowlist", [])],
            execution_limits=dict(data.get("execution_limits") or {}),
            version=str(data.get("version", "1")),
        )

    @classmethod
    def from_file(cls, path: Path) -> "LoopSpec":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate_order(self) -> list[str]:
        order: list[str] = []
        state: dict[str, str] = {}
        phases = {phase.id: phase for phase in self.phases}

        def visit(phase_id: str, stack: list[str]) -> None:
            status = state.get(phase_id)
            if status == "done":
                return
            if status == "visiting":
                raise ValueError("loop dependency cycle: " + " -> ".join(stack + [phase_id]))
            state[phase_id] = "visiting"
            for dep in phases[phase_id].depends_on:
                visit(dep, stack + [phase_id])
            state[phase_id] = "done"
            order.append(phase_id)

        for phase in self.phases:
            visit(phase.id, [])
        return order


@dataclass
class LoopPhaseResult:
    """Execution result for a single loop phase."""

    phase_id: str
    type: str
    ok: bool
    output: str = ""
    started_at: float = 0.0
    ended_at: float = 0.0
    gate_results: list[dict[str, Any]] = field(default_factory=list)
    attempts: int = 1
    attempt_results: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def duration_ms(self) -> int:
        if self.started_at and self.ended_at:
            return int((self.ended_at - self.started_at) * 1000)
        return 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["duration_ms"] = self.duration_ms
        return data


@dataclass
class LoopRunResult:
    """Durable loop run summary that can feed Trace, Eval, and Dream."""

    run_id: str
    loop_id: str
    ok: bool
    status: str
    phase_results: list[LoopPhaseResult] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    artifact_records: list[dict[str, Any]] = field(default_factory=list)
    trace_run_id: str = ""
    spec_fingerprint: str = ""
    phase_fingerprints: dict[str, str] = field(default_factory=dict)
    started_at: float = 0.0
    ended_at: float = 0.0
    path: str = ""

    @classmethod
    def new(cls, loop_id: str) -> "LoopRunResult":
        run_id = time.strftime("loop_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
        return cls(run_id=run_id, loop_id=loop_id, ok=False, status="running", started_at=time.time())

    @property
    def duration_ms(self) -> int:
        if self.started_at and self.ended_at:
            return int((self.ended_at - self.started_at) * 1000)
        return 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["phase_results"] = [item.to_dict() for item in self.phase_results]
        data["duration_ms"] = self.duration_ms
        return data
