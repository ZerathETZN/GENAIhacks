"""Dependency checks for GET /health. Owner: C. Never returns secrets."""

from __future__ import annotations

import os

import httpx

TIMEOUT = httpx.Timeout(4.0)


def _check_zetaris() -> dict:
    base = os.getenv("ZETARIS_REST_URL")
    if not base or not os.getenv("ZETARIS_API_KEY"):
        return {"status": "not_configured"}
    try:
        r = httpx.get(base.rstrip("/"), timeout=TIMEOUT)
        return {"status": "reachable", "http": r.status_code}
    except httpx.HTTPError as exc:
        return {"status": "unreachable", "detail": type(exc).__name__}


def _check_meterless() -> dict:
    base = os.getenv("METERLESS_BASE_URL")
    token = os.getenv("METERLESS_RUNTIME_TOKEN")
    if not base or not token or token.startswith("your-"):
        return {"status": "not_configured"}
    headers = {"Authorization": f"Bearer {token}", "meterless-app": "recallguard"}
    try:
        r = httpx.get(base.rstrip("/") + "/models", headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        return {"status": "unreachable", "detail": f"{type(exc).__name__} - is the Nightshift app open?"}
    if r.status_code == 401:
        return {"status": "unauthorized", "detail": "copy Nightshift Console > API key into METERLESS_RUNTIME_TOKEN"}
    if r.status_code != 200:
        return {"status": "error", "http": r.status_code}
    ids = [m.get("id", "") for m in r.json().get("data", [])]
    return {
        "status": "ok",
        "routes": len(ids),
        "nemotron_routes": [i for i in ids if "nemotron" in i.lower()][:4],
        "note": "served_by in traces shows which lane answered; stop local lanes so Nemotron serves",
    }


def health(sample_mode: bool) -> dict:
    if sample_mode:
        return {"status": "ok", "sample_mode": True, "zetaris": {"status": "skipped"}, "meterless": {"status": "skipped"}}
    z, m = _check_zetaris(), _check_meterless()
    degraded = z["status"] != "reachable" or m["status"] != "ok"
    return {"status": "degraded" if degraded else "ok", "sample_mode": False, "zetaris": z, "meterless": m}
