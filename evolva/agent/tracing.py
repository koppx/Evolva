from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TraceEvent:
    ts: float
    kind: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceRun:
    run_id: str
    started_at: float
    status: str = "running"
    user_input: str = ""
    final_answer: str = ""
    events: list[TraceEvent] = field(default_factory=list)
    ended_at: float | None = None


class TraceRecorder:
    """JSON trace recorder for observability, replay, and diagnostics."""

    def __init__(self, traces_dir: Path, *, enabled: bool = True):
        self.traces_dir = traces_dir
        self.enabled = enabled
        self.current: TraceRun | None = None
        self.traces_dir.mkdir(parents=True, exist_ok=True)

    def start(self, user_input: str, *, meta: dict[str, Any] | None = None) -> str:
        run_id = time.strftime("run_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
        self.current = TraceRun(run_id=run_id, started_at=time.time(), user_input=user_input)
        if meta:
            self.event("run_meta", meta)
        return run_id

    def event(self, kind: str, data: dict[str, Any] | None = None) -> None:
        if not self.enabled or self.current is None:
            return
        self.current.events.append(TraceEvent(ts=time.time(), kind=kind, data=data or {}))

    def end(self, final_answer: str, *, status: str = "completed") -> Path | None:
        if not self.enabled or self.current is None:
            self.current = None
            return None
        self.current.final_answer = final_answer
        self.current.status = status
        self.current.ended_at = time.time()
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
            rows.append(
                {
                    "run_id": data.get("run_id", path.stem),
                    "status": data.get("status", "unknown"),
                    "started_at": data.get("started_at"),
                    "duration_ms": self._duration_ms(data),
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
            f"Status: {data.get('status')}",
            f"Duration: {self._duration_ms(data)} ms",
            f"User: {data.get('user_input', '')}",
            "Events:",
        ]
        for event in data.get("events", []):
            kind = event.get("kind", "event")
            payload = json.dumps(event.get("data", {}), ensure_ascii=False, sort_keys=True)
            lines.append(f"- {kind}: {payload[:1200]}")
        lines.append("Final:")
        lines.append(data.get("final_answer", ""))
        return "\n".join(lines)

    def render_context(self, run_id: str) -> str:
        """Render prompt/context related trace events for debugging context assembly."""
        data = self.load(run_id)
        lines = [
            f"Trace context: {data.get('run_id')}",
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
                lines.append(f"- {kind}: {rendered[:2000]}")
        if not matched:
            lines.append("No context events recorded for this trace.")
        return "\n".join(lines)

    def replay_prompt(self, run_id: str) -> str:
        data = self.load(run_id)
        return str(data.get("user_input", ""))

    def _write(self, path: Path, run: TraceRun) -> None:
        data = asdict(run)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _duration_ms(self, data: dict[str, Any]) -> int | None:
        started = data.get("started_at")
        ended = data.get("ended_at")
        if isinstance(started, (int, float)) and isinstance(ended, (int, float)):
            return int((ended - started) * 1000)
        return None
