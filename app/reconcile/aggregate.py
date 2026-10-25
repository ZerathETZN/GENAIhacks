"""Turn matched records into one draft per (outlet, batch), using only the
agreed `product_exposure_v` columns (AGENTS.md §7.4). The Critic then checks
these drafts against the raw tables; the Reporter adds severity and action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from rapidfuzz import fuzz

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
    doubts: list[dict] = field(default_factory=list)  # spellings a pharmacist can answer (decisions.jsonl): {field, alias, canonical, record_ref}
    batch_norms: list[str] = field(default_factory=list)  # every spelling folded into this group (typos included)


def _home_batch(recall: Recall, c: Candidate) -> str:
    """Batch a record is counted under. A spelling that is not a recalled batch (a typo flagged as a near-miss,
    or one a pharmacist verified as the same) is counted under the recalled batch it most resembles, so its
    sales are not lost. shortcut: resemblance only; two similar recalled batches could be mixed up, upgrade
    by keeping the matched batch on the Candidate."""
    batch = c.record.get("batch") or ""
    if recall.batches and norm(batch) not in {norm(b) for b in recall.batches}:
        return max(recall.batches, key=lambda b: fuzz.ratio(norm(batch), norm(b)))
    return batch


def _doubts(recall: Recall, cs: list[Candidate]) -> list[dict]:
    """Spellings the agents could not settle, in the shape of a decisions.jsonl line (AGENTS.md §7.5)."""
    out: dict[tuple[str, str], dict] = {}
    for c in cs:
        rec = c.record
        ref = f"{rec['source']}:{rec['record_id']}"
        if c.status == "needs_review" and "batch near-miss" in c.reasons:
            out.setdefault(("batch", rec["batch"]), {"field": "batch", "alias": rec["batch"], "canonical": _home_batch(recall, c), "record_ref": ref})
        if c.via == "unresolved" and rec.get("product_name"):
            out.setdefault(("product_name", rec["product_name"]), {"field": "product_name", "alias": rec["product_name"], "canonical": recall.product_name, "record_ref": ref})
    return list(out.values())


def build_drafts(recall: Recall, candidates: list[Candidate]) -> list[ExposureDraft]:
    groups: dict[tuple[str, str], list[Candidate]] = {}
    for c in candidates:
        key = (c.record.get("outlet_id") or UNASSIGNED, norm(_home_batch(recall, c)))
        groups.setdefault(key, []).append(c)

    drafts = []
    for (outlet, _), cs in sorted(groups.items()):
        rows = [c.record for c in cs]
        if all(r["event_type"] == "transfer" for r in rows):  # a transfer leg alone is evidence for another group, never an exposure
            continue
        # shortcut: on hand = sum of stock snapshots only; transfers stay evidence. Confirm with A (TODO(verify)).
        on_hand = sum(int(r["qty"]) for r in rows if r["event_type"] == "stock")
        sales = [r for r in rows if r["event_type"] == "sale" and str(r["event_date"]) >= recall.date]
        first = rows[0]
        unassigned = outlet == UNASSIGNED
        no_stock = any(r["event_type"] == "delivery" for r in rows) and not any(r["event_type"] == "stock" for r in rows)
        drafts.append(ExposureDraft(
            outlet_id=outlet,
            product_name=first.get("product_name") or recall.product_name,
            reg_no=next((r["reg_no"] for r in rows if r.get("reg_no")), recall.reg_no),
            batch=_home_batch(recall, cs[0]),
            on_hand_qty=on_hand,
            sold_after_date_qty=sum(int(r["qty"]) for r in sales),
            distinct_customers=len({r["customer_id"] for r in sales if r.get("customer_id")}),
            status="confirmed" if not unassigned and not no_stock and all(c.status == "match" for c in cs) else "needs_review",
            confidence=min(c.confidence for c in cs),
            evidence=[e for c in cs for e in c.evidence],
            reasons=list(dict.fromkeys([x for c in cs for x in c.reasons] + (["delivered, no outlet recorded"] if unassigned else []) + (["delivered but no stock record"] if no_stock else []))),  # one line per distinct reason, not per record
            doubts=_doubts(recall, cs),
            batch_norms=sorted({norm(r.get("batch") or "") for r in rows}),
            names=sorted({r["product_name"] for r in rows if r.get("product_name")}),
        ))
    return drafts
