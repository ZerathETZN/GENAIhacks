"""Build input_examples/ from the recalls the synthetic chain actually stocks (AGENTS.md §4). Owner: C.

  python scripts/make_examples.py [--data-dir data/sample]

Reads <data-dir>/recalls_used.json, written by scripts/generate_synthetic.py from the real NPRA recall
snapshot, so every example is a real recall (real product, MAL number, batches and date) that the
pipeline will find exposures for. Writes:
  example_1.json  recall_alert, live mode (Zetaris + Nightshift)
  example_2.json  recall_alert, sample mode, a degree-I recall when there is one
  example_3.json  daily_scan, sample mode
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "input_examples"


def request(run_id: str, recall: dict, sample: bool) -> dict:
    keys = ("product_name", "reg_no", "batches", "date", "degree_level")
    return {"run_id": run_id, "input": {"mode": "recall_alert", "recall": {k: recall.get(k) for k in keys}},
            "options": {"sample_mode": sample, "max_critic_rounds": 2}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/sample")
    a = ap.parse_args(argv)
    src = ROOT / a.data_dir / "recalls_used.json"
    if not src.exists():
        print(f"not found: {src} (run scripts/generate_synthetic.py first)", file=sys.stderr)
        return 1
    recalls = [r for r in json.loads(src.read_text(encoding="utf-8")) if r.get("batches")]
    if len(recalls) < 2:
        print(f"need >= 2 recalls with batches in {src}", file=sys.stderr)
        return 1
    first = recalls[0]
    second = next((r for r in recalls[1:] if str(r.get("degree_level")) == "I"), recalls[1])
    OUT.mkdir(exist_ok=True)
    files = {
        "example_1.json": request("example-1", first, False),
        "example_2.json": request("example-2", second, True),
        "example_3.json": {"run_id": "example-3", "input": {"mode": "daily_scan"},
                           "options": {"sample_mode": True, "max_critic_rounds": 2}},
    }
    for name, body in files.items():
        (OUT / name).write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(files)} examples from {src.relative_to(ROOT)}: "
          f"{first['recall_id']} (live), {second['recall_id']} (sample), daily_scan (sample)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
