import json

from app.orchestrator import run
from app.schemas import Recall, RunInput, RunOptions, RunRequest, RunResult
from tests.test_critic import RawAdapter


class FullAdapter(RawAdapter):
    """Raw tables for the Critic plus the exposure view for the Retriever, same underlying facts."""
    def __init__(self):
        super().__init__()
        self.db.execute("CREATE SCHEMA recallguard")
        self.db.execute("CREATE TABLE recallguard.product_exposure_v (source VARCHAR, record_id VARCHAR, outlet_id VARCHAR, product_name VARCHAR, reg_no VARCHAR, batch VARCHAR, qty VARCHAR, event_type VARCHAR, event_date VARCHAR, customer_id VARCHAR)")
        self.db.execute("INSERT INTO recallguard.product_exposure_v VALUES "
                        "('inventory','s1','OUT-01','Paracetamol 500mg Tablet','MAL12345678A','NSC24067','12','stock','2026-09-30',NULL),"
                        "('pos','p1','OUT-01','PARACETAMOL TAB',NULL,'nsc24067','2','sale','2026-10-03','c1'),"
                        "('pos','p2','OUT-01','PARACETAMOL TAB',NULL,'nsc24067','4','sale','2026-10-05','c1'),"
                        "('pos','p3','OUT-01','PARACETAMOL TAB',NULL,'nsc24067','9','sale','2026-09-20','c9')")


def req(sample=True):
    recall = Recall(product_name="Paracetamol 500mg Tablet", reg_no="MAL12345678A", batches=["NSC-24067"], date="2026-10-01", degree_level="Degree I")
    return RunRequest(run_id="t1", input=RunInput(mode="recall_alert", recall=recall), options=RunOptions(sample_mode=sample))


def test_end_to_end_run_produces_valid_result_and_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    res = run(req(), FullAdapter(), str(tmp_path / "state"))
    RunResult.model_validate(res.model_dump())
    e = res.output.exposures[0]
    assert (e.outlet_id, e.on_hand_qty, e.sold_after_date_qty, e.status, e.severity) == ("OUT-01", 12, 6, "confirmed", "high")
    assert e.critic_check.passed and res.providers_used == ["heuristic_fallback"]
    actions = [json.loads(l)["action"] for l in open(res.log_file)]
    assert {"query_view", "verify_exposure", "summarise"} <= set(actions)


def test_second_run_reuses_hmem_from_the_first(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    run(req(), FullAdapter(), str(tmp_path / "state"))
    run(req(), FullAdapter(), str(tmp_path / "state"))  # same state dir: must not crash on existing world/hmem files


def test_daily_scan_merges_snapshot_recalls_for_stocked_products(tmp_path, monkeypatch):
    from app.adapters.factory import get_adapter

    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("DECISIONS_FILE", str(tmp_path / "none.jsonl"))
    monkeypatch.setattr("app.orchestrator.SCAN_LIMIT", 3)
    res = run(RunRequest(run_id="scan1", input=RunInput(mode="daily_scan"), options=RunOptions(sample_mode=True)),
              get_adapter(sample_mode=True, data_dir="data/sample"), str(tmp_path / "state"))
    out = res.output
    assert out.exposures and all(e.recall_id for e in out.exposures)
    assert len({e.recall_id for e in out.exposures}) == 3  # capped, newest first, each recall kept apart
    sev = [e.severity for e in out.exposures]
    assert sev == sorted(sev, key=["high", "medium", "low"].index)
    assert out.summary.startswith("Daily scan: 3 snapshot recalls")
    assert "daily_scan_select" in [json.loads(l)["action"] for l in open(res.log_file)]


def _scan_request():
    return RunRequest(run_id="scanx", input=RunInput(mode="daily_scan"), options=RunOptions(sample_mode=False))


def test_scan_stops_calling_a_dead_model_after_two_failures(tmp_path, monkeypatch):
    from app.adapters.factory import get_adapter
    from app.llm import GenerationResult

    calls = []
    monkeypatch.setattr("app.orchestrator.generate", lambda *a, **k: (calls.append(1), GenerationResult(text="", provider="heuristic_fallback", served_by=None, latency_ms=0))[1])
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("DECISIONS_FILE", str(tmp_path / "none.jsonl"))
    monkeypatch.setattr("app.orchestrator.SCAN_LIMIT", 9)
    res = run(_scan_request(), get_adapter(sample_mode=True, data_dir="data/sample"), str(tmp_path / "state"))
    assert len(calls) == 2 and res.status == "success" and res.output.exposures  # still a full answer, by rules
    assert "model_unavailable" in [json.loads(l)["action"] for l in open(res.log_file)]


def test_scan_reports_recalls_skipped_when_the_time_budget_is_used_up(tmp_path, monkeypatch):
    from app.adapters.factory import get_adapter

    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("DECISIONS_FILE", str(tmp_path / "none.jsonl"))
    monkeypatch.setattr("app.orchestrator.SCAN_BUDGET_S", -1)
    monkeypatch.setattr("app.orchestrator.SCAN_LIMIT", 3)
    res = run(RunRequest(run_id="scanb", input=RunInput(mode="daily_scan"), options=RunOptions(sample_mode=True)),
              get_adapter(sample_mode=True, data_dir="data/sample"), str(tmp_path / "state"))
    assert res.output.exposures == [] and len(res.output.unresolved_conflicts) == 3
    assert all("skipped" in c["error"] for c in res.output.unresolved_conflicts)
