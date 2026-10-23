from app.agents.reconciler import Candidate
from app.reconcile.aggregate import UNASSIGNED, build_drafts
from app.schemas import Recall

RECALL = Recall(product_name="Paracetamol 500mg Tablet", reg_no="MAL12345678A", batches=["NSC24067"], date="2026-10-01")


def cand(rid, event_type, qty, outlet="OUT-01", batch="NSC24067", date="2026-09-01", customer=None, status="match", conf=1.0, reg_no="MAL12345678A"):
    rec = {"source": "inventory", "record_id": rid, "outlet_id": outlet, "product_name": "Paracetamol", "reg_no": reg_no,
           "batch": batch, "qty": qty, "event_type": event_type, "event_date": date, "customer_id": customer}
    return Candidate(rec, status, conf, "reg_no")


def test_groups_per_outlet_and_batch_and_counts_only_post_recall_sales():
    drafts = build_drafts(RECALL, [
        cand("S1", "stock", 12),
        cand("S2", "stock", 3, batch="nsc-24067"),  # same batch, other spelling: one group
        cand("P1", "sale", 2, date="2026-10-03", customer="c1", reg_no=None),
        cand("P2", "sale", 4, date="2026-10-05", customer="c1", reg_no=None),
        cand("P3", "sale", 9, date="2026-09-20", customer="c9", reg_no=None),  # before the recall
        cand("S3", "stock", 7, outlet="OUT-02"),
    ])
    a, b = drafts
    assert (a.outlet_id, a.on_hand_qty, a.sold_after_date_qty, a.distinct_customers, a.status) == ("OUT-01", 15, 6, 1, "confirmed")
    assert (b.outlet_id, b.on_hand_qty, b.sold_after_date_qty) == ("OUT-02", 7, 0)


def test_one_uncertain_row_makes_the_group_needs_review_with_lowest_confidence():
    d = build_drafts(RECALL, [cand("S1", "stock", 5, conf=0.9), cand("S2", "stock", 1, status="needs_review", conf=0.3)])[0]
    assert (d.status, d.confidence) == ("needs_review", 0.3)


def test_unassigned_delivery_is_kept_and_has_evidence():
    d = build_drafts(RECALL, [cand("D1", "delivery", 50, outlet=None)])[0]
    assert (d.outlet_id, d.on_hand_qty) == (UNASSIGNED, 0) and d.evidence == []
    assert d.status == "needs_review" and "no outlet" in d.reasons[0]  # A: never ranked as an outlet


def test_delivery_without_stock_record_needs_review():
    d = build_drafts(RECALL, [cand("D1", "delivery", 30), cand("P1", "sale", 1, date="2026-10-03", customer="c1", reg_no=None)])[0]
    assert d.status == "needs_review" and "no stock record" in d.reasons[-1]


def test_typo_batch_sales_are_counted_under_the_recalled_batch_and_flagged():
    typo = cand("P2", "sale", 2, batch="NSC-24O67", date="2026-10-04", customer="c2", reg_no=None, status="needs_review", conf=0.4)
    typo.reasons.append("batch near-miss")
    drafts = build_drafts(RECALL, [cand("S1", "stock", 5), typo])
    assert len(drafts) == 1 and (drafts[0].batch, drafts[0].sold_after_date_qty, drafts[0].status) == ("NSC24067", 2, "needs_review")
