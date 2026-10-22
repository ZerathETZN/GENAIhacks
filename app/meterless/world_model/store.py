"""WorldStoreService: SQLite-backed canonical store (World Model engine spec §5, §12.5).

One row per entity, keyed by a content-derived id so independent agents agree
on identity without coordination. Every row carries provenance (source system
+ record id) and attribution (run_id, agent_id).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

SCHEMA_VERSION = 1

ENTITY_TYPES = ("Product", "Batch", "Outlet", "StockRecord", "SaleRecord", "Delivery", "RegulatorNotice")

_DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS entities (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  source TEXT NOT NULL,
  record_id TEXT NOT NULL,
  attrs TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  run_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (type, source, record_id)
);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities (type);
CREATE INDEX IF NOT EXISTS idx_entities_source_record ON entities (source, record_id);
CREATE TABLE IF NOT EXISTS ingest_checkpoints (
  run_id TEXT NOT NULL,
  stream TEXT NOT NULL,
  committed INTEGER NOT NULL,
  PRIMARY KEY (run_id, stream)
);
"""


def entity_id(type_: str, source: str, record_id: str) -> str:
    return "ent_" + hashlib.sha1(f"{type_}|{source}|{record_id}".encode()).hexdigest()[:16]


def content_hash(attrs: dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(attrs, sort_keys=True, default=str).encode()).hexdigest()


class WorldStoreService:
    def __init__(self, path: str = ":memory:") -> None:
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_DDL)
        self.db.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        self.db.commit()

    def upsert(self, rec: dict[str, Any], run_id: str, agent_id: str) -> str:
        """Write one record. Returns 'created' | 'updated' | 'unchanged'. Caller commits."""
        if rec["type"] not in ENTITY_TYPES:
            raise ValueError(f"unknown entity type {rec['type']!r}")
        eid = entity_id(rec["type"], rec["source"], rec["record_id"])
        h = content_hash(rec["attrs"])
        row = self.db.execute("SELECT content_hash FROM entities WHERE id = ?", (eid,)).fetchone()
        if row is None:
            self.db.execute(
                "INSERT INTO entities (id, type, source, record_id, attrs, content_hash, run_id, agent_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (eid, rec["type"], rec["source"], rec["record_id"], json.dumps(rec["attrs"], default=str), h, run_id, agent_id),
            )
            return "created"
        if row["content_hash"] == h:
            return "unchanged"
        self.db.execute(
            "UPDATE entities SET attrs = ?, content_hash = ?, run_id = ?, agent_id = ?,"
            " last_seen_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(rec["attrs"], default=str), h, run_id, agent_id, eid),
        )
        return "updated"

    def get(self, eid: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM entities WHERE id = ?", (eid,)).fetchone()
        return _to_dict(row) if row else None

    def resolve(self, source: str, record_id: str) -> list[dict[str, Any]]:
        """Provenance lookup: every entity written from this source record."""
        rows = self.db.execute("SELECT * FROM entities WHERE source = ? AND record_id = ?", (source, record_id))
        return [_to_dict(r) for r in rows]

    def list(self, type_: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM entities", ()
        if type_:
            sql, args = sql + " WHERE type = ?", (type_,)
        return [_to_dict(r) for r in self.db.execute(sql + " ORDER BY id", args)]

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM entities").fetchone()[0]


def _to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["attrs"] = json.loads(d["attrs"])
    return d
