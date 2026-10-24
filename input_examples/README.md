# Input examples

Requests in the AGENTS.md §7.1 format. Each one is a **real NPRA recall** (product, MAL number, batches, date and degree) that the synthetic chain stocks, taken from `data/sample/recalls_used.json`.

| File | Recall | Mode | Sample mode |
|---|---|---|---|
| `example_1.json` | Glumet XR Tablet 500mg, batch 5036723, degree II | `recall_alert` | live (Zetaris + Nightshift) |
| `example_2.json` | Apalin 250mg Injection, batch 242837T, degree I | `recall_alert` | sample (no credentials, no network) |
| `example_3.json` | every snapshot recall the chain stocks | `daily_scan` | sample |

```bash
python run.py --input input_examples/example_2.json            # sample mode
python run.py --input input_examples/example_1.json            # live mode (stack from the README)
python run.py --input input_examples/example_1.json --sample   # force sample mode
```

Regenerate after the synthetic data changes: `python scripts/make_examples.py`.
