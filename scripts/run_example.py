"""Record one real run under output_examples/<name>/ (result.json + trace-<run_id>.jsonl).

  python scripts/run_example.py NAME (--recall-id ID [--cancel] | --scan) [--data-dir DIR] [--live]

--live reads through Zetaris and calls the model through Nightshift (needs the stack, .env, the seed that
load_postgres.py loaded). --cancel turns the recall into a registration cancellation (no batches, no degree,
today's date): a WHAT-IF scenario, since none of the stocked synthetic products is on the real cancelled list.
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ap = argparse.ArgumentParser()
ap.add_argument("name")
ap.add_argument("--recall-id")
ap.add_argument("--scan", action="store_true")  # daily_scan over the regulator snapshot
ap.add_argument("--data-dir", default="data/sample")
ap.add_argument("--live", action="store_true")
ap.add_argument("--cancel", action="store_true")
a = ap.parse_args()

if a.live:
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))
    os.environ.pop("SAMPLE_MODE", None)

OUT = Path("output_examples") / a.name
OUT.mkdir(parents=True, exist_ok=True)
os.environ["LOG_DIR"] = str(OUT)
os.environ["DECISIONS_FILE"] = os.path.join(tempfile.mkdtemp(), "none.jsonl")  # examples are single cold runs

from app.adapters.factory import get_adapter  # noqa: E402
from app.orchestrator import run  # noqa: E402
from app.schemas import Recall, RunInput, RunOptions, RunRequest  # noqa: E402

if not a.scan and not a.recall_id:
    sys.exit("give --recall-id ID or --scan")
r = None if a.scan else next(x for x in json.loads((Path(a.data_dir) / "recalls_used.json").read_text(encoding="utf-8")) if x["recall_id"] == a.recall_id)
fields = None if a.scan else {k: r[k] for k in ("product_name", "reg_no", "batches", "date", "degree_level")}
if a.cancel and fields:
    fields.update(batches=[], degree_level=None, date=date.today().isoformat())
run_id = f"example-{a.name}"
res = run(RunRequest(run_id=run_id, input=RunInput(mode="daily_scan") if a.scan else RunInput(mode="recall_alert", recall=Recall(**fields)), options=RunOptions(sample_mode=not a.live)),
          get_adapter(sample_mode=not a.live, data_dir=a.data_dir), tempfile.mkdtemp())
(OUT / "result.json").write_text(res.model_dump_json(indent=2), encoding="utf-8")
served = sorted({json.loads(l).get("served_by") for l in open(res.log_file) if json.loads(l).get("served_by")})
o = res.output
print(f"{a.name}: adapter={res.adapter} providers={res.providers_used} served_by={served}")
print(f"  {len(o.exposures)} exposures ({sum(e.status == 'needs_review' for e in o.exposures)} needs_review), severities={sorted({e.severity for e in o.exposures})}, rule={o.exposures[0].rule_ref if o.exposures else None}")
print("  summary:", o.summary[:300])
