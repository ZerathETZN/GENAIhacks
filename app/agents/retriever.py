"""RetrieverAgent: deterministic, no model. Reads through the DataAdapter and
writes every row into the World Model with provenance (AGENTS.md §3).

CONTRACT with the data layer (Zetaris view / DuckDB twin, owner A): the view
`recallguard.product_exposure_v` returns one row per internal record with the
columns in COLUMNS. `event_type` is stock | sale | delivery | transfer.
TODO(verify): confirm names and the positional `?` parameter style with A.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable

from app.adapters import DataAdapter
from app.meterless.world_model import IngestPipelineService
from app.schemas import Recall, TraceEvent

NAME = "RetrieverAgent"
VIEW = "recallguard.product_exposure_v"
COLUMNS = ("source", "record_id", "outlet_id", "product_name", "reg_no", "batch", "qty", "event_type", "event_date", "customer_id")
LIMIT = 5000  # shortcut: one fetch capped here; page it if a chain ever exceeds this
_ENTITY = {"stock": "StockRecord", "transfer": "StockRecord", "sale": "SaleRecord", "delivery": "Delivery"}

# Batch is deliberately not filtered here: the Reconciler needs near-miss batches
# to flag them. Plain ANSI (UPPER/REPLACE/LIKE) so the same text runs on Zetaris and DuckDB.
_SQL = (
    f"SELECT {', '.join(COLUMNS)} FROM {VIEW} "
    "WHERE UPPER(REPLACE(REPLACE(reg_no, '-', ''), ' ', '')) = ? OR LOWER(product_name) LIKE ?"
)


def name_token(product_name: str) -> str:
    words = re.findall(r"[A-Za-z]{4,}", product_name)
    return max(words, key=len).lower() if words else product_name.lower()


class RetrieverAgent:
    def __init__(
        self,
        adapter: DataAdapter,
        ingest: IngestPipelineService,
        run_id: str,
        emit: Callable[[TraceEvent], None] = lambda e: None,
    ) -> None:
        self.adapter, self.ingest, self.run_id, self.emit = adapter, ingest, run_id, emit

    def retrieve(self, recall: Recall) -> list[dict[str, Any]]:
        """Return neutral records for the recalled product and ingest them."""
        t0 = time.monotonic()
        params = [re.sub(r"[^A-Z0-9]", "", recall.reg_no.upper()), f"%{name_token(recall.product_name)}%"]
        rows = self.adapter.query(_SQL, params, limit=LIMIT)
        self._trace("query_view", f"{VIEW} reg_no={recall.reg_no}", f"{len(rows)} rows", "zetaris" if self.adapter.name == "zetaris" else None, t0)

        t0 = time.monotonic()
        records = [
            {"type": _ENTITY[r["event_type"]], "source": r["source"], "record_id": str(r["record_id"]), "attrs": r}
            for r in rows
            if r.get("event_type") in _ENTITY
        ]
        records.append({
            "type": "RegulatorNotice", "source": "regulator", "record_id": f"{recall.reg_no}:{recall.date}",
            "attrs": recall.model_dump(),
        })
        counts = self.ingest.ingest(self.run_id, "recall_view", records, NAME)
        self._trace("ingest_world_model", f"{len(records)} records", str(counts), "meterless.world_model", t0)
        return rows

    def _trace(self, action: str, inp: str, out: str, sponsor: str | None, t0: float) -> None:
        self.emit(TraceEvent(
            run_id=self.run_id, agent_name=NAME, action=action, input_summary=inp[:200], output_summary=out[:200],
            sponsor_call=sponsor, duration_ms=int((time.monotonic() - t0) * 1000),
        ))
