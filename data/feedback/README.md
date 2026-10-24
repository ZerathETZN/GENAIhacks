# Pharmacist verdicts (`decisions.jsonl`)

The agents settle most matches themselves: the Critic checks each one against the raw tables, and H-MEM learns from the ones that pass. What's left are matches the Critic **can't** settle (for example a batch typo or a one-sided transfer). These come out as `needs_review`. This file is how a pharmacist answers them, **between runs** (AGENTS.md Rule 11: nobody interrupts a run).

## How to add a verdict

1. Run once ("cold run") and open the result. Look at items with `status: "needs_review"` and their `evidence`.
2. For each doubtful spelling you can decide, append **one line** to `decisions.jsonl`:

```json
{"field": "batch", "alias": "5o34698", "canonical": "5034698", "verdict": "same", "decided_by": "ethan", "decided_at": "2026-10-24T10:00:00Z", "run_id": "demo-001", "note": "POS typo: letter o for zero"}
```

| Key | Value |
|---|---|
| `field` | `batch`, `product_name` or `reg_no` |
| `alias` | the doubtful spelling, exactly as the source wrote it |
| `canonical` | the value it was compared against (the recall's batch, the registered name) |
| `verdict` | `same` (H-MEM learns the alias) or `different` (recorded; not learned as an alias) |
| `decided_by` | your handle. A real person, never an agent |
| `decided_at` | ISO 8601 UTC time |
| `run_id` | the run whose `needs_review` item you answered |
| `note` | why, in a few words |

3. Check the file: `python -m pytest -q tests/test_decisions_file.py`
4. Run again ("warm run"). H-MEM loads the verdicts, so those items should now resolve.
5. Commit `decisions.jsonl` together with both runs' traces (`output_examples/cold_warm/`).

## Rules

- Only answer items that a **real cold run** actually flagged. Writing verdicts in advance to make the warm run look better breaks Rule 2 (no fabricated logs).
- One line per `(field, alias)`. To change your mind, edit that line; don't add a second one.
- Spellings that `norm()` already equates (case, hyphens, spaces) need no verdict.
