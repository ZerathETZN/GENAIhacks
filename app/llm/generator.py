"""Single entry point for every model call (AGENTS.md §5.3). Owner: B.

Order: Nightshift (Meterless runtime) -> heuristic_fallback.
heuristic_fallback is used when SAMPLE_MODE=true, LLM_PROVIDER=heuristic, the
Nightshift token is missing, Nightshift is unreachable, or its retries are
exhausted. It returns empty text: the calling agent then applies its own
deterministic rules (score thresholds, templated critic checks). It never
returns canned prose.
Engines and agents receive `generate` by injection; nothing else calls a model.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

import httpx
from pydantic import BaseModel, ValidationError

from app.schemas import Provider

logger = logging.getLogger(__name__)

MAX_TOKENS = 1500  # Nemotron reasons first; < 800 returns 502 empty_response
TIMEOUT_S = 180.0  # a cold model load can be slow
RETRIES = 3  # attempts on 429 / 5xx / empty_response
_sleep = time.sleep  # tests replace this to skip backoff


class GenerationResult(BaseModel):
    text: str
    provider: Provider
    served_by: str | None  # response.model as returned, never the requested model
    latency_ms: int


class _NightshiftUnavailable(Exception):
    """Transport failure, exhausted retries or a non-retryable error."""


def _heuristic(start: float) -> GenerationResult:
    return GenerationResult(
        text="", provider="heuristic_fallback", served_by=None,
        latency_ms=int((time.monotonic() - start) * 1000),
    )


def _use_heuristic() -> bool:
    return (
        os.getenv("SAMPLE_MODE", "").lower() == "true"
        or os.getenv("LLM_PROVIDER", "meterless").lower() == "heuristic"
        or not os.getenv("METERLESS_RUNTIME_TOKEN")
    )


def _nightshift(messages: list[dict], model: str | None) -> tuple[str, str | None]:
    """One chat completion; returns (text, response.model)."""
    base = os.getenv("METERLESS_BASE_URL", "http://127.0.0.1:8088/v1").rstrip("/")
    headers = {
        "Authorization": f"Bearer {os.environ['METERLESS_RUNTIME_TOKEN']}",
        "meterless-app": "recallguard",
        "meterless-scope": "user",
    }
    body = {
        "model": model or os.getenv("METERLESS_MODEL", ""),
        "messages": messages,
        "max_tokens": MAX_TOKENS,
    }
    for attempt in range(RETRIES):
        try:
            resp = httpx.post(f"{base}/chat/completions", json=body, headers=headers, timeout=TIMEOUT_S)
        except httpx.TransportError as exc:
            raise _NightshiftUnavailable(f"transport: {type(exc).__name__}") from exc
        if "job_paused" in resp.text:  # needs a human to resume the Nightshift job; retrying can't help
            raise _NightshiftUnavailable("job_paused")
        if resp.status_code == 429 or resp.status_code >= 500:
            reason = f"http {resp.status_code}"
        elif resp.status_code >= 400:
            raise _NightshiftUnavailable(f"http {resp.status_code}")
        else:
            data = resp.json()
            text = (data["choices"][0]["message"].get("content") or "").strip()
            if text:
                return text, data.get("model")
            reason = "empty_response"
        logger.warning("nightshift retry %d/%d: %s", attempt + 1, RETRIES, reason)
        if attempt < RETRIES - 1:
            _sleep(2**attempt)
    raise _NightshiftUnavailable(f"retries exhausted ({reason})")


def _parse_json(text: str, schema: type[BaseModel]) -> BaseModel:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return schema.model_validate(json.loads(text))


def generate(
    prompt: str,
    system_prompt: str | None = None,
    model: str | None = None,
    json_schema: type[BaseModel] | None = None,
) -> GenerationResult:
    """Generate text (or JSON validated against `json_schema`, one retry on
    validation error). max_tokens >= 800, client timeout 180 s."""
    start = time.monotonic()
    if _use_heuristic():
        return _heuristic(start)

    system = system_prompt or ""
    if json_schema:
        system += "\nReply with JSON only, matching this schema:\n" + json.dumps(json_schema.model_json_schema())
    messages = ([{"role": "system", "content": system.strip()}] if system.strip() else []) + [
        {"role": "user", "content": prompt}
    ]

    try:
        for attempt in range(2 if json_schema else 1):
            text, served_by = _nightshift(messages, model)
            if not json_schema:
                break
            try:
                text = _parse_json(text, json_schema).model_dump_json()
                break
            except (ValidationError, ValueError) as exc:
                if attempt == 1:
                    raise _NightshiftUnavailable("invalid JSON after retry") from exc
                messages += [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": f"That reply was invalid: {str(exc)[:500]}. Return corrected JSON only."},
                ]
    except _NightshiftUnavailable as exc:
        logger.warning("heuristic_fallback: %s", exc)
        return _heuristic(start)

    return GenerationResult(
        text=text, provider="meterless", served_by=served_by,
        latency_ms=int((time.monotonic() - start) * 1000),
    )
