from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable


@dataclass
class ScoreCheck:
    """One atomic, explainable eval check.

    Eval scores are only useful when a failure can be traced back to concrete
    evidence. A check therefore carries its dimension, weight, pass/fail state,
    and a short evidence string that can be rendered into CI output or consumed
    by Dream/Self-Evolution.
    """

    name: str
    passed: bool
    dimension: str = "quality"
    weight: float = 1.0
    evidence: str = ""
    expected: Any = None
    actual: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScoreReport:
    """Weighted multidimensional score report for a single eval task."""

    checks: list[ScoreCheck] = field(default_factory=list)

    @property
    def score(self) -> float:
        total = sum(max(0.0, item.weight) for item in self.checks)
        if total <= 0:
            return 1.0 if self.checks else 0.0
        earned = sum(max(0.0, item.weight) for item in self.checks if item.passed)
        return earned / total

    @property
    def passed(self) -> bool:
        return all(item.passed for item in self.checks) if self.checks else False

    def booleans(self) -> dict[str, bool]:
        return {item.name: item.passed for item in self.checks}

    def dimensions(self) -> dict[str, float]:
        buckets: dict[str, dict[str, float]] = {}
        for check in self.checks:
            bucket = buckets.setdefault(check.dimension, {"earned": 0.0, "total": 0.0})
            weight = max(0.0, check.weight)
            bucket["total"] += weight
            if check.passed:
                bucket["earned"] += weight
        return {name: (data["earned"] / data["total"] if data["total"] else 0.0) for name, data in buckets.items()}

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "passed": self.passed,
            "dimensions": self.dimensions(),
            "checks": [item.to_dict() for item in self.checks],
        }


@dataclass
class ScorerContext:
    """Runtime context shared by eval scorers."""

    root: Path
    answer: str
    tool_logs: list[str]
    duration_ms: int | None = None
    agent: Any = None

    @property
    def text(self) -> str:
        return self.answer + "\n" + "\n".join(self.tool_logs)

    def safe_path(self, artifact: str) -> Path | None:
        path = (self.root / artifact).resolve()
        try:
            path.relative_to(self.root.resolve())
        except ValueError:
            return None
        return path


ScorerFn = Callable[[dict[str, Any], ScorerContext], Iterable[ScoreCheck]]


class ScorerRegistry:
    """Registry for local, deterministic eval scoring operators.

    The default registry intentionally stays business-agnostic. Real production
    evals should register domain-specific scorers on top of these operators, but
    the built-ins cover common Agent Infra signals: text contracts, artifacts,
    command verifiers, trace events, memory/context persistence, latency, and
    tool health.
    """

    def __init__(self) -> None:
        self._scorers: dict[str, ScorerFn] = {}

    def register(self, name: str, scorer: ScorerFn) -> None:
        if not name or not name.strip():
            raise ValueError("scorer name is required")
        self._scorers[name] = scorer

    def names(self) -> list[str]:
        return sorted(self._scorers)

    def run(self, task: dict[str, Any], context: ScorerContext) -> ScoreReport:
        checks: list[ScoreCheck] = []
        for name in self._selected(task):
            scorer = self._scorers.get(name)
            if scorer is None:
                checks.append(
                    ScoreCheck(
                        name=f"scorer_registered:{name}",
                        passed=False,
                        dimension="config",
                        evidence=f"Unknown scorer: {name}",
                    )
                )
                continue
            checks.extend(list(scorer(task, context)))
        return ScoreReport(checks=checks)

    def _selected(self, task: dict[str, Any]) -> list[str]:
        selected = list(task.get("scorers", []))
        implicit = [
            ("expected_contains", "contains"),
            ("forbidden_contains", "not_contains"),
            ("expected_regex", "regex"),
            ("expected_artifacts", "artifact_exists"),
            ("expected_artifact_contains", "artifact_contains"),
            ("expected_json", "json_match"),
            ("expected_memory", "memory_contains"),
            ("expected_context", "context_contains"),
            ("expected_trace_events", "trace_event"),
            ("expected_tool_sequence", "tool_sequence"),
            ("max_duration_ms", "latency"),
            ("command_checks", "command"),
        ]
        for key, scorer in implicit:
            if key in task and scorer not in selected:
                selected.append(scorer)
        return _dedupe(selected)


