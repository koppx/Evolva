from __future__ import annotations

import io
import json
import urllib.error

import pytest

from evolva.agent.images import image_part, is_image_url, user_content_with_images
from evolva.agent.llm import OpenAICompatibleLLM, extract_json_object


def test_extract_json_object_plain_fenced_and_nested():
    assert extract_json_object('{"final":"ok"}') == {"final": "ok"}
    assert extract_json_object('```json\n{"tool":{"args":{"x":1}}}\n```') == {"tool": {"args": {"x": 1}}}
    assert extract_json_object('prefix {"text":"brace } inside"} suffix') == {"text": "brace } inside"}


def test_extract_json_object_returns_none_for_missing_or_invalid_json():
    assert extract_json_object("no json here") is None
    assert extract_json_object('{"broken":') is None


def test_llm_available_reflects_api_key(temp_config):
    assert not OpenAICompatibleLLM(temp_config).available
    assert OpenAICompatibleLLM(temp_config.__class__(**{**temp_config.__dict__, "api_key": "sk-test"})).available


def test_llm_chat_posts_openai_compatible_payload(monkeypatch, temp_config):
    cfg = temp_config.__class__(**{**temp_config.__dict__, "api_key": "sk-test", "base_url": "https://llm.example/v1", "model": "demo-model"})
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "hello"}}]}).encode()

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(req.header_items())
        captured["payload"] = json.loads(req.data.decode())
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    resp = OpenAICompatibleLLM(cfg).chat([{"role": "user", "content": "hi"}], temperature=0.7)

    assert resp.content == "hello"
    assert captured["url"] == "https://llm.example/v1/chat/completions"
    assert captured["payload"]["model"] == "demo-model"
    assert captured["payload"]["temperature"] == 0.7
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["timeout"] == cfg.request_timeout


def test_llm_chat_accepts_per_request_timeout(monkeypatch, temp_config):
    cfg = temp_config.__class__(**{**temp_config.__dict__, "api_key": "sk-test"})
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "hello"}}]}).encode()

    def fake_urlopen(req, timeout):
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    OpenAICompatibleLLM(cfg).chat([{"role": "user", "content": "hi"}], timeout=420)

    assert captured["timeout"] == 420


def test_llm_chat_uses_configured_default_temperature(monkeypatch, temp_config):
    cfg = temp_config.__class__(**{**temp_config.__dict__, "api_key": "sk-test", "temperature": 1.0})
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "hello"}}]}).encode()

    def fake_urlopen(req, timeout):
        captured["payload"] = json.loads(req.data.decode())
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    OpenAICompatibleLLM(cfg).chat([{"role": "user", "content": "hi"}])

    assert captured["payload"]["temperature"] == 1.0


def test_llm_chat_retries_without_temperature_when_provider_requires_default(monkeypatch, temp_config):
    cfg = temp_config.__class__(**{**temp_config.__dict__, "api_key": "sk-test", "base_url": "https://llm.example/v1", "temperature": 0.2})
    payloads = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

    class FakeHTTPError(urllib.error.HTTPError):
        def read(self):
            return b'{"error":{"message":"Unsupported value: temperature only supports default"}}'

    def fake_urlopen(req, timeout):
        payloads.append(json.loads(req.data.decode()))
        if len(payloads) == 1:
            raise FakeHTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO())
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    resp = OpenAICompatibleLLM(cfg).chat([{"role": "user", "content": "hi"}], temperature=0.1)

    assert resp.content == "ok"
    assert payloads[0]["temperature"] == 0.1
    assert "temperature" not in payloads[1]


def test_llm_chat_retries_transient_http_errors(monkeypatch, temp_config):
    cfg = temp_config.__class__(**{**temp_config.__dict__, "api_key": "sk-test", "llm_max_retries": 2, "llm_retry_backoff": 0})
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "ok after retry"}}]}).encode()

    class FakeHTTPError(urllib.error.HTTPError):
        def read(self):
            return b'{"error":"temporary"}'

    def fake_urlopen(req, timeout):
        calls.append(json.loads(req.data.decode()))
        if len(calls) == 1:
            raise FakeHTTPError(req.full_url, 500, "Server Error", {}, io.BytesIO())
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    resp = OpenAICompatibleLLM(cfg).chat([{"role": "user", "content": "hi"}])

    assert resp.content == "ok after retry"
    assert len(calls) == 2


def test_llm_chat_does_not_retry_non_transient_http_errors(monkeypatch, temp_config):
    cfg = temp_config.__class__(**{**temp_config.__dict__, "api_key": "sk-test", "llm_max_retries": 3, "llm_retry_backoff": 0})
    calls = []

    class FakeHTTPError(urllib.error.HTTPError):
        def read(self):
            return b'{"error":"bad auth"}'

    def fake_urlopen(req, timeout):
        calls.append(req.full_url)
        raise FakeHTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="LLM HTTP 401"):
        OpenAICompatibleLLM(cfg).chat([{"role": "user", "content": "hi"}])

    assert len(calls) == 1


def test_llm_chat_json_validates_required_keys(monkeypatch, temp_config):
    cfg = temp_config.__class__(**{**temp_config.__dict__, "api_key": "sk-test"})

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": '```json\n{"final":"ok"}\n```'}}]}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: FakeResponse())

    llm = OpenAICompatibleLLM(cfg)
    assert llm.chat_json([{"role": "user", "content": "hi"}], required_keys=["final"]) == {"final": "ok"}
    with pytest.raises(RuntimeError, match="missing required keys"):
        llm.chat_json([{"role": "user", "content": "hi"}], required_keys=["tool"])


def test_llm_chat_surfaces_http_error(monkeypatch, temp_config):
    cfg = temp_config.__class__(**{**temp_config.__dict__, "api_key": "sk-test"})

    class FakeHTTPError(urllib.error.HTTPError):
        def read(self):
            return b'{"error":"bad"}'

    def fake_urlopen(req, timeout):
        raise FakeHTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="LLM HTTP 401"):
        OpenAICompatibleLLM(cfg).chat([{"role": "user", "content": "hi"}])


def test_image_url_and_local_image_parts(tmp_path):
    assert is_image_url("https://example.com/a.png")
    assert not is_image_url("/tmp/a.png")

    image = tmp_path / "tiny.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    part = image_part("tiny.png", root=tmp_path)
    assert part["type"] == "image_url"
    assert part["image_url"]["url"].startswith("data:image/png;base64,")

    content = user_content_with_images("describe", ["https://example.com/a.webp", "tiny.png"], root=tmp_path)
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "describe"}
    assert len(content) == 3


def test_image_part_rejects_missing_escape_and_unsupported(tmp_path):
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(b"x")
    with pytest.raises(ValueError, match="escapes"):
        image_part(str(outside), root=tmp_path)
    with pytest.raises(FileNotFoundError):
        image_part("missing.png", root=tmp_path)
    text_file = tmp_path / "note.txt"
    text_file.write_text("not image")
    with pytest.raises(ValueError, match="Unsupported image type"):
        image_part("note.txt", root=tmp_path)
