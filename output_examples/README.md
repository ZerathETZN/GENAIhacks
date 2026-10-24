# Output examples

Every file here was saved from a **real run**. Nothing is hand-written or edited. Each folder holds the `RunResult` (`result*.json`) and the trace that run wrote (`trace-*.jsonl`).

| Folder | Input | Mode | What it shows |
|---|---|---|---|
| `ambiguous-names/` | recall `NPRA-2dd68f59bb`, Apalin 250mg Injection (degree I) | live: Zetaris + Nightshift | product names that differ across systems; Nemotron settles the ambiguous ones (`served_by` in the trace) |
| `cold_warm/` | the same Glumet XR 500mg recall, twice | live | H-MEM: the cold run leaves 3 `needs_review` items, a pharmacist answers them in `data/feedback/decisions.jsonl`, the warm run leaves 2 |
| `daily-scan/` | `daily_scan` over the regulator snapshot | live | 5 recalls the chain stocks, merged into one list labelled by `recall_id` |
| `administrative-whatif/` | a recall turned into a registration cancellation | live | **what-if scenario**: none of the stocked synthetic products is on the real cancelled list, so this is labelled as such; the rules rank by stock on hand instead of units sold |

Re-create them (live mode needs the stack from the README):

```bash
python scripts/run_example.py ambiguous-names --recall-id NPRA-2dd68f59bb --live
python scripts/run_example.py daily-scan --scan --live
python scripts/run_example.py administrative-whatif --recall-id NPRA-3cb59e559d --cancel --live
python scripts/demo_cold_warm.py cold --live   # then add your verdicts to data/feedback/decisions.jsonl
python scripts/demo_cold_warm.py warm --live
```

Score a saved run against the answer key:

```bash
python scripts/evaluate.py --result output_examples/ambiguous-names/result.json --recall-id NPRA-2dd68f59bb
```
