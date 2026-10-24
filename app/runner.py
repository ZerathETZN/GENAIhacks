"""Shared execution path for the API (`POST /run`) and the CLI (`run.py`). Owner: C.

Wraps the orchestrator (owner: B) so callers always get a RunResult (AGENTS.md §7.2):
never an unhandled exception, never a fabricated result.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from app.schemas import RunError, RunRequest, RunResult

log = logging.getLogger("recallguard.runner")

LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
TRUTHY = {"1", "true", "yes", "on"}


def sample_mode_from_env() -> bool:
    return os.getenv("SAMPLE_MODE", "false").strip().lower() in TRUTHY


def trace_path(run_id: str) -> Path:
    return LOG_DIR / f"trace-{run_id}.jsonl"


def result_path(run_id: str) -> Path:
    return LOG_DIR / f"result-{run_id}.json"


def _error(request_run_id: str, etype: str, message: str, recoverable: bool, started: float) -> RunResult:
    return RunResult(
        run_id=request_run_id,
        status="error",
        error=RunError(type=etype, message=message[:500], recoverable=recoverable),
        trace_id=f"trace-{request_run_id}",
        log_file=str(trace_path(request_run_id)),
        execution_time_seconds=max(round(time.perf_counter() - started, 3), 0.001),
    )


def validate_run_id(run_id: str) -> None:
    """run_id becomes part of file names, so only safe characters are allowed."""
    if not RUN_ID_RE.match(run_id):
        raise ValueError("run_id must be 1-64 chars: letters, digits, '_', '-', '.'; starting with a letter or digit")


def execute(request: RunRequest) -> RunResult:
    """Run one request end to end and persist the result next to its trace."""
    started = time.perf_counter()
    try:
        validate_run_id(request.run_id)
    except ValueError as exc:
        return _error("invalid", "ValidationError", str(exc), False, started)

    # SAMPLE_MODE=true in the environment forces sample mode (judges' path, AGENTS.md §2.7).
    if sample_mode_from_env() and not request.options.sample_mode:
        request = request.model_copy(update={"options": request.options.model_copy(update={"sample_mode": True})})

    if request.input.mode == "recall_alert" and request.input.recall is None:
        return _error(request.run_id, "ValidationError", "mode 'recall_alert' needs input.recall", False, started)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log.info("run %s start mode=%s sample_mode=%s", request.run_id, request.input.mode, request.options.sample_mode)

    try:
        from app.orchestrator import run as orchestrate  # owner: B
    except ModuleNotFoundError as exc:
        if exc.name in {"app.orchestrator"}:
            result = _error(
                request.run_id, "NotImplemented",
                "app/orchestrator.py is not merged yet; the API and CLI are ready for it", False, started,
            )
            _persist(result)
            return result
        raise

    try:
        raw = orchestrate(request)
        result = raw if isinstance(raw, RunResult) else RunResult.model_validate(raw)
    except Exception as exc:
        log.exception("run %s failed", request.run_id)
        recoverable = bool(getattr(exc, "recoverable", True))
        result = _error(request.run_id, type(exc).__name__, str(exc) or repr(exc), recoverable, started)

    if not result.execution_time_seconds:
        result.execution_time_seconds = max(round(time.perf_counter() - started, 3), 0.001)
    _persist(result)
    log.info("run %s end status=%s in %.1fs", result.run_id, result.status, result.execution_time_seconds)
    return result


def _persist(result: RunResult) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        result_path(result.run_id).write_text(result.model_dump_json(indent=2), encoding="utf-8")
    except OSError as exc:
        log.warning("could not save result for %s: %s", result.run_id, exc)


def read_trace(run_id: str) -> list[dict]:
    """Trace events written by real execution (AGENTS.md §7.3). Malformed lines are skipped."""
    validate_run_id(run_id)
    path = trace_path(run_id)
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events
