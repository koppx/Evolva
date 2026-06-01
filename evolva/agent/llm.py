from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from evolva.config import AgentConfig


@dataclass
class LLMResponse:
    content: str
    raw: dict[str, Any] | None = None


class OpenAICompatibleLLM:
    """Minimal OpenAI-compatible chat client using stdlib only."""

    def __init__(self, config: AgentConfig):
        self.config = config

    @property
    def available(self) -> bool:
        return bool(self.config.api_key)

    def chat(self, messages: list[dict[str, Any]], *, temperature: float = 0.2) -> LLMResponse:
        if not self.available:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM HTTP {exc.code}: {body}") from exc
        content = raw["choices"][0]["message"]["content"]
        return LLMResponse(content=content, raw=raw)


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from a model response."""
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{"):
                text = candidate
                break
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i, ch in enumerate(text[start:], start=start):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None
