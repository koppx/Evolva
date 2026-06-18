from __future__ import annotations

import operator
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from evolva.storage import append_jsonl, read_jsonl


@dataclass(frozen=True)
class MetricRecord:
    ts: float
    name: str
    value: float = 1.0
    unit: str = "count"
    tags: dict[str, str] = field(default_factory=dict)
    fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AlertRule:
    name: str
    metric: str
    threshold: float = 1.0
    operator: str = ">="
    window_seconds: int = 300
    severity: str = "warning"
    description: str = ""
    tags: dict[str, str] = field(default_factory=dict)
    dedupe_seconds: int = 60

    def matches(self, record: MetricRecord) -> bool:
        if record.name != self.metric:
            return False
        return all(record.tags.get(key) == value for key, value in self.tags.items())


@dataclass(frozen=True)
class AlertEvent:
    ts: float
    rule: str
    severity: str
    metric: str
    value: float
    threshold: float
    operator: str
    window_seconds: int
    description: str
    tags: dict[str, str] = field(default_factory=dict)
    fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_ALERT_RULES = [
    AlertRule("policy-denied-any", "policy.denied", description="A policy decision denied a tool call."),
    AlertRule("tool-failure-any", "tool.failure", description="A tool call returned ok=false."),
    AlertRule("tool-error-any", "tool.error", severity="critical", description="A tool raised an unhandled exception."),
    AlertRule("mcp-timeout-any", "mcp.timeout", severity="critical", description="An MCP request timed out."),
    AlertRule("artifact-error-any", "artifact.error", description="Artifact provenance recording failed."),
]


