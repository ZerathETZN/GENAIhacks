"""MemoryRetrievalService: read side of H-MEM. Returns structured payloads with
trace metadata (spec §8.2), so the Reconciler can cite exactly what it used."""

from __future__ import annotations

from typing import Any

from app.meterless.hmem.store import MemoryStoreService
from app.meterless.world_model import norm


class MemoryRetrievalService:
    def __init__(self, store: MemoryStoreService) -> None:
        self.store = store

    def _canon(self, field: str, value: str) -> tuple[str, Any]:
        row = self.store.db.execute(
            "SELECT * FROM aliases WHERE field = ? AND alias_norm = ?", (field, norm(value))
        ).fetchone()
        return (row["canonical_norm"], row) if row else (norm(value), None)

    def same(self, field: str, a: str, b: str) -> dict[str, Any] | None:
        """Do verified memories say `a` and `b` are the same thing? None if unknown.

        Matches alias->canonical, canonical->alias, and two aliases of one canonical.
        """
        ca, ra = self._canon(field, a)
        cb, rb = self._canon(field, b)
        if ca != cb or norm(a) == norm(b):
            return None
        hit = ra or rb
        self.store.db.execute("UPDATE aliases SET access_count = access_count + 1 WHERE id = ?", (hit["id"],))
        self.store.db.commit()
        return {
            "memory_id": hit["id"],
            "field": field,
            "canonical": hit["canonical_raw"],
            "confidence": hit["confidence"],
            "source": hit["source"],
            "strategy": "exact_alias",
            "retrieval_reason": f"verified alias for {field} ({hit['source']})",
        }
