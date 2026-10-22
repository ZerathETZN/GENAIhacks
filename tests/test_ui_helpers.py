from ui import helpers as h

EXP = [
    {"outlet_id": "OUT-2", "severity": "low", "status": "confirmed", "sold_after_date_qty": 0, "batch": "B"},
    {"outlet_id": "OUT-1", "severity": "high", "status": "needs_review", "sold_after_date_qty": 3,
     "distinct_customers": 2, "batch": "B"},
    {"outlet_id": "OUT-3", "severity": "high", "status": "confirmed", "sold_after_date_qty": 12,
     "distinct_customers": 9, "batch": "B"},
]


def test_rank_by_severity_then_units_sold():
    assert [e["outlet_id"] for e in h.rank_exposures(EXP)] == ["OUT-3", "OUT-1", "OUT-2"]


def test_counts():
    assert h.counts(EXP) == {"exposures": 3, "confirmed": 2, "needs_review": 1, "outlets": 3, "high": 2}


def test_contact_line():
    assert h.contact_line(EXP[2]) == (
        "OUT-3 sold 12 units of batch B to 9 distinct (synthetic) loyalty customers after the notice date.")
    assert h.contact_line(EXP[0]) is None


def test_trace_summary_counts_critic_revisions_and_models():
    events = [
        {"agent_name": "ReconcilerAgent", "action": "match", "target_agent": "ConflictCriticAgent",
         "sponsor_call": "meterless.nightshift", "served_by": "nvidia/nemotron-3.5-lightning-30b-a3b"},
        {"agent_name": "ConflictCriticAgent", "action": "verify_query", "status": "needs_revision",
         "target_agent": "ReconcilerAgent", "sponsor_call": "zetaris"},
        {"agent_name": "ConflictCriticAgent", "action": "escalate", "status": "needs_review"},
    ]
    s = h.trace_summary(events)
    assert s["handoffs"] == 2 and s["critic_revisions"] == 1 and s["needs_review"] == 1
    assert s["served_by"] == ["nvidia/nemotron-3.5-lightning-30b-a3b"]
    assert s["sponsor_calls"] == {"meterless.nightshift": 1, "zetaris": 1}