def build_default_registry() -> ScorerRegistry:
    registry = ScorerRegistry()
    registry.register("contains", contains_scorer)
    registry.register("not_contains", not_contains_scorer)
    registry.register("regex", regex_scorer)
    registry.register("artifact_exists", artifact_exists_scorer)
    registry.register("artifact_contains", artifact_contains_scorer)
    registry.register("json_match", json_match_scorer)
    registry.register("memory_contains", memory_contains_scorer)
    registry.register("context_contains", context_contains_scorer)
    registry.register("latency", latency_scorer)
    registry.register("no_tool_error", no_tool_error_scorer)
    registry.register("trace_event", trace_event_scorer)
    registry.register("tool_sequence", tool_sequence_scorer)
    registry.register("command", command_scorer)
    return registry


def contains_scorer(task: dict[str, Any], context: ScorerContext) -> Iterable[ScoreCheck]:
    for expected in task.get("expected_contains", []):
        expected_s = str(expected)
        passed = expected_s in context.text
        yield ScoreCheck(
            name=f"contains:{expected_s}",
            passed=passed,
            dimension="correctness",
            expected=expected_s,
            evidence="found in answer/tool logs" if passed else "missing from answer/tool logs",
        )


def not_contains_scorer(task: dict[str, Any], context: ScorerContext) -> Iterable[ScoreCheck]:
    for forbidden in task.get("forbidden_contains", []):
        forbidden_s = str(forbidden)
        passed = forbidden_s not in context.text
        yield ScoreCheck(
            name=f"not_contains:{forbidden_s}",
            passed=passed,
            dimension="safety",
            expected=f"not {forbidden_s}",
            evidence="forbidden text absent" if passed else "forbidden text present",
        )


def regex_scorer(task: dict[str, Any], context: ScorerContext) -> Iterable[ScoreCheck]:
    for pattern in task.get("expected_regex", []):
        pattern_s = str(pattern)
        matched = re.search(pattern_s, context.text, flags=re.MULTILINE) is not None
        yield ScoreCheck(
            name=f"regex:{pattern_s}",
            passed=matched,
            dimension="correctness",
            expected=pattern_s,
            evidence="regex matched" if matched else "regex did not match",
        )


def artifact_exists_scorer(task: dict[str, Any], context: ScorerContext) -> Iterable[ScoreCheck]:
    for artifact in task.get("expected_artifacts", []):
        artifact_s = str(artifact)
        path = context.safe_path(artifact_s)
        inside = path is not None
        exists = bool(path and path.exists())
        yield ScoreCheck(
            name=f"artifact_inside_root:{artifact_s}",
            passed=inside,
            dimension="artifact",
            expected="inside project root",
            actual=str(path) if path else None,
            evidence="path is inside root" if inside else "path escapes root",
        )
        yield ScoreCheck(
            name=f"artifact_exists:{artifact_s}",
            passed=exists,
            dimension="artifact",
            expected="exists",
            actual=str(path) if path else None,
            evidence="artifact exists" if exists else "artifact missing or unsafe",
        )


def artifact_contains_scorer(task: dict[str, Any], context: ScorerContext) -> Iterable[ScoreCheck]:
    specs = task.get("expected_artifact_contains", [])
    if isinstance(specs, dict):
        specs = [{"path": path, "contains": contains} for path, contains in specs.items()]
    for spec in specs:
        if not isinstance(spec, dict):
            yield ScoreCheck(str(spec), False, "artifact", evidence="artifact_contains spec must be an object")
            continue
        artifact = str(spec.get("path", ""))
        expected_values = spec.get("contains", [])
        if isinstance(expected_values, str):
            expected_values = [expected_values]
        path = context.safe_path(artifact)
        try:
            content = path.read_text(encoding="utf-8") if path and path.exists() else ""
        except UnicodeDecodeError:
            content = ""
        for expected in expected_values:
            expected_s = str(expected)
            passed = bool(path and path.exists() and expected_s in content)
            yield ScoreCheck(
                name=f"artifact_contains:{artifact}:{expected_s}",
                passed=passed,
                dimension="artifact",
                expected=expected_s,
                actual=artifact,
                evidence="artifact contains expected text" if passed else "artifact missing expected text",
            )


