"""ContextBuilderService: the read surface every agent uses (World Model spec §10.2).

Returns a structured payload (not a prompt string) with trace metadata, so each
agent formats it for its own target and the trace can show what was selected.
"""

from __future__ import annotations

import re
from typing import Any

from app.meterless.world_model.store import WorldStoreService

DEFAULT_LIMIT = 50


def norm(value: Any) -> str:
    """Upper-case alphanumerics only, so 'nsc-24067' == 'NSC 24067'."""
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


class ContextBuilderService:
    def __init__(self, store: WorldStoreService) -> None:
        self.store = store

    def build(
        self,
        intent: str,
        types: list[str] | None = None,
        match: dict[str, Any] | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        """Select entities of `types` whose attrs equal every `match` value (normalised).

        `match` is e.g. {"batch": "NSC-24067", "reg_no": "MAL123"}; an entity
        lacking a matched attr is not selected. Each item keeps its provenance.
        """
        rows = [r for t in (types or [None]) for r in self.store.list(t)]
        if match:
            want = {k: norm(v) for k, v in match.items()}
            rows = [r for r in rows if all(norm(r["attrs"].get(k, "")) == v for k, v in want.items())]
        rows = rows[:limit]
        return {
            "intent": intent,
            "strategy": "match" if match else "type_scan",
            "selection_reason": f"types={types or 'all'} match={match or {}}",
            "entities": [
                {
                    "id": r["id"],
                    "type": r["type"],
                    "attrs": r["attrs"],
                    "provenance": {"source": r["source"], "record_id": r["record_id"], "run_id": r["run_id"], "agent_id": r["agent_id"]},
                }
                for r in rows
            ],
        }
