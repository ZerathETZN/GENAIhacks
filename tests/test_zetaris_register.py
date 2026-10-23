"""zetaris_register.py builds the §5.1 statements without leaking the reader password."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("zr", ROOT / "scripts" / "zetaris_register.py")
zr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(zr)


def test_statements_cover_every_source_and_the_view():
    sql = " ".join(s for _, s, _ in zr.statements("reader", "pw"))
    for ds in ("inventory_pg", "pos_pg", "regulator_pg"):
        assert f"CREATE DATASOURCE {ds}" in sql and f"REFRESH DATASOURCE TABLES FROM {ds}" in sql
    assert "jdbc:postgresql://rg-inventory:5432/inventory" in sql
    assert "http://rg-supplier-api:8000/deliveries" in sql
    assert "CREATE SCHEMASTORE VIEW product_exposure_v WITH CONTAINER recallguard AS SELECT" in sql
    assert "DROP SCHEMASTORE VIEW product_exposure_v FROM recallguard" in sql
    assert ", 'g')" not in sql  # Spark regexp_replace has no flag argument


def test_option_values_are_escaped_and_dry_run_masks_password(capsys, monkeypatch):
    assert zr.q(r'a"b\c') == r'"a\"b\\c"'
    monkeypatch.setenv("PG_READER_PASSWORD", "s3cret-pw")
    assert zr.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "s3cret-pw" not in out and "****" in out
