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


def test_tally_and_split_action():
    assert h.tally(EXP) == {"outlets": 3, "on_hand": 0, "sold": 15, "customers": 11, "needs_review": 1}
    action, contact = h.split_action("Stop selling within 24 h. (DRGD App. 34 s4.3) Outlet OUT-05 sold 7 units of batch X.")
    assert action.endswith("s4.3)") and contact.startswith("Outlet OUT-05 sold 7")
    assert h.split_action("Quarantine stock.") == ("Quarantine stock.", None)


def test_visuals_use_only_run_evidence():
    from ui import visuals as v
    exps = [{"evidence": [{"source": "pos", "record_id": "S1", "field": "batch", "value": "s036723"},
                          {"source": "supplier", "record_id": "D1", "field": "batch", "value": "503-6723"}]}]
    sp = v.spellings(exps)
    assert sp["pos"]["batch"] == ["s036723"] and sp["supplier"]["n"] == 1
    html = v.spellings_html(sp, ["5036723"])
    assert 'class="sp-b odd">s036723' in html and 'class="sp-b">503-6723' in html  # 503-6723 normalises to 5036723
    assert v.as_img(v.pipeline_svg([]), "x").startswith('<img src="data:image/svg+xml;base64,')


def test_critic_rejection_counts_missing_transfer_leg():
    ev = {"agent_name": "ConflictCriticAgent", "action": "verify_exposure", "status": "ok",
          "output_summary": "passed=True one_leg=1 status=needs_review"}
    ok = {**ev, "output_summary": "passed=True one_leg=0 status=confirmed"}
    assert h.trace_summary([ev, ok])["critic_revisions"] == 1


def test_review_breakdown_matches_reporter_count():
    conflicts = [{"outlet_id": "OUT-04"}, {"outlet_id": "OUT-06"}, {"outlet_id": "UNASSIGNED"}]
    assert h.review_breakdown(conflicts) == (3, "2 outlets + 1 delivery with no outlet to check")
    assert h.review_breakdown([{"recall_id": "R", "error": "skipped"}]) == (1, "1 other item to check")


def test_recorded_runs_are_real_committed_runs():
    from pathlib import Path
    runs = h.recorded_runs(Path("output_examples"))
    assert {r["folder"] for r in runs} >= {"cold_warm", "daily-scan"}
    cold = next(r for r in runs if r["label"] == "cold_warm (cold)")
    assert cold["trace"] is not None and h.read_trace_file(cold["trace"])
