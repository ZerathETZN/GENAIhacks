"""Adapter selection (AGENTS.md §5.1).

  get_adapter()                 -> DuckDB if SAMPLE_MODE=true or Zetaris env is missing,
                                   else Zetaris wrapped so a runtime failure falls back to DuckDB
  get_adapter(sample_mode=True) -> DuckDB, whatever the env says

`adapter.name` is "zetaris" while Zetaris answers and "duckdb" otherwise (the Critic uses
it to tag sponsor_call). `adapter.result_name` is the RunResult.adapter value
("zetaris" | "duckdb" | "duckdb_fallback") and `adapter.fallback_reason` says why, for
the orchestrator's `adapter_fallback` trace event.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.adapters.data_adapter import AdapterError, Catalogue, DataAdapter, Params, Row
from app.adapters.duckdb_adapter import DuckDBAdapter

logger = logging.getLogger(__name__)

_ZETARIS_ENV = ("ZETARIS_REST_URL", "ZETARIS_API_KEY", "ZETARIS_ORG_ID")


class FallbackAdapter(DataAdapter):
    """Zetaris first; on a recoverable failure, switch to DuckDB for the rest of the run."""

    def __init__(self, primary: DataAdapter, data_dir: str | Path | None = None) -> None:
        self.primary = primary
        self.data_dir = data_dir
        self.secondary: DataAdapter | None = None
        self.fallback_reason: str | None = None

    @property
    def name(self) -> str:  # type: ignore[override]
        return self.secondary.name if self.secondary else self.primary.name

    @property
    def result_name(self) -> str:
        return "duckdb_fallback" if self.secondary else self.primary.name

    def _fall_back(self, reason: str) -> DataAdapter:
        logger.warning("adapter_fallback: %s", reason)
        self.fallback_reason = reason
        self.secondary = DuckDBAdapter(self.data_dir)
        return self.secondary

    def catalogue(self) -> Catalogue:
        if self.secondary:
            return self.secondary.catalogue()
        try:
            return self.primary.catalogue()
        except AdapterError as e:
            if not e.recoverable:
                raise
            return self._fall_back(str(e)).catalogue()

    def query(self, sql: str, params: Params = None, limit: int = 1000) -> list[Row]:
        if self.secondary:
            return self.secondary.query(sql, params, limit)
        try:
            return self.primary.query(sql, params, limit)
        except AdapterError as e:
            if not e.recoverable:
                raise
            return self._fall_back(str(e)).query(sql, params, limit)


def _sample_mode_env() -> bool:
    return os.getenv("SAMPLE_MODE", "").strip().lower() in ("1", "true", "yes")


def get_adapter(sample_mode: bool | None = None, data_dir: str | Path | None = None) -> DataAdapter:
    """`sample_mode=None` reads SAMPLE_MODE from the env. `data_dir` overrides data/sample
    (e.g. data/tuning/seed7); RG_DATA_DIR in the env does the same."""
    if sample_mode is None:
        sample_mode = _sample_mode_env()
    if sample_mode:
        a = DuckDBAdapter(data_dir)
        a.result_name, a.fallback_reason = "duckdb", None  # type: ignore[attr-defined]
        return a
    missing = [k for k in _ZETARIS_ENV if not os.getenv(k)]
    if missing:
        a = DuckDBAdapter(data_dir)
        a.result_name, a.fallback_reason = "duckdb_fallback", f"missing env: {', '.join(missing)}"  # type: ignore[attr-defined]
        logger.warning("adapter_fallback: %s", a.fallback_reason)  # type: ignore[attr-defined]
        return a
    from app.adapters.zetaris_adapter import ZetarisAdapter

    return FallbackAdapter(ZetarisAdapter(), data_dir)
