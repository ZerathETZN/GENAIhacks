"""Zetaris adapter (no network: httpx is mocked) and adapter selection."""

import json
import uuid
from datetime import date

import httpx
import pytest

from app.adapters import AdapterError
from app.adapters.factory import FallbackAdapter, get_adapter
from app.adapters.zetaris_adapter import ZetarisAdapter, bind, cast_value


# ---------- bind ----------

def test_bind_escapes_quotes_and_backslashes():
    sql = bind("SELECT * FROM t WHERE a = ? AND b = ?", ["O'Brien", "x\\' OR 1=1 --"])
    assert sql == "SELECT * FROM t WHERE a = 'O\\'Brien' AND b = 'x\\\\\\' OR 1=1 --'"


def test_bind_types():
    assert bind("? ? ? ? ?", [3, 1.5, None, True, date(2026, 1, 30)]) == "3 1.5 NULL TRUE DATE '2026-01-30'"


def test_bind_ignores_question_marks_inside_literals():
    assert bind("SELECT '?' AS q WHERE x = ?", ["a"]) == "SELECT '?' AS q WHERE x = 'a'"


@pytest.mark.parametrize("sql, params", [("? ?", ["a"]), ("?", ["a", "b"]), ("?", [object()]), ("?", [float("nan")])])
def test_bind_rejects_bad_input(sql, params):
    with pytest.raises(AdapterError):
        bind(sql, params)


# ---------- cast ----------

def test_cast_keeps_batches_as_text_and_numbers_as_numbers():
    assert cast_value("batch", "06387206") == "06387206"
    assert cast_value("qty_on_hand", "1.2E1") == 12
    assert cast_value("n", "3") == 3
    assert cast_value("sold_after_date_qty", "2.5") == 2.5
    assert cast_value("loyalty_id", "null") is None


# ---------- REST call ----------

def _adapter(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ZetarisAdapter("http://z/api/v1.0", "secret-key", "1", client=client)


def test_query_zips_headers_and_sends_uuids():
    seen = {}

    def handler(req: httpx.Request):
        seen["req"] = req
        return httpx.Response(200, json={"headers": ["batch", "qty"], "data": [["0123", "4"]], "total": 1})

    rows = _adapter(handler).query("SELECT batch, qty FROM inventory_pg.stock WHERE outlet_id = ?", ["OUT-01"])
    assert rows == [{"batch": "0123", "qty": 4}]
    body = json.loads(seen["req"].content)
    uuid.UUID(body["queryId"]), uuid.UUID(seen["req"].headers["X-Request-ID"])
    assert body["sql"].endswith("outlet_id = 'OUT-01'")
    assert seen["req"].headers["Authorization"] == "Bearer secret-key"
    assert "secret-key" not in repr(_adapter(handler))


def test_retries_once_on_5xx_then_raises_recoverable():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503)

    with pytest.raises(AdapterError) as e:
        _adapter(handler).query("SELECT 1")
    assert len(calls) == 2 and e.value.recoverable


def test_400_is_not_recoverable():
    with pytest.raises(AdapterError) as e:
        _adapter(lambda r: httpx.Response(400, text="Not Allowed")).query("SELECT 1")
    assert not e.value.recoverable


# ---------- selection ----------

def test_sample_mode_gives_duckdb(monkeypatch):
    monkeypatch.setenv("SAMPLE_MODE", "true")
    a = get_adapter()
    assert (a.name, a.result_name) == ("duckdb", "duckdb")


def test_missing_zetaris_env_falls_back(monkeypatch):
    monkeypatch.delenv("SAMPLE_MODE", raising=False)
    for k in ("ZETARIS_REST_URL", "ZETARIS_API_KEY", "ZETARIS_ORG_ID"):
        monkeypatch.delenv(k, raising=False)
    a = get_adapter()
    assert a.result_name == "duckdb_fallback" and "ZETARIS_API_KEY" in a.fallback_reason


def test_runtime_failure_switches_to_duckdb():
    down = _adapter(lambda r: httpx.Response(502))
    a = FallbackAdapter(down)
    assert a.name == "zetaris"
    rows = a.query("SELECT count(*) AS n FROM pos_pg.sales")
    assert rows[0]["n"] > 0
    assert (a.name, a.result_name) == ("duckdb", "duckdb_fallback") and "502" in a.fallback_reason


def test_catalogue_from_show_and_describe_skips_sample_dbs():
    answers = {
        "SHOW DATASOURCES": (["name", "description", "id"], [["inventory_pg", "", "1"]]),
        "SHOW LIGHTNING DATABASES": (["name", "description", "id"], [["TPCDS_DB", "", "2"], ["supplier_rest", "", "3"]]),
        "SHOW TABLES IN inventory_pg": (["table_identifier", "catalog_name", "catalog_type"], [["INVENTORY_PG.stock", "INVENTORY_PG", "Data Source"]]),
        "SHOW TABLES IN supplier_rest": (["table_identifier", "catalog_name", "catalog_type"], [["supplier_rest.deliveries", "supplier_rest", "Lightning Database"]]),
        "SHOW TABLES IN recallguard": (["table_identifier", "catalog_name", "catalog_type"], [["PRODUCT_EXPOSURE_V", "recallguard", "Schema Store View"]]),
        "DESCRIBE inventory_pg.stock": (["col_name", "data_type", "comment"], [["batch", "string", None], ["qty_on_hand", "int", None]]),
        "DESCRIBE supplier_rest.deliveries": (["col_name", "data_type", "comment"], [["qty", "bigint", None]]),
        "DESCRIBE recallguard.product_exposure_v": (["col_name", "data_type", "comment"], [["batch_norm", "string", None]]),
    }

    def handler(req):
        h, d = answers[json.loads(req.content)["sql"]]
        return httpx.Response(200, json={"headers": h, "data": d})

    cat = _adapter(handler).catalogue()
    assert [t["table"] for t in cat["tables"]] == ["inventory_pg.stock", "supplier_rest.deliveries", "recallguard.product_exposure_v"]
    assert [t["kind"] for t in cat["tables"]] == ["datasource", "lightning_db", "view"]
    assert cat["tables"][0]["columns"] == [{"name": "batch", "type": "string"}, {"name": "qty_on_hand", "type": "int"}]
    assert cat["skipped"] == [{"source": "TPCDS_DB", "reason": "Zetaris built-in sample dataset"}]
    assert "SHOW DATASOURCES" in cat["statements"]


def test_catalogue_falls_back_to_duckdb():
    a = FallbackAdapter(_adapter(lambda r: httpx.Response(503)))
    cat = a.catalogue()
    assert cat["adapter"] == "duckdb" and a.result_name == "duckdb_fallback"
