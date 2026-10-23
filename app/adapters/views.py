"""Single definition of recallguard.product_exposure_v (AGENTS.md §7.4), rendered for
DuckDB (sample mode) and for Zetaris Lightning (Spark SQL), so the two never drift."""

from __future__ import annotations

from typing import Literal

Dialect = Literal["duckdb", "spark"]

VIEW_NAME = "recallguard.product_exposure_v"


def _norm(col: str, dialect: Dialect) -> str:
    # DuckDB replaces only the first match unless given 'g'; Spark always replaces all.
    flag = ", 'g'" if dialect == "duckdb" else ""
    return f"regexp_replace(upper({col}), '[^A-Z0-9]', ''{flag})"


def product_exposure_select(dialect: Dialect) -> str:
    """The SELECT body. Supplier values come from a REST table in Zetaris, where every
    column is a string, so qty and dates are cast explicitly in both dialects."""
    n = lambda c: _norm(c, dialect)  # noqa: E731
    return f"""
SELECT 'inventory' AS source, stock_id AS record_id, outlet_id, product_name, reg_no, batch,
       {n('reg_no')} AS reg_no_norm, {n('batch')} AS batch_norm,
       CAST(qty_on_hand AS INT) AS qty, 'stock' AS event_type, CAST(snapshot_date AS DATE) AS event_date,
       CAST(NULL AS STRING) AS customer_id
FROM inventory_pg.stock
UNION ALL
SELECT 'inventory', concat(transfer_id, ':', leg), outlet_id, product_name, reg_no, batch,
       {n('reg_no')}, {n('batch')},
       CASE WHEN leg = 'out' THEN -CAST(qty AS INT) ELSE CAST(qty AS INT) END, 'transfer',
       CAST(transfer_date AS DATE), CAST(NULL AS STRING)
FROM inventory_pg.transfers
UNION ALL
SELECT 'pos', sale_id, outlet_id, product_name, CAST(NULL AS STRING), batch,
       CAST(NULL AS STRING), {n('batch')},
       CAST(qty AS INT), 'sale', CAST(sold_at AS DATE), loyalty_id
FROM pos_pg.sales
UNION ALL
SELECT 'supplier', delivery_id, outlet_id, supplier_product_name, reg_no, batch,
       {n('reg_no')}, {n('batch')},
       CAST(qty AS INT), 'delivery', CAST(delivered_on AS DATE), CAST(NULL AS STRING)
FROM supplier_rest.deliveries
""".replace("STRING", "VARCHAR" if dialect == "duckdb" else "STRING")
