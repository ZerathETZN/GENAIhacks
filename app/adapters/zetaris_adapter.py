"""Live data layer: Zetaris Lightning over REST (AGENTS.md §5.1).

POST {ZETARIS_REST_URL}/sql-editor/sqls/run with a fresh UUID4 per queryId and
X-Request-ID. The response is {"headers": [...], "data": [[...]]} with every value
as a string, so rows are zipped with headers and numbers are cast here.
"""

from __future__ import annotations

import math
import os
import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.adapters.data_adapter import AdapterError, Catalogue, CatalogueTable, DataAdapter, Params, Row, normalise_type

TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# Only these result columns are cast to numbers. Everything else stays text, because
# casting by value would turn batch "06387206" into 6387206.
NUMERIC_COLUMNS = {"qty", "qty_on_hand", "n", "c", "count", "total", "on_hand_qty",
                   "sold_after_date_qty", "distinct_customers", "units", "customers"}
_NUMERIC_SUFFIXES = ("_qty", "_count", "_total")


# ---------- parameter substitution (REST has no bind parameters) ----------


def render_literal(v: Any) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, (float, Decimal)):
        if not math.isfinite(v):
            raise AdapterError(f"non-finite number not allowed: {v!r}", recoverable=False)
        return repr(float(v)) if isinstance(v, float) else str(v)
    if isinstance(v, datetime):
        return f"TIMESTAMP '{v.isoformat(sep=' ')}'"
    if isinstance(v, date):
        return f"DATE '{v.isoformat()}'"
    if isinstance(v, str):
        # Spark SQL treats backslash as an escape inside literals, so escape it first.
        return "'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'"
    raise AdapterError(f"unsupported parameter type {type(v).__name__}", recoverable=False)


def bind(sql: str, params: Params) -> str:
    """Replace each `?` outside string literals with a safely rendered literal."""
    values = list(params or [])
    if isinstance(params, dict):
        raise AdapterError("named parameters are not supported; use positional ?", recoverable=False)
    out, i, in_str = [], 0, False
    for ch in sql:
        if ch == "'":
            in_str = not in_str
            out.append(ch)
        elif ch == "?" and not in_str:
            if i >= len(values):
                raise AdapterError(f"SQL has more ? than the {len(values)} params given", recoverable=False)
            out.append(render_literal(values[i]))
            i += 1
        else:
            out.append(ch)
    if i != len(values):
        raise AdapterError(f"SQL has {i} ? but {len(values)} params were given", recoverable=False)
    return "".join(out)


# ---------- value casting ----------


def cast_value(column: str, v: Any) -> Any:
    if v is None or (isinstance(v, str) and v.lower() == "null"):
        return None
    col = column.lower()
    if isinstance(v, str) and (col in NUMERIC_COLUMNS or col.endswith(_NUMERIC_SUFFIXES)):
        try:
            f = float(v)  # handles exponent format such as "1.2E1"
        except ValueError:
            return v
        return int(f) if f.is_integer() else f
    return v


class ZetarisAdapter(DataAdapter):
    name = "zetaris"

    def __init__(self, base_url: str | None = None, api_key: str | None = None, org_id: str | None = None,
                 client: httpx.Client | None = None) -> None:
        self.base_url = (base_url or os.getenv("ZETARIS_REST_URL", "")).rstrip("/")
        self.api_key = api_key or os.getenv("ZETARIS_API_KEY", "")
        self.org_id = org_id or os.getenv("ZETARIS_ORG_ID", "")
        if not (self.base_url and self.api_key and self.org_id):
            raise AdapterError("ZETARIS_REST_URL, ZETARIS_API_KEY and ZETARIS_ORG_ID must be set")
        self.client = client or httpx.Client(timeout=TIMEOUT)

    def query(self, sql: str, params: Params = None, limit: int = 1000) -> list[Row]:
        body_sql = bind(sql, params)
        last: Exception | None = None
        for _attempt in range(2):  # one retry on 5xx / transport errors
            req_id = str(uuid.uuid4())
            try:
                r = self.client.post(
                    f"{self.base_url}/sql-editor/sqls/run",
                    headers={"Authorization": f"Bearer {self.api_key}", "X-Org-ID": str(self.org_id),
                             "X-Request-ID": req_id, "Content-Type": "application/json"},
                    json={"queryId": str(uuid.uuid4()), "sql": body_sql, "source": "SqlEditor", "limit": limit},
                )
            except httpx.TransportError as e:
                last = AdapterError(f"zetaris unreachable: {type(e).__name__}")
                continue
            if r.status_code >= 500:
                last = AdapterError(f"zetaris http {r.status_code}")
                continue
            if r.status_code == 401:
                raise AdapterError("zetaris 401: API key rejected (Management -> API Tokens)")
            if r.status_code >= 400:
                raise AdapterError(f"zetaris http {r.status_code}: {r.text[:200]}", recoverable=False)
            data = r.json()
            headers = data.get("headers") or []
            return [{h: cast_value(h, v) for h, v in zip(headers, row)} for row in (data.get("data") or [])[:limit]]
        raise last or AdapterError("zetaris query failed")

    def __repr__(self) -> str:  # never print the key
        return f"ZetarisAdapter(base_url={self.base_url!r}, org_id={self.org_id!r}, api_key=***)"

    # Zetaris ships these sample databases; listing them is real discovery, describing
    # their ~30 tables on every run is not worth the time.
    SAMPLE_DATABASES = {"ny_taxi", "tpcds_db"}
    CONTAINERS = ("recallguard",)
    MAX_TABLES = 40  # bounded run (Rule 8)

    def catalogue(self) -> Catalogue:
        statements: list[str] = []

        def run(sql: str) -> list[Row]:
            statements.append(sql)
            return self.query(sql, limit=500)

        sources: list[tuple[str, str]] = [(r["name"], "datasource") for r in run("SHOW DATASOURCES")]
        sources += [(r["name"], "lightning_db") for r in run("SHOW LIGHTNING DATABASES")]
        sources += [(c, "view") for c in self.CONTAINERS]
        skipped = [{"source": s, "reason": "Zetaris built-in sample dataset"} for s, _ in sources
                   if s.lower() in self.SAMPLE_DATABASES]
        tables: list[CatalogueTable] = []
        for source, kind in sources:
            if source.lower() in self.SAMPLE_DATABASES:
                continue
            for r in run(f"SHOW TABLES IN {source}"):
                if len(tables) >= self.MAX_TABLES:
                    skipped.append({"source": source, "reason": f"table cap {self.MAX_TABLES} reached"})
                    break
                # SHOW TABLES returns e.g. "INVENTORY_PG.stock" or "PRODUCT_EXPOSURE_V"
                name = r["table_identifier"].rsplit(".", 1)[-1].lower()
                qualified = f"{source.lower()}.{name}"
                cols = [{"name": c["col_name"], "type": normalise_type(c["data_type"])}
                        for c in run(f"DESCRIBE {qualified}") if c.get("col_name") and not c["col_name"].startswith("#")]
                tables.append({"source": source.lower(), "kind": kind, "table": qualified, "columns": cols})
        return {"adapter": self.name, "statements": statements, "tables": tables, "skipped": skipped}
