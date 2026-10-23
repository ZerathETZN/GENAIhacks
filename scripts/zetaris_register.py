"""Register RecallGuard's sources in the local Zetaris (AGENTS.md §5.1). Idempotent.

  python scripts/zetaris_register.py --dry-run   # print the SQL (passwords masked), send nothing
  python scripts/zetaris_register.py             # register, refresh, create the view, verify

Steps
  1. CREATE DATASOURCE inventory_pg | pos_pg | regulator_pg  (JDBC to the rg-* containers)
  2. REGISTER DATASOURCE TABLES, then REFRESH (Zetaris caches column metadata)
  3. CREATE LIGHTNING DATABASE supplier_rest + REST table deliveries (rg-supplier-api)
  4. CREATE SCHEMASTORE CONTAINER recallguard + VIEW product_exposure_v (same SQL as DuckDB's)
  5. Verify: row count of every table the agents use, through Zetaris

Run order: docker compose up -d -> load_postgres.py -> this script.
Credentials come from .env only: ZETARIS_*, PG_READER_USER, PG_READER_PASSWORD.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from _env import load_env  # noqa: E402
from app.adapters.data_adapter import AdapterError  # noqa: E402
from app.adapters.views import VIEW_NAME, product_exposure_select  # noqa: E402

JDBC_SOURCES = {  # datasource -> (container, database)
    "inventory_pg": ("rg-inventory", "inventory"),
    "pos_pg": ("rg-pos", "pos"),
    "regulator_pg": ("rg-regulator", "regulator"),
}
SUPPLIER_DB, SUPPLIER_TABLE = "supplier_rest", "deliveries"
SUPPLIER_URL = "http://rg-supplier-api:8000/deliveries"
CONTAINER = "recallguard"

VERIFY_TABLES = [
    "inventory_pg.stock", "inventory_pg.transfers", "pos_pg.sales", "supplier_rest.deliveries",
    "regulator_pg.npra_recalls", "regulator_pg.pharmaceutical_products_cancelled", VIEW_NAME,
]


def q(s: str) -> str:
    """Double-quoted Lightning option value."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def statements(reader_user: str, reader_pw: str) -> list[tuple[str, str, bool]]:
    """(label, sql, ok_if_exists). All forms ran successfully on the hackathon build on 23 Oct;
    "exist" in an error (already exists / does not exist) counts as success where allowed."""
    out: list[tuple[str, str, bool]] = []
    for ds, (host, db) in JDBC_SOURCES.items():
        out.append((f"datasource {ds}",
                    f"CREATE DATASOURCE {ds} OPTIONS (jdbcdriver {q('org.postgresql.Driver')}, "
                    f"jdbcurl {q(f'jdbc:postgresql://{host}:5432/{db}')}, username {q(reader_user)}, "
                    f"password {q(reader_pw)}, fetchsize {q('1000')})", True))
        out.append((f"register tables {ds}", f"REGISTER DATASOURCE TABLES FROM {ds}", True))
        out.append((f"refresh {ds}", f"REFRESH DATASOURCE TABLES FROM {ds}", False))
    out.append((f"lightning db {SUPPLIER_DB}", f"CREATE LIGHTNING DATABASE {SUPPLIER_DB}", True))
    out.append((f"rest table {SUPPLIER_DB}.{SUPPLIER_TABLE}",
                f"CREATE LIGHTNING REST TABLE {SUPPLIER_TABLE} FROM {SUPPLIER_DB} "
                f"REQUEST(endpoint {q(SUPPLIER_URL)}, method {q('get')}, response_type {q('json')}, "
                f"http_encoding {q('URLENCODED')}) HEADER () BODY ()", True))
    out.append((f"container {CONTAINER}", f"CREATE SCHEMASTORE CONTAINER {CONTAINER}", True))
    # Schemastore-view fallback (AGENTS.md §5.1); USL is the preferred upgrade once this works.
    # Syntax verified on the hackathon build (23 Oct): create WITH CONTAINER, drop FROM, query as
    # recallguard.<view>. Re-creating an existing view fails, so drop first ("does not exist" is fine).
    view = VIEW_NAME.split(".", 1)[1]
    out.append((f"drop old view {VIEW_NAME}", f"DROP SCHEMASTORE VIEW {view} FROM {CONTAINER}", True))
    out.append((f"view {VIEW_NAME}",
                f"CREATE SCHEMASTORE VIEW {view} WITH CONTAINER {CONTAINER} AS "
                f"{' '.join(product_exposure_select('spark').split())}", False))
    return out


def masked(sql: str, secret: str) -> str:
    return sql.replace(secret, "****") if secret else sql


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    load_env()

    reader_user = os.getenv("PG_READER_USER", "zetaris_reader")
    reader_pw = os.getenv("PG_READER_PASSWORD", "")
    plan = statements(reader_user, reader_pw)

    if args.dry_run:
        for label, sql, _ in plan:
            print(f"-- {label}\n{masked(sql, reader_pw)};\n")
        return 0

    if not reader_pw:
        print("PG_READER_PASSWORD is not set (.env)", file=sys.stderr)
        return 1
    from app.adapters.zetaris_adapter import ZetarisAdapter

    try:
        z = ZetarisAdapter()
        z.query("SELECT 1 AS one")
    except AdapterError as e:
        hint = ""
        if "Not Allowed" in str(e):
            # Zetaris returns the same 400 for both causes; its API log says which.
            hint = ("\n  -> invalid/expired API key OR wrong ZETARIS_ORG_ID. `docker logs zetaris-api-1` says"
                    " 'Api token is not allowed' or 'Org id mismatch'.\n     Also check that no old ZETARIS_*"
                    " variable is set in this shell: it overrides .env.")
        elif "401" in str(e) or "not be set" in str(e) or "must be set" in str(e):
            hint = "\n  -> set ZETARIS_API_KEY in .env (Zetaris UI: Management -> API Tokens)"
        print(f"cannot use Zetaris: {e}{hint}", file=sys.stderr)
        return 1

    failed = 0
    for label, sql, ok_if_exists in plan:
        try:
            z.query(sql)
            print(f"  ok       {label}")
        except AdapterError as e:
            msg = str(e).lower()
            if ok_if_exists and ("exist" in msg or "duplicate" in msg):
                print(f"  exists   {label}")
            else:
                failed += 1
                print(f"  FAILED   {label}: {masked(str(e), reader_pw)[:300]}")

    print("\nverify through Zetaris:")
    for t in VERIFY_TABLES:
        try:
            n = z.query(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"]
            print(f"  {t}: {n} rows")
        except (AdapterError, IndexError, KeyError) as e:
            failed += 1
            print(f"  {t}: FAILED {masked(str(e), reader_pw)[:200]}")
    if failed:
        print(f"\n{failed} step(s) failed. Paste the FAILED lines to the team; the DDL syntax may "
              "differ on this Zetaris build (TODO(verify) in this script).", file=sys.stderr)
        return 1
    print("\nall sources registered and readable through Zetaris")
    return 0


if __name__ == "__main__":
    sys.exit(main())
