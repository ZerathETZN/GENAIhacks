# Submission notes (Part C working file)

Fill each section from **real runs and traces**, never from memory. Delete this file or move its text into the README and form before submitting.

## Sponsor technology explanation (form field)

**Zetaris.** Our four fragmented sources are registered as Zetaris datasources: inventory, POS and regulator registers in Postgres, plus the supplier REST API as a Lightning REST table. The agents query them only through Zetaris.
- The Planner discovers sources with `SHOW DATASOURCES` and `DESCRIBE`.
- The Retriever reads the unified view `recallguard.product_exposure_v`, which normalises batch and registration numbers in Zetaris SQL.
- The Critic runs its own verification queries to check the Reconciler's claims.

Evidence: trace lines with `sponsor_call: "zetaris"` (count: __), and a screenshot of the view in the Zetaris UI.

**Meterless.** Nightshift is the default model provider (`LLM_PROVIDER=meterless`): every model call goes to Nightshift first.
- The **World Model** engine stores every retrieved row as a provenance-tracked entity, and each exposure's evidence resolves back to it (test: `tests/test_world_model_provenance.py`).
- H-MEM stores confirmed alias decisions, so a warm run escalates __ fewer items than a cold run.

Evidence: `provider: "meterless"` lines, the Nightshift lanes screenshot, and the test output.

**NVIDIA.** Nemotron 3.5 Super VL 120B and Nemotron 3.5 Lightning 30B are served through Nightshift lanes on our NVIDIA key. Evidence: `served_by` values in the committed traces: __.

## Demo video script (check the official length limit)

| Time | Show | Say |
|---|---|---|
| 0:00 | A recall notice and the 4 source systems | "A recall lands. The chain's systems share no IDs." |
| 0:20 | UI: Run agents (live mode), `/health` green | Zetaris + Nightshift running locally |
| 0:40 | Trace tab: Planner discovery → Retriever | sources found, not hard-coded |
| 1:10 | Trace: **Critic verify_query → needs_revision**, then `needs_review` | agents check each other |
| 1:40 | Action list + Evidence tab, customer-contact line | what the ops manager does next |
| 2:10 | Warm run: fewer escalations (H-MEM) | it learns from pharmacist decisions |
| 2:30 | Nightshift lanes (Nemotron), Zetaris UI | sponsor tech is load-bearing |
| 2:50 | Disclaimer + limitations | honest scope |

## Slides outline

1. Problem
2. Who it's for
3. Architecture
4. Live trace example
5. Results (`evaluate.py` precision and recall vs ground truth)
6. Sponsor tech
7. Limitations
8. Next steps
