"""ConflictCriticAgent: deterministic, no model. Re-derives each draft from the RAW
tables (not the view the Retriever used), so a bug in the view or in the
Reconciler cannot confirm itself (AGENTS.md §7.4).

Raw table contract from A (23 Oct, locked in AGENTS.md §7.4):
  inventory_pg.stock      outlet_id, product_name, reg_no, batch, qty_on_hand
  inventory_pg.transfers  transfer_id, leg (out|in), outlet_id, counterparty_outlet_id, product_name, reg_no, batch, qty
  pos_pg.sales            outlet_id, product_name, batch, qty, sold_at, loyalty_id   (no reg_no)
Zetaris may return every value as a string, so SQL casts and Python uses int().
"""

from __future__ import annotations

import time
from typing import Callable

from app.adapters import DataAdapter
from app.agents.retriever import name_token
from app.meterless.hmem import MemoryStoreService
from app.meterless.world_model import norm
from app.reconcile.aggregate import UNASSIGNED, ExposureDraft
from app.schemas import CriticCheck, Recall, TraceEvent

NAME = "ConflictCriticAgent"
_BATCH = "UPPER(REPLACE(REPLACE(batch, '-', ''), ' ', ''))"
_REG = "UPPER(REPLACE(REPLACE(reg_no, '-', ''), ' ', ''))"

_STOCK = (
    f"SELECT COALESCE(SUM(CAST(qty_on_hand AS INTEGER)), 0) AS n FROM inventory_pg.stock "
    f"WHERE outlet_id = ? AND {_BATCH} = ? AND ({_REG} = ? OR LOWER(product_name) LIKE ?)"
)
# POS has no reg_no, so product is matched by name token only. Dates compare as ISO strings.
_SALES = (
    "SELECT COALESCE(SUM(CAST(qty AS INTEGER)), 0) AS n, COUNT(DISTINCT loyalty_id) AS c FROM pos_pg.sales "
    f"WHERE outlet_id = ? AND {_BATCH} = ? AND LOWER(product_name) LIKE ? AND CAST(sold_at AS VARCHAR) >= ?"
)
# A transfer with a missing leg is a conflict (A: needs_review, never a quantity adjustment).
_ONE_LEG = (
    "SELECT transfer_id FROM inventory_pg.transfers "
    f"WHERE (outlet_id = ? OR counterparty_outlet_id = ?) AND {_BATCH} = ? AND ({_REG} = ? OR LOWER(product_name) LIKE ?) "
    "GROUP BY transfer_id HAVING COUNT(DISTINCT leg) < 2"
)


class ConflictCriticAgent:
    def __init__(
        self,
        adapter: DataAdapter,
        hmem: MemoryStoreService,
        run_id: str,
        emit: Callable[[TraceEvent], None] = lambda e: None,
    ) -> None:
        self.adapter, self.hmem, self.run_id, self.emit = adapter, hmem, run_id, emit

    def review(self, recall: Recall, drafts: list[ExposureDraft]) -> list[ExposureDraft]:
        return [self._check(recall, d) for d in drafts]

    def _check(self, recall: Recall, d: ExposureDraft) -> ExposureDraft:
        if d.outlet_id == UNASSIGNED:  # no outlet to query; the Reporter lists it as unresolved
            return d
        t0 = time.monotonic()
        batch, reg, like = norm(d.batch), norm(d.reg_no or recall.reg_no), f"%{name_token(recall.product_name)}%"
        stock = self.adapter.query(_STOCK, [d.outlet_id, batch, reg, like])[0]
        sales = self.adapter.query(_SALES, [d.outlet_id, batch, like, recall.date])[0]
        one_leg = self.adapter.query(_ONE_LEG, [d.outlet_id, d.outlet_id, batch, reg, like])

        observed = {"on_hand_qty": int(stock["n"]), "sold_after_date_qty": int(sales["n"]), "distinct_customers": int(sales["c"])}
        expected = {k: getattr(d, k) for k in observed}
        passed = observed == expected
        d.critic_check = CriticCheck(query=f"{_STOCK} | {_SALES}", expected=expected, observed=observed, passed=passed)

        # shortcut: the raw tables are the source of truth, so on a mismatch we adopt them once
        # and send the group to a human; a second round would run the same query. Upgrade if a check ever becomes non-deterministic.
        if not passed:
            for k, v in observed.items():
                setattr(d, k, v)
            d.status, d.reasons = "needs_review", d.reasons + [f"critic: raw tables disagree ({expected} vs {observed})"]
        if one_leg:
            d.status, d.reasons = "needs_review", d.reasons + [f"transfer with a missing leg: {sorted(r['transfer_id'] for r in one_leg)}"]
        if passed and not one_leg and d.status == "confirmed":
            for name in d.names:  # verified by an independent query, so the spelling is safe to remember
                self.hmem.remember_alias("product_name", name, recall.product_name, "critic_check", self.run_id, NAME, d.confidence)

        self.emit(TraceEvent(
            run_id=self.run_id, agent_name=NAME, action="verify_exposure", input_summary=f"{d.outlet_id}/{d.batch}"[:200],
            output_summary=f"passed={passed} one_leg={len(one_leg)} status={d.status}"[:200],
            sponsor_call="zetaris" if self.adapter.name == "zetaris" else None, duration_ms=int((time.monotonic() - t0) * 1000),
        ))
        return d
