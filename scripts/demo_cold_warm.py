"""Cold/warm H-MEM demo (AGENTS.md §7.5). Real model calls through Nightshift, DuckDB data.

  python scripts/demo_cold_warm.py cold [--recall-id ID] [--data-dir DIR]
  ... you read the printed doubts and append YOUR verdicts to data/feedback/decisions.jsonl ...
  python scripts/demo_cold_warm.py warm [--recall-id ID] [--data-dir DIR]

Outputs land in output_examples/cold_warm/ (trace-demo-<phase>.jsonl + result-<phase>.json).
Cold wipes state/cold_warm/ so H-MEM starts empty; warm reuses it. Nothing here writes verdicts.
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ap = argparse.ArgumentParser()
ap.add_argument("phase", choices=["cold", "warm"])
ap.add_argument("--recall-id")
ap.add_argument("--data-dir", default="data/tuning/seed7")
a = ap.parse_args()

for line in Path(".env").read_text(encoding="utf-8").splitlines() if Path(".env").exists() else []:  # token for Nightshift
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"'))

OUT, STATE = Path("output_examples/cold_warm"), Path("state/cold_warm")
OUT.mkdir(parents=True, exist_ok=True)
os.environ["LOG_DIR"] = str(OUT)
os.environ.pop("SAMPLE_MODE", None)  # the demo must use the real model

from app.adapters.factory import get_adapter  # noqa: E402
from app.orchestrator import run  # noqa: E402
from app.schemas import Recall, RunInput, RunOptions, RunRequest  # noqa: E402

recalls = json.loads((Path(a.data_dir) / "recalls_used.json").read_text(encoding="utf-8"))
if not a.recall_id:
    sys.exit("pick one with --recall-id:\n" + "\n".join(f"  {r['recall_id']}  {r['product_name']}" for r in recalls))
r = next(x for x in recalls if x["recall_id"] == a.recall_id)
if a.phase == "cold":
    shutil.rmtree(STATE, ignore_errors=True)

recall = Recall(**{k: r[k] for k in ("product_name", "reg_no", "batches", "date", "degree_level")})
res = run(RunRequest(run_id=f"demo-{a.phase}", input=RunInput(mode="recall_alert", recall=recall), options=RunOptions()),
          get_adapter(sample_mode=True, data_dir=a.data_dir), str(STATE))
(OUT / f"result-{a.phase}.json").write_text(res.model_dump_json(indent=2), encoding="utf-8")

review = [e for e in res.output.exposures if e.status == "needs_review"]
print(f"{a.phase}: {len(res.output.exposures)} exposures, {len(review)} needs_review, providers={res.providers_used}")
if a.phase == "warm":
    cold = OUT / "result-cold.json"
    if cold.exists():
        c = json.loads(cold.read_text(encoding="utf-8"))["output"]["exposures"]
        print(f"cold had {sum(e['status'] == 'needs_review' for e in c)} needs_review -> warm has {len(review)}")
else:
    doubts = [d for c in res.output.unresolved_conflicts for d in c.get("doubts", [])]
    print(f"\n{len(doubts)} doubtful spellings you can answer. For each one you decide, append a line to data/feedback/decisions.jsonl:")
    for d in doubts:
        print(f"  # {d['record_ref']}: is '{d['alias']}' the same {d['field']} as '{d['canonical']}'?")
        print('  {"field":"%s","alias":"%s","canonical":"%s","verdict":"same|different","decided_by":"<your handle>","decided_at":"<UTC ISO time>","run_id":"demo-cold","note":"<why>"}' % (d["field"], d["alias"], d["canonical"]))
    others = [c for c in res.output.unresolved_conflicts if not c.get("doubts")]
    print(f"\n{len(others)} other conflicts have no spelling to answer (one-sided transfer, unassigned delivery, ...); they stay needs_review.")
