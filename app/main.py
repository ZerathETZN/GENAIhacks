"""FastAPI entry point (AGENTS.md §6, §7). Owner: C.

POST /run                 run one request (§7.1) -> RunResult (§7.2)
GET  /health              liveness + Zetaris / Nightshift reachability
GET  /runs/{run_id}       saved RunResult
GET  /runs/{run_id}/trace trace events (§7.3) written by the real run
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool

from app import health as health_mod
from app.runner import execute, read_trace, result_path, sample_mode_from_env, validate_run_id
from app.schemas import RunRequest, RunResult

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title="RecallGuard",
    version="0.1.0",
    description="Multi-agent recall exposure review for pharmacy chains. Outputs are for pharmacist review, "
    "not compliance verdicts.",
)


@app.get("/")
def root() -> dict:
    return {"service": "RecallGuard", "docs": "/docs", "run": "POST /run", "health": "/health"}


@app.get("/health")
def get_health() -> dict:
    return health_mod.health(sample_mode_from_env())


@app.post("/run", response_model=RunResult)
async def post_run(request: RunRequest) -> RunResult:
    # Runs in a worker thread: agents make blocking HTTP calls and a run can take minutes.
    return await run_in_threadpool(execute, request)


def _checked(run_id: str) -> str:
    try:
        validate_run_id(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return run_id


@app.get("/runs/{run_id}", response_model=RunResult)
def get_run(run_id: str) -> RunResult:
    path = result_path(_checked(run_id))
    if not path.exists():
        raise HTTPException(status_code=404, detail="no saved result for this run_id")
    return RunResult.model_validate_json(path.read_text(encoding="utf-8"))


@app.get("/runs/{run_id}/trace")
def get_trace(run_id: str) -> list[dict]:
    return read_trace(_checked(run_id))
