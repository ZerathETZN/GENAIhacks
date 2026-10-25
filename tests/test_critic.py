import duckdb

from app.adapters import DataAdapter
from app.agents.critic import ConflictCriticAgent
from app.meterless.hmem import MemoryRetrievalService, MemoryStoreService
from app.reconcile.aggregate import ExposureDraft
from app.schemas import Recall

RECALL = Recall(product_name="Paracetamol 500mg Tablet", reg_no="MAL12345678A", batches=["NSC24067"], date="2026-10-01")


class RawAdapter(DataAdapter):
    """DuckDB tables shaped like A's raw-table contract (all strings, like Zetaris REST)."""
    name = "duckdb"

    def __init__(self):
        self.db = duckdb.connect()
        for schema in ("inventory_pg", "pos_pg"):
            self.db.execute(f"CREATE SCHEMA {schema}")
        self.db.execute("CREATE TABLE inventory_pg.stock (stock_id VARCHAR, outlet_id VARCHAR, product_name VARCHAR, reg_no VARCHAR, batch VARCHAR, qty_on_hand VARCHAR, snapshot_date VARCHAR)")
        self.db.execute("CREATE TABLE inventory_pg.transfers (transfer_id VARCHAR, leg VARCHAR, outlet_id VARCHAR, counterparty_outlet_id VARCHAR, product_name VARCHAR, reg_no VARCHAR, batch VARCHAR, qty VARCHAR, transfer_date VARCHAR)")
        self.db.execute("CREATE TABLE pos_pg.sales (sale_id VARCHAR, outlet_id VARCHAR, sku VARCHAR, product_name VARCHAR, batch VARCHAR, qty VARCHAR, sold_at VARCHAR, loyalty_id VARCHAR)")
        self.db.execute("INSERT INTO inventory_pg.stock VALUES ('s1','OUT-01','Paracetamol 500mg Tablet','MAL-12345678A','NSC-24067','12','2026-09-30')")
        self.db.execute("INSERT INTO pos_pg.sales VALUES ('p1','OUT-01','K1','PARACETAMOL TAB','nsc24067','2','2026-10-03 10:00:00','c1'),"
                        "('p2','OUT-01','K1','PARACETAMOL TAB','nsc24067','4','2026-10-05 10:00:00','c1'),"
                        "('p3','OUT-01','K1','PARACETAMOL TAB','nsc24067','9','2026-09-20 10:00:00','c9')")

    def query(self, sql, params=None, limit=1000):
        cur = self.db.execute(sql, params or [])
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchmany(limit)]


def draft(**kw):
    base = dict(outlet_id="OUT-01", product_name="PARACETAMOL TAB", reg_no="MAL12345678A", batch="NSC24067",
                on_hand_qty=12, sold_after_date_qty=6, distinct_customers=1, status="confirmed", confidence=0.9, names=["PARACETAMOL TAB"])
    return ExposureDraft(**{**base, **kw})


def test_matching_numbers_pass_and_teach_hmem_the_verified_spelling():
    hmem = MemoryStoreService()
    d = ConflictCriticAgent(RawAdapter(), hmem, "r1").review(RECALL, [draft()])[0]
    assert d.critic_check.passed and d.status == "confirmed"
    assert MemoryRetrievalService(hmem).same("product_name", "PARACETAMOL TAB", RECALL.product_name)


def test_mismatch_adopts_raw_numbers_and_needs_review_and_learns_nothing():
    hmem = MemoryStoreService()
    d = ConflictCriticAgent(RawAdapter(), hmem, "r1").review(RECALL, [draft(on_hand_qty=99)])[0]
    assert (d.critic_check.passed, d.on_hand_qty, d.status) == (False, 12, "needs_review")
    assert MemoryRetrievalService(hmem).same("product_name", "PARACETAMOL TAB", RECALL.product_name) is None


def test_transfer_with_a_missing_leg_needs_review():
    a = RawAdapter()
    a.db.execute("INSERT INTO inventory_pg.transfers VALUES ('t1','out','OUT-01','OUT-02','Paracetamol 500mg Tablet','MAL12345678A','NSC24067','5','2026-09-10')")
    d = ConflictCriticAgent(a, MemoryStoreService(), "r1").review(RECALL, [draft()])[0]
    assert d.status == "needs_review" and "missing leg" in d.reasons[-1]


def test_unassigned_draft_is_passed_through_untouched():
    d = draft(outlet_id="UNASSIGNED", status="needs_review")
    assert ConflictCriticAgent(RawAdapter(), MemoryStoreService(), "r1").review(RECALL, [d])[0].critic_check is None


def test_batch_with_slash_matches_raw_rows_after_norm():
    a = RawAdapter()
    a.db.execute("INSERT INTO inventory_pg.stock VALUES ('s9','OUT-09','Paracetamol 500mg Tablet','MAL12345678A','BN2404/23','5','2026-09-30')")
    d = draft(outlet_id="OUT-09", batch="BN2404-23", on_hand_qty=5, sold_after_date_qty=0, distinct_customers=0)
    assert ConflictCriticAgent(a, MemoryStoreService(), "r1").review(RECALL, [d])[0].critic_check.passed


def test_rejections_are_visible_in_the_trace():
    events = []
    ConflictCriticAgent(RawAdapter(), MemoryStoreService(), "r1", events.append).review(RECALL, [draft(), draft(on_hand_qty=99)])
    assert [e.status for e in events] == ["ok", "needs_revision"]
