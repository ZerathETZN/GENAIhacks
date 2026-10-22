import httpx
import pytest
from pydantic import BaseModel

from app.llm import generator


class Verdict(BaseModel):
    ok: bool


def _resp(status=200, content="hi", model="served-model"):
    body = {"model": model, "choices": [{"message": {"content": content}}]}
    return httpx.Response(status, json=body, request=httpx.Request("POST", "http://x"))


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "t")
    monkeypatch.setenv("METERLESS_MODEL", "requested-model")
    monkeypatch.delenv("SAMPLE_MODE", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setattr(generator, "_sleep", lambda s: None)


def _script(monkeypatch, *responses):
    calls = []

    def post(url, json, headers, timeout):
        calls.append((json, headers))
        r = responses[min(len(calls), len(responses)) - 1]
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(generator.httpx, "post", post)
    return calls


def test_nightshift_records_served_by_and_headers(monkeypatch):
    calls = _script(monkeypatch, _resp())
    r = generator.generate("p")
    assert (r.provider, r.served_by, r.text) == ("meterless", "served-model", "hi")
    body, headers = calls[0]
    assert headers["meterless-app"] == "recallguard" and headers["meterless-scope"] == "user"
    assert body["max_tokens"] >= 800


def test_retries_empty_and_429_then_succeeds(monkeypatch):
    calls = _script(monkeypatch, _resp(429), _resp(content=""), _resp())
    assert generator.generate("p").provider == "meterless"
    assert len(calls) == 3


def test_exhausted_retries_use_heuristic(monkeypatch):
    calls = _script(monkeypatch, _resp(502))
    r = generator.generate("p")
    assert (r.provider, r.served_by, r.text) == ("heuristic_fallback", None, "")
    assert len(calls) == generator.RETRIES


def test_paused_job_is_not_retried(monkeypatch):
    paused = httpx.Response(429, json={"error": {"code": "job_paused"}}, request=httpx.Request("POST", "http://x"))
    calls = _script(monkeypatch, paused)
    assert generator.generate("p").provider == "heuristic_fallback"
    assert len(calls) == 1


def test_transport_failure_uses_heuristic(monkeypatch):
    _script(monkeypatch, httpx.ConnectError("refused"))
    assert generator.generate("p").provider == "heuristic_fallback"


def test_sample_mode_makes_no_network_call(monkeypatch):
    monkeypatch.setenv("SAMPLE_MODE", "true")
    calls = _script(monkeypatch, _resp())
    assert generator.generate("p").provider == "heuristic_fallback"
    assert calls == []


def test_missing_token_uses_heuristic(monkeypatch):
    monkeypatch.delenv("METERLESS_RUNTIME_TOKEN")
    assert generator.generate("p").provider == "heuristic_fallback"


def test_json_schema_retries_once_on_invalid(monkeypatch):
    calls = _script(monkeypatch, _resp(content="not json"), _resp(content='```json\n{"ok": true}\n```'))
    r = generator.generate("p", json_schema=Verdict)
    assert Verdict.model_validate_json(r.text).ok and len(calls) == 2


def test_json_schema_invalid_twice_uses_heuristic(monkeypatch):
    _script(monkeypatch, _resp(content="nope"))
    assert generator.generate("p", json_schema=Verdict).provider == "heuristic_fallback"
