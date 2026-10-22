"""Build input_examples/ from the committed NPRA recall snapshot (AGENTS.md §4.1). Owner: C.

  python scripts/make_examples.py            # after scripts/scrape_npra.py has written the snapshot

Writes example_1 (recall_alert, live), example_2 (recall_alert, sample mode) and example_3 (daily_scan).
Column names are matched loosely so the script keeps working if the snapshot header changes.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "data/sample/regulator/npra_recalls.csv"
OUT = ROOT / "input_examples"


def _col(header: list[str], *keys: str) -> str | None:
    for h in header:
        low = h.lower()
        if any(k in low for k in keys):
            return h
    return None


def _batches(raw: str) -> list[str]:
    # "2311021 and 2311022", "A1, A2", "A1/A2" -> ["2311021", "2311022"]
    parts = re.split(r"\s*(?:,|;|/|\band\b|\bdan\b|&)\s*", raw or "", flags=re.IGNORECASE)
    return [p.strip() for p in parts if p.strip()]


def _date(raw: str) -> str:
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw or "")
    if m:
        return m.group(0)
    m = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", raw or "")
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else raw


def main() -> int:
    if not SNAPSHOT.exists():
        print(f"snapshot not found: {SNAPSHOT} (run scripts/scrape_npra.py first)", file=sys.stderr)
        return 1
    with SNAPSHOT.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        c_name, c_reg = _col(header, "product", "name"), _col(header, "reg", "mal")
        c_batch, c_date = _col(header, "batch"), _col(header, "date", "tarikh")
        c_degree = _col(header, "degree", "level", "class")
        rows = [r for r in reader if c_batch and _batches(r.get(c_batch, ""))]
    if len(rows) < 2 or not (c_name and c_reg and c_date):
        print(f"need >=2 recalls with batches and name/reg/date columns; header={header}", file=sys.stderr)
        return 1

    OUT.mkdir(exist_ok=True)
    for i, (row, sample) in enumerate([(rows[0], False), (rows[1], True)], start=1):
        req = {
            "run_id": f"example-{i}",
            "input": {"mode": "recall_alert", "recall": {
                "product_name": row[c_name].strip(), "reg_no": row[c_reg].strip(),
                "batches": _batches(row[c_batch]), "date": _date(row[c_date]),
                "degree_level": (row.get(c_degree) or "").strip() or None if c_degree else None}},
            "options": {"sample_mode": sample, "max_critic_rounds": 2},
        }
        (OUT / f"example_{i}.json").write_text(json.dumps(req, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    scan = {"run_id": "example-3", "input": {"mode": "daily_scan"},
            "options": {"sample_mode": True, "max_critic_rounds": 2}}
    (OUT / "example_3.json").write_text(json.dumps(scan, indent=2) + "\n", encoding="utf-8")
    print(f"wrote 3 examples from {SNAPSHOT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
