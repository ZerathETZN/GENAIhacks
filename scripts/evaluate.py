"""Score RecallGuard against an answer key (AGENTS.md §9, §12).

Run every recall of a dataset, then score (sample mode unless --live):
  python scripts/evaluate.py --data-dir data/holdout/seed99          # the honest, untouched score
  python scripts/evaluate.py --data-dir data/sample --live           # through Zetaris + Nightshift
  python scripts/evaluate.py --data-dir data/sample --json out.json  # also write the numbers

Score a run that already happened (e.g. a committed example):
  python scripts/evaluate.py --result output_examples/ambiguous-names/result.json --recall-id NPRA-2dd68f59bb
  python scripts/evaluate.py --result output_examples/daily-scan/result.json        # scan rows carry recall_id

Answer key: <data-dir>/ground_truth/exposures.json, or data/ground_truth/exposures.json for data/sample.
Only this script and scripts/eval_tuning.py read answer keys; agents never do (Rule 9).
The key describes a COLD run. After pharmacist verdicts, a warm run may confirm items the key
lists as needs_review: that STATUS difference is the intended effect, not an error.

Metrics
  found / missed / extra  exposures matched on (recall_id, outlet_id, normalised batch)
  precision, recall       found / (found + extra), found / expected
  quantities correct      on_hand_qty, sold_after_date_qty and distinct_customers all equal the key
  status correct          confirmed vs needs_review equals the key
  decoy false positives   a non-affected batch reported as an exposure (must be 0)
  unassigned reported     deliveries with no outlet listed in unresolved_conflicts
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

QTY_FIELDS = ("on_hand_qty", "sold_after_date_qty", "distinct_customers")


def norm(v) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(v or "").upper())


def answer_key_path(data_dir: Path) -> Path:
    own = data_dir / "ground_truth" / "exposures.json"
    return own if own.exists() else ROOT / "data" / "ground_truth" / "exposures.json"


def load_truth(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def score(results: list[tuple[str, dict]], truth: dict) -> dict:
    """results: [(recall_id, RunResult as dict)]. Only recalls that are both in `results` and in the
    answer key are scored; rows from other recalls (a daily_scan also checks real notices the key
    does not cover) are listed under `unkeyed` instead of counting as false positives."""
    keyed = {e["recall_id"] for e in truth["exposures"]} | {u["recall_id"] for u in truth.get("unassigned", [])}
    unkeyed_ids = sorted({rid for rid, _ in results} - keyed)
    results = [(rid, res) for rid, res in results if rid in keyed]
    recall_ids = {rid for rid, _ in results}
    want = {(e["recall_id"], e["outlet_id"], e["batch_norm"]): e for e in truth["exposures"] if e["recall_id"] in recall_ids}
    decoys = {(d["outlet_id"], d["reg_no"], d["batch_norm"]) for d in truth["decoys"]}
    got: dict[tuple, dict] = {}
    decoy_hits, unassigned, adapters, errors = [], 0, set(), []
    for rid, res in results:
        adapters.add(res.get("adapter"))
        if res.get("status") != "success":
            errors.append((rid, (res.get("error") or {}).get("message", "error")))
            continue
        out = res.get("output") or {}
        for e in out.get("exposures", []):
            key = (e.get("recall_id") or rid, e["outlet_id"], norm(e["batch"]))
            got[key] = e
            if (e["outlet_id"], e.get("reg_no"), norm(e["batch"])) in decoys:
                decoy_hits.append(key)
        unassigned += sum(c.get("outlet_id") == "UNASSIGNED" for c in out.get("unresolved_conflicts", []))

    found = sorted(want.keys() & got.keys())
    qty_bad = [k for k in found if any(got[k].get(f) != want[k][f] for f in QTY_FIELDS)]
    status_bad = [k for k in found if got[k].get("status") != want[k]["expected_status"]]
    extra = sorted(got.keys() - want.keys())
    n_found = len(found)
    return {
        "recalls": len(recall_ids),
        "adapters": sorted(a for a in adapters if a),
        "expected": len(want),
        "found": n_found,
        "missed": sorted(want.keys() - got.keys()),
        "extra": extra,
        "precision": round(n_found / (n_found + len(extra)), 3) if n_found + len(extra) else None,
        "recall": round(n_found / len(want), 3) if want else None,
        "quantities_correct": n_found - len(qty_bad),
        "status_correct": n_found - len(status_bad),
        "qty_mismatches": [(k, {f: (got[k].get(f), want[k][f]) for f in QTY_FIELDS}) for k in qty_bad],
        "status_mismatches": [(k, got[k].get("status"), want[k]["expected_status"], want[k]["conflicts"]) for k in status_bad],
        "decoy_false_positives": decoy_hits,
        "unassigned_expected": sum(u["recall_id"] in recall_ids for u in truth.get("unassigned", [])),
        "unassigned_reported": unassigned,
        "errors": errors,
        "unkeyed_recalls": unkeyed_ids,
    }


def report(s: dict, label: str) -> None:
    print(f"{label}: {s['recalls']} recalls, adapter={s['adapters']}")
    print(f"  exposures   expected={s['expected']} found={s['found']} missed={len(s['missed'])} extra={len(s['extra'])}"
          f"   precision={s['precision']} recall={s['recall']}")
    print(f"  quantities  correct={s['quantities_correct']}/{s['found']}   status correct={s['status_correct']}/{s['found']}")
    print(f"  decoys      false positives={len(s['decoy_false_positives'])}"
          f"   unassigned deliveries expected={s['unassigned_expected']} reported={s['unassigned_reported']}")
    for k in s["missed"]:
        print("  MISSED ", k)
    for k in s["extra"]:
        print("  EXTRA  ", k)
    for k, diff in s["qty_mismatches"]:
        print("  QTY    ", k, "got/want", diff)
    for k, got, want, conflicts in s["status_mismatches"]:
        print("  STATUS ", k, f"got {got} want {want}", conflicts)
    for k in s["decoy_false_positives"]:
        print("  DECOY  ", k)
    if s["unkeyed_recalls"]:
        print(f"  not scored  {len(s['unkeyed_recalls'])} recall(s) not in the answer key: {', '.join(s['unkeyed_recalls'])}")
    for rid, msg in s["errors"]:
        print("  ERROR  ", rid, msg[:200])


def run_dataset(data_dir: Path, live: bool, warm: bool) -> list[tuple[str, dict]]:
    """Run every recall in <data_dir>/recalls_used.json through the real pipeline."""
    from _env import load_env

    if live:
        load_env()
        os.environ.pop("SAMPLE_MODE", None)
    from app.adapters.factory import get_adapter
    from app.orchestrator import run
    from app.schemas import Recall, RunInput, RunOptions, RunRequest

    tmp = tempfile.mkdtemp(prefix="rg-eval-")
    os.environ["LOG_DIR"] = tmp
    # The answer key describes a cold run, so real pharmacist verdicts must not be loaded.
    os.environ["DECISIONS_FILE"] = os.path.join(tmp, "no-verdicts.jsonl")
    recalls = json.loads((data_dir / "recalls_used.json").read_text(encoding="utf-8"))
    results = []
    for i, r in enumerate(recalls):
        recall = Recall(**{k: r[k] for k in ("product_name", "reg_no", "batches", "date", "degree_level")})
        state = tmp if warm else tempfile.mkdtemp(prefix="rg-eval-state-")
        res = run(RunRequest(run_id=f"eval-{i}", input=RunInput(mode="recall_alert", recall=recall),
                             options=RunOptions(sample_mode=not live)),
                  get_adapter(sample_mode=not live, data_dir=data_dir), state)
        results.append((r["recall_id"], res.model_dump(mode="json")))
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--data-dir", type=Path, help="run every recall of this dataset, then score")
    src.add_argument("--result", type=Path, help="score a saved RunResult JSON")
    ap.add_argument("--recall-id", help="with --result: the recall a recall_alert result answered")
    ap.add_argument("--truth", type=Path, help="answer key (default: from --data-dir, else data/ground_truth)")
    ap.add_argument("--live", action="store_true", help="read through Zetaris + Nightshift (needs the stack and .env)")
    ap.add_argument("--warm", action="store_true", help="share one H-MEM across recalls")
    ap.add_argument("--json", type=Path, help="also write the score as JSON")
    args = ap.parse_args(argv)

    if args.data_dir:
        data_dir = args.data_dir if args.data_dir.is_absolute() else ROOT / args.data_dir
        truth = load_truth(args.truth or answer_key_path(data_dir))
        results = run_dataset(data_dir, args.live, args.warm)
        label = f"{data_dir.relative_to(ROOT).as_posix() if data_dir.is_relative_to(ROOT) else data_dir} live={args.live} warm={args.warm}"
    else:
        res = json.loads(args.result.read_text(encoding="utf-8"))
        rids = {e.get("recall_id") for e in (res.get("output") or {}).get("exposures", [])} - {None}
        if args.recall_id:
            rids = {args.recall_id}
        if not rids:
            print("this result does not say which recall it answered: pass --recall-id", file=sys.stderr)
            return 2
        truth = load_truth(args.truth or ROOT / "data" / "ground_truth" / "exposures.json")
        # A scan result covers several recalls: score it once per recall it contains.
        results = [(rid, res) for rid in sorted(rids)] if not args.recall_id else [(args.recall_id, res)]
        if len(results) > 1:
            results = [(rid, {**res, "output": {**res["output"], "exposures": [e for e in res["output"]["exposures"] if e.get("recall_id") == rid],
                                                 "unresolved_conflicts": [c for c in res["output"].get("unresolved_conflicts", []) if c.get("recall_id") == rid]}})
                       for rid, _ in results]
        label = f"{args.result.as_posix()}"

    s = score(results, truth)
    report(s, label)
    if args.json:
        args.json.write_text(json.dumps(s, indent=2, default=str) + "\n", encoding="utf-8")
    if args.live and s["adapters"] != ["zetaris"]:
        print(f"LIVE CHECK FAILED: expected only zetaris, got {s['adapters']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
