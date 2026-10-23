"""Trace writer (AGENTS.md §7.3). One JSONL file per run, echoed to the log.

Events are written only by real execution. The file is read back by the API
(`app.runner.read_trace`), so the name must stay `trace-<run_id>.jsonl`.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.schemas import TraceEvent

log = logging.getLogger("recallguard.trace")

_SECRET_ENV = ("METERLESS_RUNTIME_TOKEN", "NVIDIA_API_KEY", "ZETARIS_API_KEY", "PG_READER_PASSWORD", "PG_ADMIN_PASSWORD")


def _redact(text: str) -> str:
    for name in _SECRET_ENV:
        secret = os.getenv(name, "")
        if len(secret) >= 8:  # placeholders like "change-me" are short enough to skip noise
            text = text.replace(secret, "***")
    return text


class Tracer:
    def __init__(self, run_id: str, log_dir: str | None = None) -> None:
        self.run_id = run_id
        self.path = Path(log_dir or os.getenv("LOG_DIR", "logs")) / f"trace-{run_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")  # a re-run of the same run_id replaces the old trace

    def emit(self, event: TraceEvent) -> None:
        line = _redact(event.model_dump_json())
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        log.info("run_id=%s %s %s: %s", event.run_id, event.agent_name, event.action, event.output_summary)
