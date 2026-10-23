"""DuckDB adapter + generator agree with the §7.4 contract and with the answer key."""

import importlib.util
import json
from pathlib import Path

import pytest

from app.adapters import AdapterError
from app.adapters.duckdb_adapter import DuckDBAdapter

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("gen", ROOT / "scripts" / "generate_synthetic.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("seed42")
    assert gen.main(["--seed", "42", "--out", str(out), "--truth", str(out / "gt" / "exposures.json")]) == 0
    return out, json.loads((out / "gt" / "exposures.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def adapter(generated):
    return DuckDBAdapter(generated[0])


def test_generator_is_deterministic(generated, tmp_path):
    out, _ = generated
    gen.main(["--seed", "42", "--out", str(tmp_path), "--truth", str(tmp_path / "gt.json")])
    for f in ["inventory/stock.csv", "inventory/transfers.csv", "pos/sales.csv", "supplier/deliveries.json"]:
        assert (out / f).read_bytes() == (tmp_path / f).read_bytes(), f


def test_view_columns_match_contract(adapter):
    row = adapter.query("SELECT * FROM recallguard.product_exposure_v", limit=1)[0]
    assert list(row) == ["source", "record_id", "outlet_id", "product_name", "reg_no", "batch",
                         "reg_no_norm", "batch_norm", "qty", "event_type", "event_date", "customer_id"]


def test_raw_tables_for_critic(adapter):
    for table, cols in [
        ("inventory_pg.stock", {"outlet_id", "product_name", "reg_no", "batch", "qty_on_hand"}),
        ("inventory_pg.transfers", {"transfer_id", "leg", "outlet_id", "counterparty_outlet_id", "batch", "qty"}),
        ("pos_pg.sales", {"outlet_id", "product_name", "batch", "qty", "sold_at", "loyalty_id"}),
        ("supplier_rest.deliveries", {"delivery_id", "outlet_id", "batch", "qty", "supplier_licence_no"}),
        ("regulator_pg.npra_recalls", {"recall_id", "reg_no", "batches", "recall_date"}),
    ]:
        assert cols <= set(adapter.query(f"SELECT * FROM {table}", limit=1)[0]), table


def test_batches_stay_text(adapter):
    for r in adapter.query("SELECT batch FROM inventory_pg.stock"):
        assert isinstance(r["batch"], str)


def test_answer_key_matches_raw_tables(adapter, generated):
    """Each ground-truth exposure can be re-derived from the raw tables with plain SQL."""
    _, truth = generated
    recalls = {r["recall_id"]: r for r in adapter.query("SELECT recall_id, recall_date FROM regulator_pg.npra_recalls", limit=500)}
    bn = "regexp_replace(upper(batch), '[^A-Z0-9]', '', 'g')"
    for e in truth["exposures"]:
        if "batch_typo" in e["conflicts"]:
            continue  # the typo'd sale is deliberately not findable by exact batch
        stock = adapter.query(f"SELECT COALESCE(SUM(qty_on_hand), 0) AS n FROM inventory_pg.stock WHERE outlet_id = ? AND {bn} = ?",
                              [e["outlet_id"], e["batch_norm"]])[0]["n"]
        sold = adapter.query(f"SELECT COALESCE(SUM(qty), 0) AS n FROM pos_pg.sales WHERE outlet_id = ? AND {bn} = ? "
                             "AND CAST(sold_at AS DATE) >= CAST(? AS DATE)",
                             [e["outlet_id"], e["batch_norm"], recalls[e["recall_id"]]["recall_date"]])[0]["n"]
        assert (stock, sold) == (e["on_hand_qty"], e["sold_after_date_qty"]), e["recall_id"]


def test_ground_truth_dir_is_refused():
    with pytest.raises(AdapterError):
        DuckDBAdapter(ROOT / "data" / "ground_truth")
