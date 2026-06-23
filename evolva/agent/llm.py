from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from evolva.config import AgentConfig


@dataclass
class LLMResponse:
    content: str
    raw: dict[str, Any] | None = None
    attempts: int = 1
    retries: int = 0


class OpenAICompatibleLLM:
    """Minimal OpenAI-compatible chat client using stdlib only."""

    def __init__(self, config: AgentConfig):
        self.config = config

    @property
    def available(self) -> bool:
        return bool(self.config.api_key)

    def chat(self, messages: list[dict[str, Any]], *, temperature: float | None = None, timeout: int | None = None) -> LLMResponse:
        if not self.available:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        payload = {
            "model": self.config.model,
            "messages": messages,
        }
        resolved_temperature = self.config.temperature if temperature is None else temperature
        if resolved_temperature is not None:
            payload["temperature"] = resolved_temperature
        request_timeout = timeout or getattr(self.config, "request_timeout", 180)
        attempts = max(1, 1 + int(getattr(self.config, "llm_max_retries", 0)))
        for attempt in range(attempts):
            try:
                raw = self._post_chat(payload, request_timeout)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if payload.get("temperature") is not None and self._temperature_must_be_default(exc.code, body):
                    retry_payload = dict(payload)
                    retry_payload.pop("temperature", None)
                    try:
                        raw = self._post_chat(retry_payload, request_timeout)
                    except urllib.error.HTTPError as retry_exc:
                        retry_body = retry_exc.read().decode("utf-8", errors="replace")
                        raise RuntimeError(f"LLM HTTP {retry_exc.code}: {retry_body}") from retry_exc
                    except Exception:
                        raise
                    return LLMResponse(content=self._content_from_raw(raw), raw=raw, attempts=attempt + 2, retries=attempt + 1)
                if self._is_retryable_http(exc.code) and attempt + 1 < attempts:
                    self._sleep_before_retry(attempt)
                    continue
                raise RuntimeError(f"LLM HTTP {exc.code}: {body}") from exc
            except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
                if attempt + 1 < attempts:
                    self._sleep_before_retry(attempt)
                    continue
                raise RuntimeError(f"LLM request failed after {attempts} attempt(s): {exc}") from exc
            return LLMResponse(content=self._content_from_raw(raw), raw=raw, attempts=attempt + 1, retries=attempt)
        raise RuntimeError(f"LLM request failed after {attempts} attempt(s)")

    def chat_json(self, messages: list[dict[str, Any]], *, required_keys: list[str] | None = None, **kwargs: Any) -> dict[str, Any]:
        response = self.chat(messages, **kwargs)
        data = extract_json_object(response.content)
        if data is None:
            raise RuntimeError("LLM response did not contain a JSON object")
        missing = [key for key in required_keys or [] if key not in data]
        if missing:
            raise RuntimeError(f"LLM JSON response missing required keys: {', '.join(missing)}")
        return data

    def _post_chat(self, payload: dict[str, Any], request_timeout: int) -> dict[str, Any]:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
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
        with urllib.request.urlopen(req, timeout=request_timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _content_from_raw(self, raw: dict[str, Any]) -> str:
        try:
            return str(raw["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("LLM response missing choices[0].message.content") from exc

    def _sleep_before_retry(self, attempt: int) -> None:
        backoff = max(0.0, float(getattr(self.config, "llm_retry_backoff", 0.25)))
        if backoff:
            time.sleep(min(backoff * (2**attempt), 5.0))

    @staticmethod
    def _is_retryable_http(status_code: int) -> bool:
        return status_code in {408, 429, 500, 502, 503, 504}

    @staticmethod
    def _temperature_must_be_default(status_code: int, body: str) -> bool:
        if status_code != 400:
            return False
        lowered = body.lower()
        return "temperature" in lowered and ("unsupported" in lowered or "default" in lowered)


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
