import pytest

from app.meterless.world_model import ContextBuilderService, IngestPipelineService, WorldStoreService


def _records(n=5):
    return [
        {"type": "StockRecord", "source": "inventory", "record_id": f"INV-{i}", "attrs": {"batch": f"nsc-{i}", "qty": i}}
        for i in range(n)
    ]


def test_reingest_creates_no_duplicates():
    store = WorldStoreService()
    ing = IngestPipelineService(store, batch_size=2)
    first = ing.ingest("r1", "inventory.stock", _records(), "RetrieverAgent")
    assert first["created"] == 5 and store.count() == 5

    # same run again: fully checkpointed, nothing written
    assert ing.ingest("r1", "inventory.stock", _records(), "RetrieverAgent")["skipped"] == 5
    # a new run over the same records: upsert sees identical content
    again = ing.ingest("r2", "inventory.stock", _records(), "RetrieverAgent")
    assert again["unchanged"] == 5 and again["created"] == 0
    assert store.count() == 5


def test_changed_record_updates_in_place():
    store = WorldStoreService()
    ing = IngestPipelineService(store)
    ing.ingest("r1", "s", _records(1), "A")
    changed = _records(1)
    changed[0]["attrs"]["qty"] = 99
    assert ing.ingest("r2", "s", changed, "A")["updated"] == 1
    assert store.count() == 1 and store.list()[0]["attrs"]["qty"] == 99


def test_interrupted_ingest_resumes_cleanly(tmp_path):
    path = str(tmp_path / "world.db")

    def dying():
        for i, rec in enumerate(_records()):
            if i == 3:
                raise ConnectionError("source dropped")
            yield rec

    ing = IngestPipelineService(WorldStoreService(path), batch_size=2)
    with pytest.raises(ConnectionError):
        ing.ingest("r1", "inventory.stock", dying(), "RetrieverAgent")

    # fresh process: only the first full batch (2 records) was committed
    store = WorldStoreService(path)
    assert store.count() == 2
    resumed = IngestPipelineService(store, batch_size=2).ingest("r1", "inventory.stock", _records(), "RetrieverAgent")
    assert resumed["skipped"] == 2 and resumed["created"] == 3
    assert store.count() == 5


def test_unknown_entity_type_rejected():
    ing = IngestPipelineService(WorldStoreService())
    with pytest.raises(ValueError):
        ing.ingest("r", "s", [{"type": "Nope", "source": "pos", "record_id": "1", "attrs": {}}], "A")


def test_context_builder_matches_normalised_and_keeps_provenance():
    store = WorldStoreService()
    IngestPipelineService(store).ingest("r1", "s", _records(), "RetrieverAgent")
    ctx = ContextBuilderService(store).build("find batch", types=["StockRecord"], match={"batch": "NSC 3"})
    assert [e["attrs"]["qty"] for e in ctx["entities"]] == [3]
    assert ctx["entities"][0]["provenance"] == {
        "source": "inventory", "record_id": "INV-3", "run_id": "r1", "agent_id": "RetrieverAgent",
    }
