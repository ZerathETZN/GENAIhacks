from app.meterless.world_model import IngestPipelineService, WorldStoreService
from app.schemas import Evidence


def test_every_evidence_item_resolves_to_a_world_model_record():
    store = WorldStoreService()
    IngestPipelineService(store).ingest(
        "r1", "pos.sales",
        [{"type": "SaleRecord", "source": "pos", "record_id": "S-1", "attrs": {"batch": "nsc-1"}}],
        "RetrieverAgent",
    )
    evidence = [Evidence(source="pos", record_id="S-1", field="batch", value="nsc-1")]
    for ev in evidence:
        found = store.resolve(ev.source, ev.record_id)
        assert found and found[0]["attrs"][ev.field] == ev.value


def test_fabricated_evidence_does_not_resolve():
    ev = Evidence(source="inventory", record_id="MISSING", field="batch", value="x")
    assert WorldStoreService().resolve(ev.source, ev.record_id) == []


def test_evidence_of_a_real_orchestrator_run_resolves_in_its_world_model(tmp_path, monkeypatch):
    import json

    from app.adapters.factory import get_adapter
    from app.orchestrator import run
    from app.schemas import Recall, RunInput, RunOptions, RunRequest

    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("DECISIONS_FILE", str(tmp_path / "none.jsonl"))
    r = json.load(open("data/sample/recalls_used.json", encoding="utf-8"))[3]
    recall = Recall(**{k: r[k] for k in ("product_name", "reg_no", "batches", "date", "degree_level")})
    res = run(RunRequest(run_id="prov1", input=RunInput(mode="recall_alert", recall=recall), options=RunOptions(sample_mode=True)),
              get_adapter(sample_mode=True, data_dir="data/sample"), str(tmp_path / "state"))
    world = WorldStoreService(str(tmp_path / "state" / "world-prov1.db"))
    evidence = [ev for e in res.output.exposures for ev in e.evidence]
    assert evidence
    for ev in evidence:
        found = world.resolve(ev.source, ev.record_id)
        assert found and found[0]["attrs"][ev.field] == ev.value