def json_match_scorer(task: dict[str, Any], context: ScorerContext) -> Iterable[ScoreCheck]:
    expected = task.get("expected_json")
    if expected is None:
        return []
    try:
        actual = json.loads(context.answer)
    except Exception as exc:
        return [ScoreCheck("json:parse", False, "correctness", expected="valid JSON", evidence=str(exc))]
    checks: list[ScoreCheck] = [ScoreCheck("json:parse", True, "correctness", expected="valid JSON", evidence="answer parsed as JSON")]
    for path, value in _flatten_expected_json(expected).items():
        actual_value = _lookup_json_path(actual, path)
        checks.append(
            ScoreCheck(
                name=f"json:{path}",
                passed=actual_value == value,
                dimension="correctness",
                expected=value,
                actual=actual_value,
                evidence="JSON value matched" if actual_value == value else "JSON value mismatch",
            )
        )
    return checks


def memory_contains_scorer(task: dict[str, Any], context: ScorerContext) -> Iterable[ScoreCheck]:
    for expected in task.get("expected_memory", []):
        query = str(expected)
        hay = context.agent.memory.context(query) if context.agent is not None else ""
        yield ScoreCheck(
            name=f"memory:{query}",
            passed=query in hay,
            dimension="memory",
            expected=query,
            evidence="memory search returned expected text" if query in hay else "memory search did not return expected text",
        )


def context_contains_scorer(task: dict[str, Any], context: ScorerContext) -> Iterable[ScoreCheck]:
    for expected in task.get("expected_context", []):
        query = str(expected)
        hay = context.agent.context.render(query=query) if context.agent is not None else ""
        yield ScoreCheck(
            name=f"context:{query}",
            passed=query in hay,
            dimension="context",
            expected=query,
            evidence="context search returned expected text" if query in hay else "context search did not return expected text",
        )


def latency_scorer(task: dict[str, Any], context: ScorerContext) -> Iterable[ScoreCheck]:
    if "max_duration_ms" not in task or context.duration_ms is None:
        return []
    limit = int(task["max_duration_ms"])
    passed = context.duration_ms <= limit
    return [
        ScoreCheck(
            name=f"duration<={limit}ms",
            passed=passed,
            dimension="latency",
            expected=limit,
            actual=context.duration_ms,
            evidence="within latency budget" if passed else "latency budget exceeded",
        )
    ]


def no_tool_error_scorer(task: dict[str, Any], context: ScorerContext) -> Iterable[ScoreCheck]:
    failed_markers = ["ok=False", "Tool error", "Traceback", "Policy denied"]
    found = [marker for marker in failed_markers if marker in context.text]
    return [
        ScoreCheck(
            name="no_tool_error",
            passed=not found,
            dimension="tool_use",
            expected="no tool error markers",
            actual=found,
            evidence="no tool errors detected" if not found else "tool error markers detected: " + ", ".join(found),
        )
    ]


def trace_event_scorer(task: dict[str, Any], context: ScorerContext) -> Iterable[ScoreCheck]:
    expected = task.get("expected_trace_events", [])
    if not expected or context.agent is None:
        return []
    try:
        if getattr(context.agent.tracer, "current", None) is not None:
            run_id = context.agent.tracer.current.run_id
            events = [event.to_dict() if hasattr(event, "to_dict") else {"kind": event.kind, "data": event.data} for event in context.agent.tracer.current.events]
        else:
            run_id = context.agent.tracer.list_runs(limit=1)[0]["run_id"]
            trace = context.agent.tracer.load(run_id)
            events = trace.get("events", [])
    except Exception as exc:
        return [ScoreCheck("trace:load_latest", False, "trace", evidence=str(exc))]
    kinds = [str(event.get("kind", "")) for event in events]
    checks = [ScoreCheck("trace:load_latest", True, "trace", actual=run_id, evidence="latest trace loaded")]
    for spec in expected:
        if isinstance(spec, str):
            kind = spec
            passed = kind in kinds
            checks.append(ScoreCheck(f"trace_event:{kind}", passed, "trace", expected=kind, actual=kinds, evidence="event found" if passed else "event missing"))
            continue
        if isinstance(spec, dict):
            kind = str(spec.get("kind", ""))
            data_contains = spec.get("data_contains")
            matched = [event for event in events if event.get("kind") == kind]
            if data_contains:
                needle = str(data_contains)
                matched = [event for event in matched if needle in json.dumps(event.get("data", {}), ensure_ascii=False)]
            passed = bool(matched)
            name = f"trace_event:{kind}" + (f":{data_contains}" if data_contains else "")
            checks.append(ScoreCheck(name, passed, "trace", expected=spec, actual=len(matched), evidence="event matched" if passed else "event missing"))
    return checks


