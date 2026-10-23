import json

import duckdb

from app.adapters import DataAdapter
from app.agents.retriever import COLUMNS, RetrieverAgent
from app.meterless.world_model import IngestPipelineService, WorldStoreService
from app.schemas import Recall, TraceEvent
from app.tracing import Tracer

RECALL = Recall(product_name="Paracetamol 500mg Tablet", reg_no="MAL12345678A", batches=["NSC-24067"], date="2026-10-01")

ROWS = [
    ("inventory", "INV-1", "OUT-01", "Paracetamol 500mg Tablet", "MAL12345678A", "NSC24067", 12, "stock", "2026-09-01", None),
    ("pos", "POS-1", "OUT-01", "PARACETAMOL TAB", None, "nsc-24067", 2, "sale", "2026-10-03", "c1"),
    ("supplier", "DEL-1", "OUT-02", "Paracetamol 500mg Tablet", "MAL-1234 5678A", "NSC-24067", 50, "delivery", "2026-08-20", None),
    ("inventory", "INV-9", "OUT-01", "Vitamin C", "MAL99999999Z", "VC1", 5, "stock", "2026-09-01", None),
]


class DuckAdapter(DataAdapter):
    name = "duckdb"

    def __init__(self):
        self.db = duckdb.connect()
        self.db.execute("CREATE SCHEMA recallguard")
        cols = ", ".join(f"{c} VARCHAR" for c in COLUMNS)
        self.db.execute(f"CREATE TABLE recallguard.product_exposure_v ({cols})")
        self.db.executemany(f"INSERT INTO recallguard.product_exposure_v VALUES ({', '.join('?' * len(COLUMNS))})", [[str(v) if v is not None else None for v in r] for r in ROWS])

    def query(self, sql, params=None, limit=1000):
        cur = self.db.execute(sql, params or [])
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchmany(limit)]


def test_retrieves_product_rows_by_reg_no_or_name_and_ingests_with_provenance(tmp_path):
    store = WorldStoreService()
    events = []
    rows = RetrieverAgent(DuckAdapter(), IngestPipelineService(store), "r1", events.append).retrieve(RECALL)

    assert {r["record_id"] for r in rows} == {"INV-1", "POS-1", "DEL-1"}  # unrelated INV-9 left out
    assert store.resolve("pos", "POS-1")[0]["type"] == "SaleRecord"
    assert store.resolve("supplier", "DEL-1")[0]["type"] == "Delivery"
    assert store.resolve("regulator", "MAL12345678A:2026-10-01")[0]["type"] == "RegulatorNotice"
    assert [e.sponsor_call for e in events] == [None, "meterless.world_model"]  # duckdb, not zetaris


def test_recall_input_is_parameterised_not_inlined():
    hostile = RECALL.model_copy(update={"reg_no": "x' OR '1'='1", "product_name": "zq'); DROP--"})
    assert RetrieverAgent(DuckAdapter(), IngestPipelineService(WorldStoreService()), "r1").retrieve(hostile) == []


def test_tracer_writes_valid_jsonl_replaces_old_run_and_redacts(tmp_path, monkeypatch):
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "supersecrettoken123")
    t = Tracer("r1", str(tmp_path))
    t.emit(TraceEvent(run_id="r1", agent_name="A", action="x", output_summary="token supersecrettoken123 used"))
    lines = t.path.read_text().splitlines()
    assert len(lines) == 1 and "supersecrettoken123" not in lines[0]
    assert TraceEvent.model_validate(json.loads(lines[0])).output_summary == "token *** used"
    Tracer("r1", str(tmp_path))
    assert t.path.read_text() == ""
