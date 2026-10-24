from ui import helpers as h

EXP = [
    {"outlet_id": "OUT-2", "severity": "low", "status": "confirmed", "sold_after_date_qty": 0, "batch": "B"},
    {"outlet_id": "OUT-1", "severity": "high", "status": "needs_review", "sold_after_date_qty": 3,
     "distinct_customers": 2, "batch": "B"},
    {"outlet_id": "OUT-3", "severity": "high", "status": "confirmed", "sold_after_date_qty": 12,
     "distinct_customers": 9, "batch": "B"},
]


def test_rank_groups_by_severity_and_keeps_reporter_order():
    assert [e["outlet_id"] for e in h.rank_exposures(EXP)] == ["OUT-1", "OUT-3", "OUT-2"]


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
    assert s["agents"] == ["ReconcilerAgent", "ConflictCriticAgent"]
    assert s["served_by"] == ["nvidia/nemotron-3.5-lightning-30b-a3b"]
    assert s["sponsor_calls"] == {"meterless.nightshift": 1, "zetaris": 1}


def test_trace_summary_reads_critic_output_summary():
    events = [
        {"agent_name": "PlannerAgent", "action": "catalogue_discovery"},
        {"agent_name": "RetrieverAgent", "action": "query_view", "sponsor_call": "zetaris"},
        {"agent_name": "ConflictCriticAgent", "action": "verify_exposure", "output_summary": "passed=False one_leg=1 status=needs_review"},
        {"agent_name": "ConflictCriticAgent", "action": "verify_exposure", "output_summary": "passed=True one_leg=0 status=confirmed"},
        {"agent_name": "Orchestrator", "action": "adapter_fallback", "status": "degraded"},
    ]
    s = h.trace_summary(events)
    assert s["handoffs"] == 2 and s["critic_checks"] == 2 and s["critic_revisions"] == 1 and s["needs_review"] == 1
    assert s["fallbacks"] == ["adapter_fallback"]


def test_review_items_and_verdict_line_match_contract():
    from app.schemas import HumanVerdict
    conflicts = [{"outlet_id": "OUT-04", "batch": "5036723", "reasons": [], "doubts": [
        {"field": "batch", "alias": "s036723", "canonical": "5036723", "record_ref": "pos:SAL-000007"}]}]
    items = h.review_items(conflicts)
    assert items[0]["outlet_id"] == "OUT-04"
    line = h.verdict_line(items[0], "same", "shermaine", "2026-10-24T10:00:00Z", "demo-cold", "s for 5")
    HumanVerdict.model_validate(line)
