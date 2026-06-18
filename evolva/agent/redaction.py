from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


SECRET_KEY_RE = re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization|credential)")


@dataclass
class Redactor:
    """Best-effort secret redaction for trace, context, and audit payloads."""

    patterns: list[str] = field(
        default_factory=lambda: [
            r"sk-[A-Za-z0-9_-]{20,}",
            r"AKIA[0-9A-Z]{16}",
            r"-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----.*?-----END (RSA |OPENSSH |EC )?PRIVATE KEY-----",
            r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?([^\s'\",}]{8,})",
            r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{16,}",
        ]
    )
    max_string_chars: int = 64_000

    def redact_text(self, text: str) -> str:
        value = str(text)
        for pattern in self.patterns:
            value = re.sub(pattern, self._replacement, value, flags=re.S)
        if len(value) > self.max_string_chars:
            return value[: self.max_string_chars] + "\n[TRUNCATED]"
        return value

    def redact_json(self, value: Any) -> Any:
        try:
            return self._redact(value)
        except Exception:
            return "[REDACTION_ERROR]"

    def _redact(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, dict):
            redacted: dict[str, Any] = {}
            for key, item in value.items():
                rendered_key = str(key)
                if SECRET_KEY_RE.search(rendered_key):
                    redacted[rendered_key] = f"[REDACTED:{rendered_key}]"
                else:
                    redacted[rendered_key] = self._redact(item)
            return redacted
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, tuple):
            return [self._redact(item) for item in value]
        return value

    def _replacement(self, match: re.Match[str]) -> str:
        text = match.group(0)
        key_match = re.match(r"(?i)(api[_-]?key|token|secret|password)", text)
        if key_match:
            return f"{key_match.group(1)}=[REDACTED:{key_match.group(1)}]"
        if text.lower().startswith("bearer "):
            return "Bearer [REDACTED:authorization]"
        if "PRIVATE KEY" in text:
            return "[REDACTED:private_key]"
        if text.startswith("AKIA"):
            return "[REDACTED:aws_access_key]"
        if text.startswith("sk-"):
            return "[REDACTED:openai_key]"
        return "[REDACTED:secret]"


def redacted_json_dumps(value: Any, **kwargs: Any) -> str:
    return json.dumps(Redactor().redact_json(value), **kwargs)