def tool_sequence_scorer(task: dict[str, Any], context: ScorerContext) -> Iterable[ScoreCheck]:
    expected = [str(item) for item in task.get("expected_tool_sequence", [])]
    if not expected:
        return []
    observed: list[str] = []
    for log in context.tool_logs:
        match = re.search(r"TOOL\s+([\w_.-]+)", log)
        if match:
            observed.append(match.group(1))
    passed = _is_subsequence(expected, observed)
    return [ScoreCheck("tool_sequence", passed, "tool_use", expected=expected, actual=observed, evidence="tool sequence matched" if passed else "tool sequence mismatch")]


def command_scorer(task: dict[str, Any], context: ScorerContext) -> Iterable[ScoreCheck]:
    checks: list[ScoreCheck] = []
    for idx, spec in enumerate(task.get("command_checks", [])):
        if not isinstance(spec, dict):
            checks.append(ScoreCheck(f"command:{idx}:config", False, "verification", evidence="command spec must be an object"))
            continue
        command = spec.get("command")
        if isinstance(command, str):
            args = command.split()
        else:
            args = [str(item) for item in command or []]
        if not args:
            checks.append(ScoreCheck(f"command:{idx}:config", False, "verification", evidence="command is required"))
            continue
        timeout = int(spec.get("timeout_ms", 10000)) / 1000
        if any(_looks_unsafe_arg(arg) for arg in args):
            checks.append(ScoreCheck(f"command:{idx}:safety", False, "verification", evidence="unsafe shell metacharacter or destructive token in command"))
            continue
        try:
            proc = subprocess.run(args, cwd=context.root, text=True, capture_output=True, timeout=timeout, check=False)
            output = (proc.stdout or "") + (proc.stderr or "")
            expected_exit = int(spec.get("exit_code", 0))
            checks.append(
                ScoreCheck(
                    name=f"command:{idx}:exit_code",
                    passed=proc.returncode == expected_exit,
                    dimension="verification",
                    expected=expected_exit,
                    actual=proc.returncode,
                    evidence=output[-500:],
                )
            )
            for expected_text in spec.get("expected_contains", []):
                expected_s = str(expected_text)
                checks.append(
                    ScoreCheck(
                        name=f"command:{idx}:contains:{expected_s}",
                        passed=expected_s in output,
                        dimension="verification",
                        expected=expected_s,
                        evidence="command output contained expected text" if expected_s in output else output[-500:],
                    )
                )
        except Exception as exc:
            checks.append(ScoreCheck(f"command:{idx}:run", False, "verification", evidence=str(exc)))
    return checks


def _looks_unsafe_arg(arg: str) -> bool:
    dangerous = {";", "&&", "||", "|", ">", "<", "`", "$"}
    destructive = {"rm", "shutdown", "mkfs", "reboot"}
    return arg in dangerous or arg in destructive or ".." in arg


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _flatten_expected_json(value: Any, prefix: str = "$") -> dict[str, Any]:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, child in value.items():
            out.update(_flatten_expected_json(child, f"{prefix}.{key}"))
        return out
    return {prefix: value}


def _lookup_json_path(value: Any, path: str) -> Any:
    cur = value
    for part in path.split(".")[1:]:
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _is_subsequence(expected: list[str], observed: list[str]) -> bool:
    pos = 0
    for item in observed:
        if pos < len(expected) and item == expected[pos]:
            pos += 1
    return pos == len(expected)
