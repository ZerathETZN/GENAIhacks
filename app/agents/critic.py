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
from app.agents.retriever import name_tokens
from app.meterless.hmem import MemoryStoreService
from app.meterless.world_model import norm
from app.reconcile.aggregate import UNASSIGNED, ExposureDraft
from app.schemas import CriticCheck, Recall, TraceEvent

NAME = "ConflictCriticAgent"
_REG = "UPPER(REPLACE(REPLACE(reg_no, '-', ''), ' ', ''))"
# Batches are normalised in Python with norm() (all non-alphanumerics), not in SQL: a SQL REPLACE chain
# missed characters like '/' ("BN2404/23"). Cost: rows come back per outlet+product, then are filtered.
_PRODUCT = f"({_REG} = ? OR LOWER(product_name) LIKE ? OR LOWER(product_name) LIKE ?)"
_STOCK = f"SELECT batch, qty_on_hand FROM inventory_pg.stock WHERE outlet_id = ? AND {_PRODUCT}"
# POS has no reg_no, so product is matched by name token only. Dates compare as ISO strings.
_SALES = "SELECT batch, qty, loyalty_id FROM pos_pg.sales WHERE outlet_id = ? AND (LOWER(product_name) LIKE ? OR LOWER(product_name) LIKE ?) AND CAST(sold_at AS VARCHAR) >= ?"
_TRANSFERS = f"SELECT transfer_id, leg, batch FROM inventory_pg.transfers WHERE (outlet_id = ? OR counterparty_outlet_id = ?) AND {_PRODUCT}"


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
        batches, reg, likes = set(d.batch_norms) | {norm(d.batch)}, norm(d.reg_no or recall.reg_no), name_tokens(recall.product_name)
        stock = [r for r in self.adapter.query(_STOCK, [d.outlet_id, reg, *likes]) if norm(r["batch"] or "") in batches]
        sales = [r for r in self.adapter.query(_SALES, [d.outlet_id, *likes, recall.date]) if norm(r["batch"] or "") in batches]
        legs: dict[str, set[str]] = {}
        for r in self.adapter.query(_TRANSFERS, [d.outlet_id, d.outlet_id, reg, *likes]):
            if norm(r["batch"] or "") in batches:
                legs.setdefault(r["transfer_id"], set()).add(r["leg"])
        one_leg = sorted(t for t, ls in legs.items() if len(ls) < 2)

        observed = {
            "on_hand_qty": sum(int(r["qty_on_hand"]) for r in stock),
            "sold_after_date_qty": sum(int(r["qty"]) for r in sales),
            "distinct_customers": len({r["loyalty_id"] for r in sales if r["loyalty_id"]}),
        }
        expected = {k: getattr(d, k) for k in observed}
        passed = observed == expected
        d.critic_check = CriticCheck(query=f"{_STOCK} | {_SALES} | {_TRANSFERS}", expected=expected, observed=observed, passed=passed)

        # shortcut: the raw tables are the source of truth, so on a mismatch we adopt them once
        # and send the group to a human; a second round would run the same query. Upgrade if a check ever becomes non-deterministic.
        if not passed:
            for k, v in observed.items():
                setattr(d, k, v)
            d.status, d.reasons = "needs_review", d.reasons + [f"critic: raw tables disagree ({expected} vs {observed})"]
        if one_leg:
            d.status, d.reasons = "needs_review", d.reasons + [f"transfer with a missing leg: {one_leg}"]
        if passed and not one_leg and d.status == "confirmed":
            for name in d.names:  # verified by an independent query, so the spelling is safe to remember
                self.hmem.remember_alias("product_name", name, recall.product_name, "critic_check", self.run_id, NAME, d.confidence)

        self.emit(TraceEvent(
            run_id=self.run_id, agent_name=NAME, action="verify_exposure", input_summary=f"{d.outlet_id}/{d.batch}"[:200],
            output_summary=f"passed={passed} one_leg={len(one_leg)} status={d.status}"[:200],
            sponsor_call="zetaris" if self.adapter.name == "zetaris" else None, duration_ms=int((time.monotonic() - t0) * 1000),
        ))
        return d
