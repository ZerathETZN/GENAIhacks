"""Score the pipeline against a ground_truth/exposures.json (tune on seed 7, never on seed 42's data).

  python scripts/eval_tuning.py [data_dir] [--warm] [--live]

--live reads through Zetaris and uses Nightshift (needs the stack up and .env). data_dir must then be the
seed that load_postgres.py loaded: it only supplies the answer key. The run fails if any run fell back to DuckDB.

Runs every recall in <data_dir>/recalls_used.json in sample mode (no model calls). Cold = fresh H-MEM
per recall; --warm shares one H-MEM across recalls. Decoys are false positives if they show up as an exposure.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.factory import get_adapter  # noqa: E402
from app.meterless.world_model import norm  # noqa: E402
from app.orchestrator import run  # noqa: E402
from app.schemas import Recall, RunInput, RunOptions, RunRequest  # noqa: E402

LIVE = "--live" in sys.argv
if LIVE:
    for line in Path(".env").read_text(encoding="utf-8").splitlines():  # same loader idea as scripts/demo_cold_warm.py
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))
    os.environ.pop("SAMPLE_MODE", None)
args = [a for a in sys.argv[1:] if not a.startswith("--")]
data_dir, warm = Path(args[0] if args else "data/tuning/seed7"), "--warm" in sys.argv
gt = data_dir / "ground_truth" / "exposures.json"  # seed 42 keeps its key at data/ground_truth
truth = json.loads((gt if gt.exists() else Path("data/ground_truth/exposures.json")).read_text(encoding="utf-8"))
recalls = json.loads((data_dir / "recalls_used.json").read_text(encoding="utf-8"))
tmp = tempfile.mkdtemp()
os.environ["LOG_DIR"] = tmp
os.environ["DECISIONS_FILE"] = os.path.join(tmp, "none.jsonl")  # the answer key expects the cold-run view: ignore real pharmacist verdicts

want = {(e["recall_id"], e["outlet_id"], e["batch_norm"]): e for e in truth["exposures"]}
decoys = {(d["outlet_id"], d["reg_no"], d["batch_norm"]) for d in truth["decoys"]}
got, fp_decoy, hit_unassigned, adapters = {}, [], 0, set()
for i, r in enumerate(recalls):
    rid = r["recall_id"]
    recall = Recall(**{k: r[k] for k in ("product_name", "reg_no", "batches", "date", "degree_level")})
    state = tmp if warm else tempfile.mkdtemp()
    res = run(RunRequest(run_id=f"ev{i}", input=RunInput(mode="recall_alert", recall=recall), options=RunOptions(sample_mode=not LIVE)),
              get_adapter(sample_mode=not LIVE, data_dir=data_dir), state)
    adapters.add(res.adapter)
    for e in res.output.exposures:
        key = (rid, e.outlet_id, norm(e.batch))
        got[key] = e
        if (e.outlet_id, norm(e.reg_no or recall.reg_no), norm(e.batch)) in decoys:
            fp_decoy.append(key)
    hit_unassigned += sum(c["outlet_id"] == "UNASSIGNED" for c in res.output.unresolved_conflicts)

found = want.keys() & got.keys()
qty_ok = [k for k in found if all(getattr(got[k], f) == want[k][f] for f in ("on_hand_qty", "sold_after_date_qty", "distinct_customers"))]
status_ok = [k for k in found if got[k].status == want[k]["expected_status"]]
print(f"data={data_dir} warm={warm} live={LIVE} recalls={len(recalls)} adapter={sorted(adapters)}")
if LIVE and adapters != {"zetaris"}:
    sys.exit(f"LIVE CHECK FAILED: expected only zetaris, got {sorted(adapters)} (a run fell back to DuckDB)")
print(f"exposures expected={len(want)} found={len(found)} missed={len(want.keys() - got.keys())} extra={len(got.keys() - want.keys())}")
print(f"quantities correct={len(qty_ok)}/{len(found)}  status correct={len(status_ok)}/{len(found)}  decoy false positives={len(fp_decoy)}")
print(f"unassigned deliveries expected={len(truth['unassigned'])} reported={hit_unassigned}")
for k in sorted(want.keys() - got.keys()):
    print("  MISSED", k, want[k]["conflicts"])
for k in sorted(got.keys() - want.keys()):
    print("  EXTRA ", k, got[k].status, got[k].on_hand_qty)
for k in sorted(set(found) - set(qty_ok)):
    print("  QTY   ", k, [(f, getattr(got[k], f), want[k][f]) for f in ("on_hand_qty", "sold_after_date_qty", "distinct_customers")])
for k in sorted(set(found) - set(status_ok)):
    print("  STATUS", k, "got", got[k].status, "want", want[k]["expected_status"], want[k]["conflicts"])
