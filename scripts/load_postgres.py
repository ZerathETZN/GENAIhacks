"""Load data/sample into the rg-* Postgres containers (AGENTS.md §4, §9).

  python scripts/load_postgres.py               # data/sample -> rg-inventory, rg-pos, rg-regulator
  python scripts/load_postgres.py --data-dir data/tuning/seed7

Idempotent: each table is dropped and recreated, then filled with COPY. Column types are
the same definitions the DuckDB adapter uses, so live and sample mode see one schema.
Supplier deliveries are not loaded here: rg-supplier-api serves them over REST.
Run zetaris_register.py afterwards (it refreshes Zetaris's cached column metadata).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import duckdb
import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from _env import load_env  # noqa: E402
from app.adapters.duckdb_adapter import (  # noqa: E402
    _RECALLS, _REGULATOR_PARQUET, _SALES, _STOCK, _TRANSFERS, _csv,
)

PG_TYPES = {"VARCHAR": "text", "INTEGER": "integer", "BIGINT": "bigint", "DOUBLE": "double precision",
            "DATE": "date", "TIMESTAMP": "timestamp", "BOOLEAN": "boolean"}

# database -> host port on this laptop (docker-compose.yml)
DATABASES = {"inventory": 5433, "pos": 5434, "regulator": 5435}


def tables(data_dir: Path, reg_dir: Path) -> dict[str, list[tuple[str, str, dict[str, str]]]]:
    """database -> [(table, duckdb source expression, {column: duckdb type})]"""
    out = {
        "inventory": [("stock", _csv(data_dir / "inventory" / "stock.csv", _STOCK), _STOCK),
                      ("transfers", _csv(data_dir / "inventory" / "transfers.csv", _TRANSFERS), _TRANSFERS)],
        "pos": [("sales", _csv(data_dir / "pos" / "sales.csv", _SALES), _SALES)],
        "regulator": [("npra_recalls", _csv(reg_dir / "npra_recalls.csv", _RECALLS), _RECALLS)],
    }
    for t in _REGULATOR_PARQUET:
        src = f"read_parquet('{(reg_dir / f'{t}.parquet').as_posix()}')"
        cols = {name: typ for name, typ, *_ in duckdb.sql(f"DESCRIBE SELECT * FROM {src}").fetchall()}
        out["regulator"].append((t, src, cols))
    return out


def load_table(conn: psycopg.Connection, table: str, src: str, cols: dict[str, str]) -> int:
    ddl = ", ".join(f'"{c}" {PG_TYPES.get(t, "text")}' for c, t in cols.items())
    rows = duckdb.sql(f"SELECT {', '.join(cols)} FROM {src}").fetchall()
    with conn.cursor() as cur:
        cur.execute(f'DROP TABLE IF EXISTS public."{table}"')
        cur.execute(f'CREATE TABLE public."{table}" ({ddl})')
        with cur.copy(f'COPY public."{table}" ({", ".join(chr(34) + c + chr(34) for c in cols)}) FROM STDIN') as cp:
            for r in rows:
                cp.write_row(r)
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data" / "sample")
    ap.add_argument("--host", default=os.getenv("PG_HOST", "localhost"))
    args = ap.parse_args(argv)
    load_env()

    password = os.getenv("PG_ADMIN_PASSWORD")
    if not password:
        print("PG_ADMIN_PASSWORD is not set (.env)", file=sys.stderr)
        return 1
    data_dir = args.data_dir if args.data_dir.is_absolute() else ROOT / args.data_dir
    if "ground_truth" in data_dir.parts:
        print("refusing to load data/ground_truth into a source system", file=sys.stderr)
        return 1

    for db, specs in tables(data_dir, ROOT / "data" / "sample" / "regulator").items():
        try:
            with psycopg.connect(host=args.host, port=DATABASES[db], dbname=db, user="postgres",
                                 password=password, connect_timeout=10) as conn:
                for table, src, cols in specs:
                    n = load_table(conn, table, src, cols)
                    print(f"  rg-{db}.{table}: {n} rows")
        except psycopg.OperationalError as e:
            print(f"cannot reach rg-{db} on {args.host}:{DATABASES[db]}: {e}\n"
                  "Is it running? docker compose up -d", file=sys.stderr)
            return 1
    print("done. Next: python scripts/zetaris_register.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
