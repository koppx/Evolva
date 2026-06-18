from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from evolva.agent.observability import ObservabilitySink
from evolva.agent.redaction import Redactor
from evolva.storage import atomic_write_json


TRACE_SCHEMA_VERSION = "trace.v1"


@dataclass
class TraceEvent:
    """One structured trace event in a run timeline."""

    ts: float
    kind: str
    data: dict[str, Any] = field(default_factory=dict)
    event_id: str = ""
    span_id: str = ""
    parent_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TraceRun:
    """A persisted Evolva execution trace.

    schema_version makes traces explicitly versioned so replay, eval, and Dream
    analysis can evolve without silently breaking older runs.
    """

    run_id: str
    started_at: float
    schema_version: str = TRACE_SCHEMA_VERSION
    status: str = "running"
    user_input: str = ""
    final_answer: str = ""
    events: list[TraceEvent] = field(default_factory=list)
    ended_at: float | None = None
    summary: dict[str, Any] = field(default_factory=dict)


class TraceRecorder:
    """JSON trace recorder for observability, replay, and diagnostics."""

    def __init__(self, traces_dir: Path, *, enabled: bool = True, redactor: Redactor | None = None, observability: ObservabilitySink | None = None):
        self.traces_dir = traces_dir
        self.enabled = enabled
        self.redactor = redactor or Redactor()
        self.observability = observability
        self.current: TraceRun | None = None
        self._event_seq = 0
        self.traces_dir.mkdir(parents=True, exist_ok=True)

    @property
    def current_run_id(self) -> str:
        return self.current.run_id if self.current is not None else ""

    def start(self, user_input: str, *, meta: dict[str, Any] | None = None) -> str:
        run_id = time.strftime("run_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
        self._event_seq = 0
        self.current = TraceRun(run_id=run_id, started_at=time.time(), user_input=user_input)
        if meta:
            self.event("run_meta", meta, parent_id="")
        return run_id

    def event(
        self,
        kind: str,
        data: dict[str, Any] | None = None,
        *,
        span_id: str | None = None,
        parent_id: str | None = None,
    ) -> str | None:
        """Append an event and return its event_id.

        Existing callers can keep using event(kind, data). New callers may pass
        span_id/parent_id to build DAG-like timelines for visualization.
        """

        if not self.enabled or self.current is None:
            return None
        self._event_seq += 1
        event_id = f"evt_{self._event_seq:04d}"
        if span_id is None:
            safe_kind = "".join(ch if ch.isalnum() else "_" for ch in kind.lower()).strip("_") or "event"
            span_id = f"span_{safe_kind}_{self._event_seq:04d}"
        if parent_id is None:
            parent_id = self.current.events[-1].event_id if self.current.events else ""
        event = TraceEvent(
            ts=time.time(),
            kind=kind,
            data=self.redactor.redact_json(data or {}),
            event_id=event_id,
            span_id=span_id,
            parent_id=parent_id,
        )
        self.current.events.append(event)
        self._record_observability(event)
        return event_id

    def end(self, final_answer: str, *, status: str = "completed") -> Path | None:
        if not self.enabled or self.current is None:
            self.current = None
            return None
        self.current.final_answer = self.redactor.redact_text(final_answer)
        self.current.status = status
        self.current.ended_at = time.time()
        self.current.summary = self._summarize_run(self.current)
        path = self.path_for(self.current.run_id)
        self._write(path, self.current)
        self.current = None
        return path

    def path_for(self, run_id: str) -> Path:
        safe = run_id.replace("/", "_").replace("..", "_")
        if safe.endswith(".json"):
            safe = safe[:-5]
        return self.traces_dir / f"{safe}.json"

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in sorted(self.traces_dir.glob("run_*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            summary = data.get("summary") or self._summarize_data(data)
            rows.append(
                {
                    "run_id": data.get("run_id", path.stem),
                    "schema_version": data.get("schema_version", "trace.legacy"),
                    "status": data.get("status", "unknown"),
                    "started_at": data.get("started_at"),
                    "duration_ms": summary.get("duration_ms", self._duration_ms(data)),
                    "event_count": summary.get("event_count", len(data.get("events", []))),
                    "tool_calls": summary.get("tool_calls", 0),
                    "tool_failures": summary.get("tool_failures", 0),
                    "artifacts": summary.get("artifacts", 0),
                    "user_input": data.get("user_input", "")[:120],
                    "path": str(path),
                }
            )
        return rows

    def load(self, run_id: str) -> dict[str, Any]:
        path = self.path_for(run_id)
        if not path.exists() and Path(run_id).exists():
            path = Path(run_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def render(self, run_id: str) -> str:
        data = self.load(run_id)
        lines = [
            f"Trace: {data.get('run_id')}",
            f"Schema: {data.get('schema_version', 'trace.legacy')}",
            f"Status: {data.get('status')}",
            f"Duration: {self._duration_ms(data)} ms",
            f"User: {data.get('user_input', '')}",
            "Events:",
        ]
        for event in data.get("events", []):
            kind = event.get("kind", "event")
            event_id = event.get("event_id", "evt_legacy")
            span_id = event.get("span_id", "")
            parent_id = event.get("parent_id", "")
            payload = json.dumps(event.get("data", {}), ensure_ascii=False, sort_keys=True)
            edge = f" span={span_id}" + (f" parent={parent_id}" if parent_id else "")
            lines.append(f"- {event_id} {kind}{edge}: {payload[:1200]}")
        lines.append("Final:")
        lines.append(data.get("final_answer", ""))
        return "\n".join(lines)

    def render_context(self, run_id: str) -> str:
        """Render prompt/context related trace events for debugging context assembly."""
        data = self.load(run_id)
        lines = [
            f"Trace context: {data.get('run_id')}",
            f"Schema: {data.get('schema_version', 'trace.legacy')}",
            f"User: {data.get('user_input', '')}",
            "Context events:",
        ]
        matched = False
        for event in data.get("events", []):
            kind = event.get("kind", "event")
            payload = event.get("data", {}) or {}
            if kind in {"run_meta", "prompt", "context_write", "auto_evolve"}:
                matched = True
                rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                lines.append(f"- {event.get('event_id', 'evt_legacy')} {kind}: {rendered[:2000]}")
        if not matched:
            lines.append("No context events recorded for this trace.")
        return "\n".join(lines)

    def timeline(self, run_id: str) -> list[dict[str, Any]]:
        """Return a normalized timeline for TUI/HTML visualization."""
        data = self.load(run_id)
        started = data.get("started_at") or 0
        rows: list[dict[str, Any]] = []
        for event in data.get("events", []):
            ts = event.get("ts") or started
            rows.append(
                {
                    "event_id": event.get("event_id", ""),
                    "span_id": event.get("span_id", ""),
                    "parent_id": event.get("parent_id", ""),
                    "kind": event.get("kind", "event"),
                    "offset_ms": int((ts - started) * 1000) if started else 0,
                    "data": event.get("data", {}),
                }
            )
        return rows

    def replay_prompt(self, run_id: str) -> str:
        data = self.load(run_id)
        return str(data.get("user_input", ""))

    def _write(self, path: Path, run: TraceRun) -> None:
        data = asdict(run)
        atomic_write_json(path, data)

    def _record_observability(self, event: TraceEvent) -> None:
        if self.observability is None:
            return
        try:
            data = event.data or {}
            if event.kind == "policy_decision":
                allowed = bool(data.get("allowed", True))
                tags = {"tool": data.get("tool", ""), "risk": data.get("risk", ""), "allowed": str(allowed).lower()}
                fields = {"reason": data.get("reason", ""), "audit_tags": data.get("audit_tags", [])}
                self.observability.record("policy.decision", tags=tags, fields=fields)
                if not allowed:
                    self.observability.record("policy.denied", tags={key: value for key, value in tags.items() if key != "allowed"}, fields=fields)
                redactions = data.get("redactions", []) or []
                if redactions:
                    self.observability.record("redaction.hit", value=len(redactions), tags={"tool": data.get("tool", ""), "source": "policy_decision"}, fields={"redactions": redactions})
            elif event.kind == "tool_call":
                ok = bool(data.get("ok", False))
                tags = {"tool": data.get("tool", ""), "ok": str(ok).lower()}
                self.observability.record("tool.call", tags=tags)
                latency = data.get("latency_ms")
                if latency is not None:
                    self.observability.record("tool.latency_ms", value=float(latency), unit="ms", tags=tags)
                if not ok:
                    output = str(data.get("output", ""))
                    self.observability.record("tool.failure", tags={"tool": data.get("tool", "")}, fields={"output": output[:1000]})
                    if "mcp request timed out" in output.lower():
                        self.observability.record("mcp.timeout", tags={"tool": data.get("tool", "")}, fields={"output": output[:1000]})
            elif event.kind == "tool_error":
                error = str(data.get("error", ""))
                self.observability.record("tool.error", tags={"tool": data.get("tool", "")}, fields={"error": error[:1000]})
                if "mcp request timed out" in error.lower():
                    self.observability.record("mcp.timeout", tags={"tool": data.get("tool", "")}, fields={"error": error[:1000]})
            elif event.kind == "artifact_error":
                self.observability.record("artifact.error", tags={"tool": data.get("tool", "")}, fields={"error": str(data.get("error", ""))[:1000]})
        except Exception:
            return

    def _summarize_run(self, run: TraceRun) -> dict[str, Any]:
        data = asdict(run)
        return self._summarize_data(data)

    def _summarize_data(self, data: dict[str, Any]) -> dict[str, Any]:
        events = data.get("events", []) or []
        tool_calls = [event for event in events if event.get("kind") == "tool_call"]
        tool_failures = [event for event in tool_calls if not (event.get("data", {}) or {}).get("ok", False)]
        artifact_events = [event for event in events if event.get("kind") == "artifact"]
        return {
            "event_count": len(events),
            "tool_calls": len(tool_calls),
            "tool_failures": len(tool_failures),
            "artifacts": len(artifact_events),
            "duration_ms": self._duration_ms(data),
            "kinds": sorted({str(event.get("kind", "event")) for event in events}),
        }

    def _duration_ms(self, data: dict[str, Any]) -> int | None:
        started = data.get("started_at")
        ended = data.get("ended_at")
        if isinstance(started, (int, float)) and isinstance(ended, (int, float)):
            return int((ended - started) * 1000)
        return None
