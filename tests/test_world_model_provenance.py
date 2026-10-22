from app.meterless.world_model import IngestPipelineService, WorldStoreService
from app.schemas import Evidence


def test_every_evidence_item_resolves_to_a_world_model_record():
    store = WorldStoreService()
    IngestPipelineService(store).ingest(
        "r1", "pos.sales",
        [{"type": "SaleRecord", "source": "pos", "record_id": "S-1", "attrs": {"batch": "nsc-1"}}],
        "RetrieverAgent",
    )
    # TODO(B): replace with evidence[] from a real orchestrator run once agents exist.
    evidence = [Evidence(source="pos", record_id="S-1", field="batch", value="nsc-1")]
    for ev in evidence:
        found = store.resolve(ev.source, ev.record_id)
        assert found and found[0]["attrs"][ev.field] == ev.value


def test_fabricated_evidence_does_not_resolve():
    ev = Evidence(source="inventory", record_id="MISSING", field="batch", value="x")
    assert WorldStoreService().resolve(ev.source, ev.record_id) == []
