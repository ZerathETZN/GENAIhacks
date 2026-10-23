"""MemoryStoreService: durable cross-run memory (H-MEM engine spec §4, §5, §13).

We only keep alias memories: "this POS/supplier spelling is the same thing as
this canonical value". An alias is stored only when it was verified (the
Critic's Zetaris check passed, a human verdict confirmed it, or it is a
committed seed); the Reconciler's own guesses are never written, otherwise one
wrong guess would be remembered and trusted on every later run.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.meterless.world_model import norm

VERIFIED_SOURCES = ("critic_check", "human_verdict", "seed")

_DDL = """
CREATE TABLE IF NOT EXISTS aliases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  field TEXT NOT NULL,
  alias_norm TEXT NOT NULL,
  canonical_norm TEXT NOT NULL,
  alias_raw TEXT NOT NULL,
  canonical_raw TEXT NOT NULL,
  confidence REAL NOT NULL,
  source TEXT NOT NULL,
  run_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  access_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (field, alias_norm)
);
"""


class MemoryStoreService:
    def __init__(self, path: str = ":memory:") -> None:
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_DDL)
        self.db.commit()

    def remember_alias(
        self, field: str, alias: str, canonical: str, source: str, run_id: str, agent_id: str, confidence: float = 1.0
    ) -> bool:
        """Store a verified alias. Returns False when there is nothing to learn
        (formats that `norm` already equates). A later verified mapping for the
        same alias replaces the earlier one."""
        if source not in VERIFIED_SOURCES:
            raise ValueError(f"alias source must be one of {VERIFIED_SOURCES}, got {source!r}")
        a, c = norm(alias), norm(canonical)
        if not a or not c or a == c:
            return False
        self.db.execute(
            "INSERT INTO aliases (field, alias_norm, canonical_norm, alias_raw, canonical_raw, confidence, source, run_id, agent_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (field, alias_norm) DO UPDATE SET canonical_norm = excluded.canonical_norm,"
            " canonical_raw = excluded.canonical_raw, confidence = excluded.confidence, source = excluded.source,"
            " run_id = excluded.run_id, agent_id = excluded.agent_id",
            (field, a, c, alias, canonical, confidence, source, run_id, agent_id),
        )
        self.db.commit()
        return True

    def load_jsonl(self, path: str, source: str, run_id: str, agent_id: str = "MemoryStoreService") -> int:
        """Load confirmed aliases, one JSON object per line: {field, alias, canonical}.
        Used for state/seed_memory.jsonl (source='seed') and data/feedback/decisions.jsonl
        (source='human_verdict'). TODO(verify): final decisions.jsonl shape with the team."""
        p = Path(path)
        if not p.exists():
            return 0
        n = 0
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                n += self.remember_alias(r["field"], r["alias"], r["canonical"], source, run_id, agent_id)
        return n
