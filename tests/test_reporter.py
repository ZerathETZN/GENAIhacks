from app.agents.reporter import ReporterAgent, pick_rule
from app.llm import GenerationResult
from app.reconcile.aggregate import ExposureDraft
from app.schemas import Recall

R = dict(product_name="Paracetamol", reg_no="MAL1", date="2026-10-01")
no_model = lambda *a, **k: GenerationResult(text="", provider="heuristic_fallback", served_by=None, latency_ms=0)


def d(outlet, sold, hand, status="confirmed"):
    return ExposureDraft(outlet, "Paracetamol", "MAL1", "B1", hand, sold, 2 if sold else 0, status, 0.9, reasons=["why"] if status != "confirmed" else [])


def test_rule_choice():
    assert pick_rule(Recall(**R, batches=["B1"], degree_level="Degree II recall")) == "degree-II"
    assert pick_rule(Recall(**R, batches=["B1"], degree_level="Degree III")) == "degree-III"
    assert pick_rule(Recall(**R, batches=["B1"])) == "voluntary-no-degree"
    assert pick_rule(Recall(**R)) == "administrative"


def test_safety_recall_ranks_by_sold_and_unassigned_is_not_an_outlet():
    out = ReporterAgent("r1", no_model).report(Recall(**R, batches=["B1"], degree_level="Degree I"),
                                               [d("O1", 1, 50), d("O2", 9, 5), d("UNASSIGNED", 0, 0, "needs_review")])
    assert [e.outlet_id for e in out.exposures] == ["O2", "O1"]
    assert out.exposures[0].severity == "high" and out.exposures[0].rule_ref == "actions.yaml#degree-I"
    assert "9 units of batch B1 to 2 distinct" in out.exposures[0].recommended_action
    assert [c["outlet_id"] for c in out.unresolved_conflicts] == ["UNASSIGNED"]
    assert "2 outlets exposed" in out.summary  # templated fallback


def test_administrative_ranks_by_stock_and_uses_model_text_when_given():
    ai = lambda *a, **k: GenerationResult(text=" Two outlets hold stock. ", provider="meterless", served_by="m", latency_ms=5)
    out = ReporterAgent("r1", ai).report(Recall(**R), [d("O1", 9, 5), d("O2", 0, 50)])
    assert [e.outlet_id for e in out.exposures] == ["O2", "O1"] and out.summary == "Two outlets hold stock."


def test_level_c_lowers_severity_and_level_b_skips_customer_contact():
    drafts = [d("O1", 9, 5)]
    c = ReporterAgent("r1", no_model).report(Recall(**R, batches=["B1"], degree_level="Degree I sub-distributor (wholesaler)"), drafts).exposures[0]
    assert c.severity == "medium" and "Level C" in c.recommended_action
    b = ReporterAgent("r1", no_model).report(Recall(**R, batches=["B1"], degree_level="sales"), drafts).exposures[0]
    assert b.rule_ref == "actions.yaml#voluntary-no-degree" and "distinct loyalty" not in b.recommended_action
