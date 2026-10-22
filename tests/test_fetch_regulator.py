"""Offline tests for scripts/fetch_regulator.py (no network)."""

import importlib.util
from pathlib import Path

import duckdb
import pytest

_spec = importlib.util.spec_from_file_location(
    "fetch_regulator", Path(__file__).resolve().parents[1] / "scripts" / "fetch_regulator.py"
)
fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fr)


def _make_parquet(path: Path, n: int) -> Path:
    duckdb.sql(
        f"COPY (SELECT 'MAL' || lpad(i::VARCHAR, 8, '0') || 'A' AS reg_no, 'P' || i AS product "
        f"FROM range({n}) t(i)) TO '{path.as_posix()}' (FORMAT parquet)"
    )
    return path


def test_sample_is_reproducible(tmp_path):
    raw = _make_parquet(tmp_path / "raw.parquet", 500)
    a, b = tmp_path / "a.parquet", tmp_path / "b.parquet"
    assert fr.write_snapshot(raw, a, 50, seed=42) == 50
    fr.write_snapshot(raw, b, 50, seed=42)
    assert fr.sha256(a) == fr.sha256(b)


def test_full_copy_keeps_all_rows(tmp_path):
    raw = _make_parquet(tmp_path / "raw.parquet", 30)
    assert fr.write_snapshot(raw, tmp_path / "out.parquet", None, seed=42) == 30


def test_latest_raw_ignores_datasets_with_shared_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(fr, "RAW_DIR", tmp_path)
    for f in ["pharmaceutical_products_2026-10-01.parquet", "pharmaceutical_products_cancelled_2026-10-22.parquet"]:
        (tmp_path / f).touch()
    assert fr.latest_raw("pharmaceutical_products").name == "pharmaceutical_products_2026-10-01.parquet"


def test_schema_drift_fails_loudly(tmp_path):
    raw = _make_parquet(tmp_path / "raw.parquet", 3)
    fr.check_columns(raw, ["reg_no", "product"])
    with pytest.raises(ValueError, match="missing columns"):
        fr.check_columns(raw, ["reg_no", "date_end"])
