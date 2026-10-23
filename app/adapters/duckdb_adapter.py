"""SAMPLE_MODE twin of the Zetaris layer (AGENTS.md §5.1, §7.4).

Exposes the same logical names agents use against Zetaris, over local files:
  inventory_pg.stock, inventory_pg.transfers, pos_pg.sales, supplier_rest.deliveries,
  regulator_pg.<5 real tables>, recallguard.product_exposure_v
No network, no credentials. Never reads data/ground_truth/.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from app.adapters.data_adapter import AdapterError, Catalogue, CatalogueTable, DataAdapter, Params, Row, normalise_type
from app.adapters.views import VIEW_NAME, product_exposure_select

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = ROOT / "data" / "sample"
REGULATOR_DIR = ROOT / "data" / "sample" / "regulator"

# Explicit types: auto-detection would turn batch "06387206" into the integer 6387206.
_STOCK = {"stock_id": "VARCHAR", "outlet_id": "VARCHAR", "product_name": "VARCHAR", "reg_no": "VARCHAR",
          "batch": "VARCHAR", "qty_on_hand": "INTEGER", "snapshot_date": "DATE"}
_TRANSFERS = {"transfer_id": "VARCHAR", "leg": "VARCHAR", "outlet_id": "VARCHAR", "counterparty_outlet_id": "VARCHAR",
              "product_name": "VARCHAR", "reg_no": "VARCHAR", "batch": "VARCHAR", "qty": "INTEGER", "transfer_date": "DATE"}
_SALES = {"sale_id": "VARCHAR", "outlet_id": "VARCHAR", "sku": "VARCHAR", "product_name": "VARCHAR",
          "batch": "VARCHAR", "qty": "INTEGER", "sold_at": "TIMESTAMP", "loyalty_id": "VARCHAR"}
_DELIVERIES = {"delivery_id": "VARCHAR", "supplier_name": "VARCHAR", "supplier_licence_no": "VARCHAR",
               "outlet_id": "VARCHAR", "supplier_product_name": "VARCHAR", "reg_no": "VARCHAR",
               "batch": "VARCHAR", "qty": "INTEGER", "delivered_on": "DATE"}
_RECALLS = {"recall_id": "VARCHAR", "recall_date": "DATE", "product_name": "VARCHAR", "reg_no": "VARCHAR",
            "batches": "VARCHAR", "all_batches": "BOOLEAN", "batch_raw": "VARCHAR", "degree": "VARCHAR",
            "voluntary": "BOOLEAN", "level": "VARCHAR", "degree_level_raw": "VARCHAR", "reason": "VARCHAR",
            "holder": "VARCHAR", "active_ingredients": "VARCHAR", "date_raw": "VARCHAR"}

_REGULATOR_PARQUET = ["pharmaceutical_products_cancelled", "pharmaceutical_products",
                      "pharmaceutical_importers", "pharmaceutical_wholesalers"]

# §7.4 view, shared with the Zetaris registration so both define it identically.
PRODUCT_EXPOSURE_V = f"CREATE VIEW {VIEW_NAME} AS {product_exposure_select('duckdb')}"


def _csv(path: Path, cols: dict[str, str]) -> str:
    spec = "{" + ", ".join(f"'{k}': '{v}'" for k, v in cols.items()) + "}"
    return f"read_csv('{path.as_posix()}', header=true, columns={spec}, nullstr='')"


def _plain(v: Any) -> Any:
    """Same Python types the Zetaris adapter returns: int/float/str/bool/None."""
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


class DuckDBAdapter(DataAdapter):
    name = "duckdb"

    def __init__(self, data_dir: str | Path | None = None, regulator_dir: str | Path | None = None) -> None:
        self.data_dir = Path(data_dir or os.getenv("RG_DATA_DIR") or DEFAULT_DATA_DIR)
        if not self.data_dir.is_absolute():
            self.data_dir = ROOT / self.data_dir
        self.regulator_dir = Path(regulator_dir or REGULATOR_DIR)
        if "ground_truth" in self.data_dir.parts:
            raise AdapterError("agents must never read data/ground_truth", recoverable=False)
        self.con = duckdb.connect(":memory:")
        self._register()

    def _register(self) -> None:
        d, r, c = self.data_dir, self.regulator_dir, self.con
        for schema in ("inventory_pg", "pos_pg", "supplier_rest", "regulator_pg", "recallguard"):
            c.execute(f"CREATE SCHEMA {schema}")
        try:
            c.execute(f"CREATE VIEW inventory_pg.stock AS SELECT * FROM {_csv(d / 'inventory' / 'stock.csv', _STOCK)}")
            c.execute(f"CREATE VIEW inventory_pg.transfers AS SELECT * FROM {_csv(d / 'inventory' / 'transfers.csv', _TRANSFERS)}")
            c.execute(f"CREATE VIEW pos_pg.sales AS SELECT * FROM {_csv(d / 'pos' / 'sales.csv', _SALES)}")
            spec = "{" + ", ".join(f"'{k}': '{v}'" for k, v in _DELIVERIES.items()) + "}"
            c.execute(f"CREATE VIEW supplier_rest.deliveries AS SELECT * FROM "
                      f"read_json('{(d / 'supplier' / 'deliveries.json').as_posix()}', format='array', columns={spec})")
            c.execute(f"CREATE VIEW regulator_pg.npra_recalls AS SELECT * FROM {_csv(r / 'npra_recalls.csv', _RECALLS)}")
            for t in _REGULATOR_PARQUET:
                c.execute(f"CREATE VIEW regulator_pg.{t} AS SELECT * FROM read_parquet('{(r / f'{t}.parquet').as_posix()}')")
            c.execute(PRODUCT_EXPOSURE_V)
            c.execute("SELECT count(*) FROM recallguard.product_exposure_v").fetchall()  # fail now, not mid-run
        except duckdb.Error as e:
            raise AdapterError(
                f"sample data missing or malformed in {self.data_dir}: {e}. "
                "Run scripts/generate_synthetic.py", recoverable=False,
            ) from e

    def query(self, sql: str, params: Params = None, limit: int = 1000) -> list[Row]:
        try:
            cur = self.con.execute(sql, list(params) if params is not None and not isinstance(params, dict) else params)
            cols = [d[0] for d in cur.description]
            return [{k: _plain(v) for k, v in zip(cols, row)} for row in cur.fetchmany(limit)]
        except duckdb.Error as e:
            raise AdapterError(f"duckdb: {e}", recoverable=False) from e

    # Which DuckDB schema stands in for which kind of Zetaris source.
    _KINDS = {"inventory_pg": "datasource", "pos_pg": "datasource", "regulator_pg": "datasource",
              "supplier_rest": "lightning_db", "recallguard": "view"}

    def catalogue(self) -> Catalogue:
        sql = ("SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns "
               "WHERE table_schema IN ({}) ORDER BY table_schema, table_name, ordinal_position").format(
            ", ".join(f"'{s}'" for s in self._KINDS))
        tables: dict[str, CatalogueTable] = {}
        for schema, table, col, typ in self.con.execute(sql).fetchall():
            key = f"{schema}.{table}".lower()
            t = tables.setdefault(key, {"source": schema, "kind": self._KINDS[schema], "table": key, "columns": []})
            t["columns"].append({"name": col, "type": normalise_type(typ)})
        return {"adapter": self.name, "statements": [sql], "tables": list(tables.values()), "skipped": []}
