"""scripts/evaluate.py scores results against an answer key correctly."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("evaluate", ROOT / "scripts" / "evaluate.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

TRUTH = {
    "exposures": [
        {"recall_id": "R1", "outlet_id": "OUT-01", "batch_norm": "B1", "on_hand_qty": 5, "sold_after_date_qty": 2,
         "distinct_customers": 1, "expected_status": "confirmed", "conflicts": []},
        {"recall_id": "R1", "outlet_id": "OUT-02", "batch_norm": "B1", "on_hand_qty": 0, "sold_after_date_qty": 0,
         "distinct_customers": 0, "expected_status": "needs_review", "conflicts": ["batch_typo"]},
    ],
    "decoys": [{"outlet_id": "OUT-03", "reg_no": "MAL1", "batch_norm": "B9"}],
    "unassigned": [{"recall_id": "R1"}],
}


def _exp(outlet, batch, on_hand=5, sold=2, cust=1, status="confirmed", reg="MAL1", recall_id=None):
    return {"outlet_id": outlet, "batch": batch, "reg_no": reg, "on_hand_qty": on_hand, "sold_after_date_qty": sold,
            "distinct_customers": cust, "status": status, "recall_id": recall_id}


def _res(exposures, conflicts=()):
    return {"status": "success", "adapter": "duckdb",
            "output": {"exposures": exposures, "unresolved_conflicts": list(conflicts)}}


def test_perfect_run():
    s = ev.score([("R1", _res([_exp("OUT-01", "b-1"), _exp("OUT-02", "B1", 0, 0, 0, "needs_review")],
                               [{"outlet_id": "UNASSIGNED"}]))], TRUTH)
    assert (s["found"], s["precision"], s["recall"], s["quantities_correct"], s["status_correct"]) == (2, 1.0, 1.0, 2, 2)
    assert s["unassigned_reported"] == 1 and not s["decoy_false_positives"]


def test_miss_extra_decoy_qty_and_status_are_counted():
    s = ev.score([("R1", _res([_exp("OUT-01", "B1", on_hand=4, status="needs_review"), _exp("OUT-03", "B9")]))], TRUTH)
    assert [k[1] for k in s["missed"]] == ["OUT-02"]
    assert [k[1] for k in s["extra"]] == ["OUT-03"]
    assert len(s["decoy_false_positives"]) == 1
    assert s["quantities_correct"] == 0 and s["status_correct"] == 0


def test_recalls_outside_the_key_are_not_scored():
    s = ev.score([("R1", _res([_exp("OUT-01", "B1"), _exp("OUT-02", "B1", 0, 0, 0, "needs_review")])),
                  ("R-OTHER", _res([_exp("OUT-05", "X")]))], TRUTH)
    assert s["extra"] == [] and s["unkeyed_recalls"] == ["R-OTHER"]


def test_failed_run_is_reported_not_crashing():
    s = ev.score([("R1", {"status": "error", "adapter": "duckdb", "error": {"message": "boom"}})], TRUTH)
    assert s["errors"] == [("R1", "boom")] and s["found"] == 0
