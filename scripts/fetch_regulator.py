"""Download the real regulator datasets from data.gov.my (AGENTS.md §4.1).

  python scripts/fetch_regulator.py              # download + write sample snapshots
  python scripts/fetch_regulator.py --offline    # rebuild snapshots from data/raw/ only

Outputs
  data/raw/<name>_<YYYY-MM-DD>.parquet       full download (gitignored)
  data/sample/regulator/<name>.parquet       committed snapshot used by SAMPLE_MODE
  data/sample/regulator/manifest.json        source URL, licence, fetch date, rows, sha256

Loading into the rg-regulator container is load_postgres.py's job, not this script's.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import httpx

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
SAMPLE_DIR = ROOT / "data" / "sample" / "regulator"

BASE_URL = "https://storage.data.gov.my/healthcare"
LICENCE = "CC BY 4.0 (data.gov.my open data)"
CAVEAT = "data.gov.my: the data should not be used as the basis for legal action."

# name -> columns we rely on downstream. A missing column means the upstream
# schema changed: fail loudly instead of producing a silently broken snapshot.
DATASETS: dict[str, list[str]] = {
    "pharmaceutical_products_cancelled": ["reg_no", "product", "holder", "date_end"],
    "pharmaceutical_products": ["reg_no", "product", "status", "holder", "importer", "date_end"],
    "pharmaceutical_importers": ["license_no", "company", "state"],
    "pharmaceutical_wholesalers": ["company", "state", "poison"],
}

# Datasets too big to commit whole get a seeded random subset in data/sample/.
SAMPLE_ROWS = {"pharmaceutical_products": 2000}

TIMEOUT = httpx.Timeout(60.0, connect=15.0)
RETRIES = 2


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last_err: Exception | None = None
    for attempt in range(1 + RETRIES):
        try:
            with httpx.stream("GET", url, timeout=TIMEOUT, follow_redirects=True) as r:
                r.raise_for_status()
                with tmp.open("wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
            tmp.replace(dest)
            return
        except httpx.HTTPError as e:
            last_err = e
            print(f"  attempt {attempt + 1} failed: {e}", file=sys.stderr)
    raise RuntimeError(f"download failed after {1 + RETRIES} attempts: {url}") from last_err


def check_columns(path: Path, required: list[str]) -> None:
    cols = {row[0] for row in duckdb.sql(f"DESCRIBE SELECT * FROM read_parquet('{path.as_posix()}')").fetchall()}
    missing = [c for c in required if c not in cols]
    if missing:
        raise ValueError(f"{path.name}: upstream schema changed, missing columns {missing}")


def write_snapshot(raw: Path, out: Path, sample_rows: int | None, seed: int) -> int:
    """Copy raw -> out, optionally as a reproducible random subset. Returns row count."""
    out.parent.mkdir(parents=True, exist_ok=True)
    src = f"read_parquet('{raw.as_posix()}')"
    if sample_rows:
        # ORDER BY makes the subset stable for a given snapshot and seed.
        select = f"SELECT * FROM {src} USING SAMPLE reservoir({sample_rows} ROWS) REPEATABLE ({seed}) ORDER BY ALL"
    else:
        select = f"SELECT * FROM {src} ORDER BY ALL"
    duckdb.sql(f"COPY ({select}) TO '{out.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
    return duckdb.sql(f"SELECT count(*) FROM read_parquet('{out.as_posix()}')").fetchall()[0][0]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def latest_raw(name: str) -> Path | None:
    # Match the date suffix exactly: "pharmaceutical_products_*" would also match "..._cancelled_*".
    files = sorted(RAW_DIR.glob(f"{name}_[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].parquet"))
    return files[-1] if files else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="skip download, use newest file in data/raw/")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)

    today = datetime.now(timezone.utc).date().isoformat()
    manifest: dict = {"licence": LICENCE, "caveat": CAVEAT, "seed": args.seed, "datasets": {}}

    for name, required in DATASETS.items():
        url = f"{BASE_URL}/{name}.parquet"
        if args.offline:
            raw = latest_raw(name)
            if raw is None:
                print(f"{name}: no raw file in {RAW_DIR}, run without --offline first", file=sys.stderr)
                return 1
        else:
            raw = RAW_DIR / f"{name}_{today}.parquet"
            print(f"{name}: downloading {url}")
            download(url, raw)

        check_columns(raw, required)
        out = SAMPLE_DIR / f"{name}.parquet"
        rows = write_snapshot(raw, out, SAMPLE_ROWS.get(name), args.seed)
        total = duckdb.sql(f"SELECT count(*) FROM read_parquet('{raw.as_posix()}')").fetchall()[0][0]
        print(f"  -> {out.relative_to(ROOT).as_posix()}: {rows} of {total} rows")

        manifest["datasets"][name] = {
            "source_url": url,
            "fetched_on": raw.stem.rsplit("_", 1)[-1],
            "rows_upstream": total,
            "rows_in_sample": rows,
            "sampled": name in SAMPLE_ROWS,
            "file": out.relative_to(ROOT).as_posix(),
            "sha256": sha256(out),
        }

    (SAMPLE_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"manifest -> {(SAMPLE_DIR / 'manifest.json').relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