class ObservabilitySink:
    """Local JSONL metrics and alert sink for production validation hooks."""

    def __init__(
        self,
        metrics_file: Path,
        alerts_file: Path,
        *,
        enabled: bool = True,
        rules: list[AlertRule] | None = None,
    ):
        self.metrics_file = metrics_file
        self.alerts_file = alerts_file
        self.enabled = enabled
        self.rules = list(rules if rules is not None else DEFAULT_ALERT_RULES)
        self.metrics_file.parent.mkdir(parents=True, exist_ok=True)
        self.alerts_file.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        name: str,
        value: float = 1.0,
        *,
        unit: str = "count",
        tags: dict[str, Any] | None = None,
        fields: dict[str, Any] | None = None,
        ts: float | None = None,
    ) -> MetricRecord:
        record = MetricRecord(
            ts=ts or time.time(),
            name=name,
            value=float(value),
            unit=unit,
            tags=_string_tags(tags or {}),
            fields=dict(fields or {}),
        )
        if not self.enabled:
            return record
        append_jsonl(self.metrics_file, record.to_dict())
        for alert in self.evaluate(record):
            append_jsonl(self.alerts_file, alert.to_dict())
        return record

    def evaluate(self, record: MetricRecord) -> list[AlertEvent]:
        events: list[AlertEvent] = []
        for rule in self.rules:
            if not rule.matches(record):
                continue
            value = self.window_sum(rule, now=record.ts)
            if not _compare(rule.operator)(value, rule.threshold):
                continue
            if self._recent_duplicate(rule, record, now=record.ts):
                continue
            events.append(
                AlertEvent(
                    ts=record.ts,
                    rule=rule.name,
                    severity=rule.severity,
                    metric=rule.metric,
                    value=value,
                    threshold=rule.threshold,
                    operator=rule.operator,
                    window_seconds=rule.window_seconds,
                    description=rule.description,
                    tags=record.tags,
                    fields={"record": record.fields},
                )
            )
        return events

    def window_sum(self, rule: AlertRule, *, now: float | None = None) -> float:
        current = now or time.time()
        since = current - max(0, int(rule.window_seconds))
        total = 0.0
        for record in self.recent_metrics(name=rule.metric):
            if record.ts < since:
                continue
            if not all(record.tags.get(key) == value for key, value in rule.tags.items()):
                continue
            total += record.value
        return total

    def recent_metrics(self, *, name: str | None = None, limit: int | None = None) -> list[MetricRecord]:
        rows = []
        for raw in read_jsonl(self.metrics_file):
            try:
                record = MetricRecord(**raw)
            except TypeError:
                continue
            if name is not None and record.name != name:
                continue
            rows.append(record)
        if limit is not None:
            return rows[-limit:]
        return rows

    def recent_alerts(self, *, limit: int | None = None) -> list[AlertEvent]:
        rows = []
        for raw in read_jsonl(self.alerts_file):
            try:
                rows.append(AlertEvent(**raw))
            except TypeError:
                continue
        if limit is not None:
            return rows[-limit:]
        return rows

    def render_metrics(self, *, limit: int = 20) -> str:
        rows = self.recent_metrics(limit=limit)
        if not rows:
            return "No metrics."
        lines = ["Metrics:"]
        for record in rows:
            stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.ts))
            tags = ",".join(f"{key}={value}" for key, value in sorted(record.tags.items()))
            suffix = f" tags={tags}" if tags else ""
            lines.append(f"- {stamp} {record.name}={record.value:g} {record.unit}{suffix}")
        return "\n".join(lines)

    def render_alerts(self, *, limit: int = 20) -> str:
        rows = self.recent_alerts(limit=limit)
        if not rows:
            return "No alerts."
        lines = ["Alerts:"]
        for alert in rows:
            stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(alert.ts))
            tags = ",".join(f"{key}={value}" for key, value in sorted(alert.tags.items()))
            suffix = f" tags={tags}" if tags else ""
            lines.append(f"- {stamp} [{alert.severity}] {alert.rule} {alert.metric}={alert.value:g} threshold={alert.operator}{alert.threshold:g}{suffix}")
        return "\n".join(lines)

    def render_prometheus(self) -> str:
        rows = self.recent_metrics()
        if not rows:
            return "# No Evolva metrics recorded\n"
        aggregates: dict[tuple[str, tuple[tuple[str, str], ...], str], MetricRecord] = {}
        totals: dict[tuple[str, tuple[tuple[str, str], ...], str], float] = {}
        for record in rows:
            key = (record.name, tuple(sorted(record.tags.items())), record.unit)
            if record.unit == "count":
                totals[key] = totals.get(key, 0.0) + record.value
            else:
                aggregates[key] = record
        lines = ["# HELP evolva_metric Local Evolva runtime metric.", "# TYPE evolva_metric untyped"]
        for key, value in sorted(totals.items()):
            name, tags, unit = key
            metric_name = _prometheus_name(name, unit=unit)
            lines.append(f"{metric_name}{_prometheus_labels(dict(tags))} {value:g}")
        for key, record in sorted(aggregates.items()):
            name, tags, unit = key
            metric_name = _prometheus_name(name, unit=unit)
            lines.append(f"{metric_name}{_prometheus_labels(dict(tags))} {record.value:g}")
        alerts = self.recent_alerts()
        if alerts:
            lines.append("# HELP evolva_alert_active Local Evolva alert events.")
            lines.append("# TYPE evolva_alert_active gauge")
            for alert in alerts:
                labels = {"rule": alert.rule, "severity": alert.severity, "metric": alert.metric, **alert.tags}
                lines.append(f"evolva_alert_active{_prometheus_labels(labels)} 1")
        return "\n".join(lines) + "\n"

    def _recent_duplicate(self, rule: AlertRule, record: MetricRecord, *, now: float) -> bool:
        if rule.dedupe_seconds <= 0:
            return False
        since = now - rule.dedupe_seconds
        for alert in reversed(self.recent_alerts()):
            if alert.ts < since:
                return False
            if alert.rule == rule.name and alert.metric == rule.metric and alert.tags == record.tags:
                return True
        return False


def _string_tags(tags: dict[str, Any]) -> dict[str, str]:
    return {str(key): str(value) for key, value in tags.items() if value is not None}


def _compare(op: str) -> Callable[[float, float], bool]:
    operators = {
        ">": operator.gt,
        ">=": operator.ge,
        "<": operator.lt,
        "<=": operator.le,
        "==": operator.eq,
    }
    return operators.get(op, operator.ge)


def _prometheus_name(name: str, *, unit: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_:]", "_", name).strip("_")
    prefix = "evolva_"
    metric = prefix + safe
    if unit == "count" and not metric.endswith("_total"):
        metric += "_total"
    elif unit and unit not in {"count", "unit"} and not metric.endswith(f"_{unit}"):
        metric += f"_{re.sub(r'[^a-zA-Z0-9_]', '_', unit).strip('_')}"
    return metric


def _prometheus_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    rendered = ",".join(f'{_prometheus_label_name(key)}="{_escape_label(value)}"' for key, value in sorted(labels.items()) if value)
    return "{" + rendered + "}" if rendered else ""


def _prometheus_label_name(name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", name).strip("_")
    if not safe or safe[0].isdigit():
        safe = f"label_{safe}"
    return safe


def _escape_label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
