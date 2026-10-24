# Submission notes (Part C working file)

Text for the submission form, video and slides. Every number comes from the committed runs in `output_examples/` and from A's evaluation (24 Oct). Re-check them if code changes before submitting.

## Sponsor technology explanation (form field)

**Zetaris: the federated data layer.** The chain's four systems stay separate and share no IDs. Zetaris federates all of them:
- inventory, POS and regulator registers as three JDBC Postgres datasources;
- the supplier portal as a Lightning REST table.

A **USL semantic layer** (`recallguard_usl`) normalises batch and MAL numbers inside Zetaris under the view `recallguard.product_exposure_v`. Three agents use Zetaris:
- **Planner:** discovers the sources from the Zetaris catalogue.
- **Retriever:** reads the view.
- **Conflict Critic:** runs its own verification queries on the raw tables.

Live, it scores 22/22 with adapter `zetaris`, and the daily-scan trace makes 32 Zetaris calls.

Files: `app/adapters/zetaris_adapter.py`, `scripts/zetaris_register.py`, `scripts/load_postgres.py`.

**Meterless: Nightshift and two engines.**
- **Nightshift** is the model provider for every model call (`LLM_PROVIDER=meterless`). There is no direct NVIDIA client.
- **World Model** (required engine): the Retriever ingests every row with its source system and record ID, and each exposure's evidence resolves back to it (`tests/test_world_model_provenance.py`, `tests/test_world_model_ingest.py`).
- **H-MEM** keeps aliases the Critic verified, and pharmacist verdicts from `data/feedback/decisions.jsonl`, across runs. In `output_examples/cold_warm/`, the same recall goes from 3 `needs_review` items to 2, with 10 H-MEM hits in the warm trace (`tests/test_hmem_warm_start.py`).

**NVIDIA: Nemotron through Nightshift.** NVIDIA Nemotron 3.5 Super VL 120B, served through a Nightshift lane on our NVIDIA key, does two jobs:
- it decides the Reconciler's ambiguous product matches;
- it writes the Reporter's summary.

Every committed live trace records `served_by: nvidia/nemotron-3.5-super-vl-120b-a12b`.

## Demo video script (check the official length limit)

Record in **live mode**:
- Docker Desktop with Zetaris up;
- Nightshift open, with NVIDIA lanes only;
- `docker compose --profile live up -d --build`.

Open http://localhost:8501.

| Time | Show | Say |
|---|---|---|
| 0:00 | An NPRA recall notice, and the batch spelled 3 ways (inventory `5036723`, POS `s036723`, supplier `503-6723`) | "A recall lands. The chain's systems share no IDs and spell the batch differently." |
| 0:20 | Sidebar: API, Zetaris and Nightshift all green; run `example_1` (Glumet XR 500mg) | Live run on Zetaris and Nightshift |
| 0:40 | **Agent trace** tab: pipeline, catalogue discovery, the view query, Critic checks, `served_by` Nemotron | The agents discover the data, and the Critic checks every claim on raw tables |
| 1:15 | **Action list**: outlets ranked by units sold after the recall date; `needs_review` items flagged | What the operations manager does next |
| 1:35 | **Evidence** tab: one outlet's records from POS, inventory and supplier, plus the Critic's query | Every fact traced to a source record |
| 1:55 | **Pharmacist review** tab: answer the open question and download the line; then the warm run escalates fewer items | It learns from the pharmacist, between runs |
| 2:25 | Daily scan: 5 recalls in one ranked list | Runs every morning, not only on alerts |
| 2:45 | Hold-out score (31/31, precision 0.91, 0 decoys), the disclaimer and the limitations | Honest scope |

## Slides outline

1. **Problem:** a recall, fragmented systems, the risk to patients.
2. **Who it's for:** a pharmacy chain operations manager.
3. **Architecture:** five agents; Zetaris, Nightshift, World Model and H-MEM.
4. **Live trace example**, showing the Critic's independent check.
5. **Results:** the evaluation table, hold-out row first.
6. **Sponsor technology**, with the evidence above.
7. **Limitations:**
   - synthetic chain data;
   - strengths of the same brand not yet separated;
   - small datasets.
8. **Next steps:** real chain integration and strength-aware matching.
