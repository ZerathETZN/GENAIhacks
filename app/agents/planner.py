"""PlannerAgent: discovers what the data layer offers and checks the pipeline can run on it.

Deterministic, no model (AGENTS.md lists it as reasoning; the plan here is fixed, so a model adds nothing).
It calls `adapter.catalogue()`, never raw SHOW/DESCRIBE SQL, which DuckDB (sample mode) does not understand.
"""

from __future__ import annotations

import time
from typing import Callable

from app.adapters import DataAdapter
from app.agents.retriever import COLUMNS, VIEW
from app.schemas import TraceEvent

NAME = "PlannerAgent"
RAW_TABLES = ("inventory_pg.stock", "inventory_pg.transfers", "pos_pg.sales", "supplier_rest.deliveries")  # the Critic's sources


class PlannerError(RuntimeError):
    recoverable = False  # C's runner reads this: retrying the same request cannot fix a missing table


class PlannerAgent:
    def __init__(self, adapter: DataAdapter, run_id: str, emit: Callable[[TraceEvent], None] = lambda e: None) -> None:
        self.adapter, self.run_id, self.emit = adapter, run_id, emit

    def plan(self) -> dict:
        t0 = time.monotonic()
        try:
            cat = self.adapter.catalogue()
        except NotImplementedError:  # test doubles only; real adapters implement it
            self._trace("catalogue_discovery", "adapter has no catalogue()", "skipped", t0, "skipped")
            return {"view": VIEW, "raw_tables": list(RAW_TABLES)}
        tables = {t["table"].lower(): {c["name"].lower() for c in t["columns"]} for t in cat["tables"]}
        missing = [t for t in (VIEW, *RAW_TABLES) if t not in tables]
        if VIEW in tables:
            missing += [f"{VIEW}.{c}" for c in COLUMNS if c not in tables[VIEW]]
        self._trace("catalogue_discovery", " | ".join(cat["statements"]), f"{len(tables)} tables, missing={missing or 'none'}", t0, "error" if missing else "ok")
        if missing:
            raise PlannerError(f"data layer is missing {missing}")
        return {"view": VIEW, "raw_tables": list(RAW_TABLES)}

    def _trace(self, action: str, inp: str, out: str, t0: float, status: str) -> None:
        self.emit(TraceEvent(
            run_id=self.run_id, agent_name=NAME, action=action, input_summary=inp[:200], output_summary=out[:200],
            sponsor_call="zetaris" if self.adapter.name == "zetaris" else None, status=status,
            duration_ms=int((time.monotonic() - t0) * 1000),
        ))
