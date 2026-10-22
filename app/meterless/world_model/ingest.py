"""IngestPipelineService: idempotent, resumable writes into the World Model.

Records are committed in batches; each batch and its checkpoint share one
transaction. Re-running the same stream is a no-op (content-hash upsert) and a
run interrupted mid-stream resumes at the last committed batch.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from app.meterless.world_model.store import WorldStoreService

BATCH_SIZE = 100


class IngestPipelineService:
    def __init__(self, store: WorldStoreService, batch_size: int = BATCH_SIZE) -> None:
        self.store = store
        self.batch_size = batch_size

    def ingest(self, run_id: str, stream: str, records: Iterable[dict[str, Any]], agent_id: str) -> dict[str, int]:
        """Ingest `records` (each {type, source, record_id, attrs}) for one stream.

        Returns counts of created/updated/unchanged/skipped (already checkpointed).
        An exception from `records` or the store leaves earlier batches committed.
        """
        db = self.store.db
        row = db.execute(
            "SELECT committed FROM ingest_checkpoints WHERE run_id = ? AND stream = ?", (run_id, stream)
        ).fetchone()
        committed = row["committed"] if row else 0
        counts: Counter[str] = Counter(skipped=committed)

        batch: list[dict[str, Any]] = []
        position = 0
        for rec in records:
            position += 1
            if position <= committed:
                continue
            batch.append(rec)
            if len(batch) == self.batch_size:
                committed = self._commit(run_id, stream, batch, agent_id, committed, counts)
                batch = []
        if batch:
            self._commit(run_id, stream, batch, agent_id, committed, counts)
        return {k: counts[k] for k in ("created", "updated", "unchanged", "skipped")}

    def _commit(self, run_id, stream, batch, agent_id, committed, counts) -> int:
        db = self.store.db
        try:
            for rec in batch:
                counts[self.store.upsert(rec, run_id, agent_id)] += 1
            committed += len(batch)
            db.execute(
                "INSERT INTO ingest_checkpoints VALUES (?, ?, ?)"
                " ON CONFLICT (run_id, stream) DO UPDATE SET committed = excluded.committed",
                (run_id, stream, committed),
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        return committed
