"""Register RecallGuard's sources in the local Zetaris (AGENTS.md §5.1). Idempotent.

  python scripts/zetaris_register.py --dry-run   # print the SQL (passwords masked), send nothing
  python scripts/zetaris_register.py             # register, refresh, create the view, verify

Steps
  1. CREATE DATASOURCE inventory_pg | pos_pg | regulator_pg  (JDBC to the rg-* containers)
  2. REGISTER DATASOURCE TABLES, then REFRESH (Zetaris caches column metadata)
  3. CREATE LIGHTNING DATABASE supplier_rest + REST table deliveries (rg-supplier-api)
  4. Unified Semantic Layer: namespace lightning.metastore.recallguard, COMPILE USL recallguard_usl,
     ACTIVATE USL TABLE product_exposure AS <the four-source union>   (skip with --no-usl)
  5. CREATE SCHEMASTORE CONTAINER recallguard + VIEW product_exposure_v: a rename over the USL table,
     or the union itself if USL failed. Agents only ever see the view (same name and columns).
  6. Verify: row count of every table the agents use, through Zetaris

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
from app.adapters.views import (  # noqa: E402
    USL_DDL, USL_MODEL, USL_NAMESPACE, USL_TABLE, VIEW_NAME, product_exposure_select, usl_activation_select,
    view_over_usl_select,
)

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
    "regulator_pg.npra_recalls", "regulator_pg.pharmaceutical_products_cancelled", USL_TABLE, VIEW_NAME,
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
    return out


def usl_statements() -> list[tuple[str, str, bool]]:
    """Unified Semantic Layer: the governed model the view reads from (AGENTS.md §5.1)."""
    parent = USL_NAMESPACE.rsplit(".", 1)[0]
    return [
        (f"namespace {parent}", f"CREATE NAMESPACE IF NOT EXISTS {parent}", True),
        (f"namespace {USL_NAMESPACE}", f"CREATE NAMESPACE IF NOT EXISTS {USL_NAMESPACE}", True),
        (f"compile USL {USL_MODEL}", f"COMPILE USL IF NOT EXISTS {USL_MODEL} DEPLOY NAMESPACE {USL_NAMESPACE} DDL {USL_DDL}", True),
        (f"activate USL {USL_TABLE}", f"ACTIVATE USL TABLE {USL_TABLE} AS {usl_activation_select()}", False),
    ]


def view_statements(over_usl: bool) -> list[tuple[str, str, bool]]:
    view = VIEW_NAME.split(".", 1)[1]
    body = view_over_usl_select() if over_usl else " ".join(product_exposure_select("spark").split())
    return [
        (f"drop old view {VIEW_NAME}", f"DROP SCHEMASTORE VIEW {view} FROM {CONTAINER}", True),
        (f"view {VIEW_NAME} ({'over USL' if over_usl else 'direct'})",
         f"CREATE SCHEMASTORE VIEW {view} WITH CONTAINER {CONTAINER} AS {body}", False),
    ]


def masked(sql: str, secret: str) -> str:
    return sql.replace(secret, "****") if secret else sql


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-usl", action="store_true", help="skip the USL model; build the view directly on the sources")
    args = ap.parse_args(argv)
    load_env()

    reader_user = os.getenv("PG_READER_USER", "zetaris_reader")
    reader_pw = os.getenv("PG_READER_PASSWORD", "")
    plan = statements(reader_user, reader_pw)
    usl_plan = [] if args.no_usl else usl_statements()

    if args.dry_run:
        for label, sql, _ in plan + usl_plan + view_statements(over_usl=not args.no_usl):
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

    def run_steps(steps: list[tuple[str, str, bool]]) -> int:
        bad = 0
        for label, sql, ok_if_exists in steps:
            try:
                z.query(sql)
                print(f"  ok       {label}")
            except AdapterError as e:
                msg = str(e).lower()
                if ok_if_exists and ("exist" in msg or "duplicate" in msg):
                    print(f"  exists   {label}")
                else:
                    bad += 1
                    print(f"  FAILED   {label}: {masked(str(e), reader_pw)[:300]}")
        return bad

    failed = run_steps(plan)
    over_usl = bool(usl_plan) and run_steps(usl_plan) == 0
    if usl_plan and not over_usl:
        print("  -> USL failed: falling back to a schemastore view built directly on the sources")
    failed += run_steps(view_statements(over_usl))
    layer = f"USL {USL_TABLE} -> view {VIEW_NAME}" if over_usl else f"schemastore view {VIEW_NAME} (no USL)"
    print(f"\nsemantic layer: {layer}")

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
