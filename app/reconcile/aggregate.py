"""Turn matched records into one draft per (outlet, batch), using only the
agreed `product_exposure_v` columns (AGENTS.md §7.4). The Critic then checks
these drafts against the raw tables; the Reporter adds severity and action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.agents.reconciler import Candidate
from app.meterless.world_model import norm
from app.schemas import CriticCheck, Evidence, Recall

UNASSIGNED = "UNASSIGNED"  # delivery not yet assigned to an outlet (outlet_id NULL)


@dataclass
class ExposureDraft:
    outlet_id: str
    product_name: str
    reg_no: str | None
    batch: str
    on_hand_qty: int
    sold_after_date_qty: int
    distinct_customers: int
    status: Literal["confirmed", "needs_review"]
    confidence: float
    evidence: list[Evidence] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)  # distinct product names seen, for H-MEM learning
    critic_check: CriticCheck | None = None


def build_drafts(recall: Recall, candidates: list[Candidate]) -> list[ExposureDraft]:
    groups: dict[tuple[str, str], list[Candidate]] = {}
    for c in candidates:
        key = (c.record.get("outlet_id") or UNASSIGNED, norm(c.record.get("batch") or ""))
        groups.setdefault(key, []).append(c)

    drafts = []
    for (outlet, _), cs in sorted(groups.items()):
        rows = [c.record for c in cs]
        # shortcut: on hand = sum of stock snapshots only; transfers stay evidence. Confirm with A (TODO(verify)).
        on_hand = sum(int(r["qty"]) for r in rows if r["event_type"] == "stock")
        sales = [r for r in rows if r["event_type"] == "sale" and str(r["event_date"]) >= recall.date]
        first = rows[0]
        unassigned = outlet == UNASSIGNED
        drafts.append(ExposureDraft(
            outlet_id=outlet,
            product_name=first.get("product_name") or recall.product_name,
            reg_no=next((r["reg_no"] for r in rows if r.get("reg_no")), recall.reg_no),
            batch=first.get("batch") or "",
            on_hand_qty=on_hand,
            sold_after_date_qty=sum(int(r["qty"]) for r in sales),
            distinct_customers=len({r["customer_id"] for r in sales if r.get("customer_id")}),
            status="confirmed" if not unassigned and all(c.status == "match" for c in cs) else "needs_review",
            confidence=min(c.confidence for c in cs),
            evidence=[e for c in cs for e in c.evidence],
            reasons=[x for c in cs for x in c.reasons] + (["delivered, no outlet recorded"] if unassigned else []),
            names=sorted({r["product_name"] for r in rows if r.get("product_name")}),
        ))
    return drafts
