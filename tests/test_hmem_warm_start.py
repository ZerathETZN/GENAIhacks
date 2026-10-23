"""Proof that H-MEM changes behaviour: a spelling verified in run 1 resolves a doubtful row in run 2.

OUT-02 has stock under the odd name "Panadol Paracetamol" WITH the reg_no, so run 1 confirms it by
reg_no and the Critic verifies it against the raw tables, which teaches H-MEM the spelling.
OUT-03's POS rows use the same spelling with no reg_no: name similarity alone (0.73) is too weak,
so run 1 sends it to review; run 2 trusts the verified alias.
"""

from app.orchestrator import run
from tests.test_orchestrator import FullAdapter, req


class WarmAdapter(FullAdapter):
    def __init__(self):
        super().__init__()
        self.db.execute("INSERT INTO inventory_pg.stock VALUES ('s2','OUT-02','Panadol Paracetamol','MAL12345678A','NSC24067','8','2026-09-30')")
        self.db.execute("INSERT INTO pos_pg.sales VALUES ('p9','OUT-03','K2','Panadol Paracetamol','nsc24067','3','2026-10-04 09:00:00','c7')")
        self.db.execute("INSERT INTO recallguard.product_exposure_v VALUES "
                        "('inventory','s2','OUT-02','Panadol Paracetamol','MAL12345678A','NSC24067','8','stock','2026-09-30',NULL),"
                        "('pos','p9','OUT-03','Panadol Paracetamol',NULL,'nsc24067','3','sale','2026-10-04','c7')")


def test_warm_run_has_fewer_needs_review_than_cold(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    state = str(tmp_path / "state")
    cold = run(req(), WarmAdapter(), state).output
    warm = run(req(), WarmAdapter(), state).output
    review = lambda o: [e.outlet_id for e in o.exposures if e.status == "needs_review"]
    assert review(cold) == ["OUT-03"] and review(warm) == []
