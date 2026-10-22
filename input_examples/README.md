# Input examples

Requests in the AGENTS.md §7.1 format. Run one with:

```bash
python run.py --input input_examples/example_1.json
```

| File | Mode | Sample mode |
|---|---|---|
| `example_1.json` | `recall_alert` | live (Zetaris + Nightshift) |
| `example_2.json` | `recall_alert` | sample (no credentials, no network) |
| `example_3.json` | `daily_scan` | sample |

The recall fields come from the real NPRA recall snapshot (`data/sample/regulator/npra_recalls.csv`).
Regenerate them after the snapshot changes:

```bash
python scripts/make_examples.py
```

> Until the snapshot is committed, examples 1 and 2 hold clearly marked `PLACEHOLDER` values.
