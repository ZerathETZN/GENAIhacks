# RecallGuard

**Multi-agent recall exposure review for pharmacy chains.** Open Agent Hackathon 2026, Track 1: *Solving Fragmented Intelligence*. Team Invictus.

When Malaysia's drug regulator (NPRA) recalls or deregisters a product, a pharmacy chain has to find every outlet that still holds it or has already sold it. The answer is spread across inventory, point-of-sale and supplier systems that share no IDs and often disagree. RecallGuard's agents discover those sources through Zetaris, reconcile them against real regulator data, check each other's claims, and produce a **severity-ranked, per-outlet action list**. Every fact in it is traced to its source record.

> **For pharmacist review. Not a compliance verdict.** Regulator data comes from data.gov.my (CC BY 4.0) and NPRA's public recall notices; data.gov.my data should not be used as the basis for legal action. Internal chain data in this project is **synthetic**.

---

## Quick start (sample mode: no credentials, no network)

```bash
git clone https://github.com/ZerathETZN/GENAIhacks.git && cd GENAIhacks
docker compose --profile sample up --build app-sample ui-sample
```

- API: http://localhost:8000/docs
- UI: http://localhost:8501

Without Docker:

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
SAMPLE_MODE=true .venv/bin/python run.py --input input_examples/example_2.json
```

Sample mode runs the **real agent logic** over the committed sample data (DuckDB) with a deterministic heuristic model fallback. It never replays saved outputs.

## Live mode (Zetaris + Meterless Nightshift + NVIDIA Nemotron)

Prerequisites on the machine running the demo:

1. **Docker Desktop** running, with the Zetaris platform up (`docker compose up -d` in the Zetaris folder; UI on :3000, REST on :8888). This creates the `zetaris_default` network.
2. **Meterless Nightshift** open, with:
   - an NVIDIA key in Setup → Providers;
   - cloud lanes set to NVIDIA Nemotron 3.5 Super VL / Lightning 30B;
   - the local WebLLM lane stopped.
3. `cp .env.example .env`, then fill in:
   - `METERLESS_RUNTIME_TOKEN`, from Nightshift Console → API key (the NVIDIA key lives in Nightshift, not in `.env`);
   - `ZETARIS_API_KEY` and `ZETARIS_ORG_ID`;
   - the Postgres passwords.

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
docker compose up -d                     # rg-inventory, rg-pos, rg-regulator, rg-supplier-api
python scripts/load_postgres.py          # loads the committed data/sample into the three databases
python scripts/zetaris_register.py       # datasources, REST table, USL model, view; ends with row counts
python scripts/evaluate.py --data-dir data/sample --live   # optional check: 22/22, adapter zetaris
docker compose --profile live up -d --build                # API :8000, UI :8501
```

The data is committed, so live mode does not regenerate or re-download it (see Data below to rebuild it).

`GET /health` reports whether Zetaris and Nightshift are reachable and which Nemotron routes Nightshift exposes.

## Interfaces

| Entry point | Use |
|---|---|
| `python run.py --input <file.json> [--output out.json] [--sample]` | One run; prints the `RunResult` JSON. Exit code 0 means success. |
| `python run.py --serve` | HTTP API on `0.0.0.0:$PORT` |
| `POST /run` | Request in the AGENTS.md §7.1 format, returns a `RunResult` (§7.2). Errors are returned as `status: "error"`, never as a crash. |
| `GET /health` | Liveness, plus Zetaris and Nightshift checks (skipped in sample mode) |
| `GET /runs/{run_id}` · `GET /runs/{run_id}/trace` | Saved result · trace events written by that run |
| `streamlit run ui/app.py` | UI with five views: ranked action list, evidence and Critic checks, pharmacist review (writes `decisions.jsonl` lines), agent trace timeline, raw JSON |

Example request:

```json
{ "run_id": "demo-001",
  "input": { "mode": "recall_alert",
             "recall": { "product_name": "...", "reg_no": "MAL...", "batches": ["..."], "date": "YYYY-MM-DD" } },
  "options": { "sample_mode": true, "max_critic_rounds": 2 } }
```

Three examples are in `input_examples/`. `output_examples/` holds results and traces saved from real runs (`python run.py --input … --output output_examples/…`); nothing in it is hand-written.

## How the agents work

```
trigger → PlannerAgent (discovers sources in the Zetaris catalogue)
        → RetrieverAgent (queries via Zetaris; ingests into the World Model with provenance)
        → ReconcilerAgent (deterministic matching; Nemotron only for ambiguous cases)
        → ConflictCriticAgent (re-checks each exposure with its own query on the raw tables; else needs_review)
        → ReporterAgent (severity tiers from the NPRA rules table → ranked action list)
```

- **Planner** reads the Zetaris catalogue and fails the run if a required table or column is missing.
- **Retriever** reads the USL-backed view `recallguard.product_exposure_v` and ingests every row into the **World Model** with its source system and record ID.
- **Reconciler** matches records to the recall deterministically (normalised batch and MAL number, RapidFuzz on names). It consults **H-MEM** for aliases confirmed in earlier runs, and asks Nemotron only about the ambiguous cases, in batched calls.
- **Conflict Critic** runs its **own** queries on the raw source tables, not the view, so a mistake in the view or in matching cannot confirm itself. Anything it cannot settle becomes `needs_review`.
- **Reporter** applies `app/rules/actions.yaml` (from NPRA DRGD Appendix 34) and ranks outlets: safety recalls by units already sold to customers, administrative ones by stock on hand.

`daily_scan` runs the same pipeline for each snapshot recall the chain stocks (newest first, capped by `SCAN_LIMIT`) and merges them into one list labelled by `recall_id`.

**Learning between runs (H-MEM).** A pharmacist answers the open questions of a run in `data/feedback/decisions.jsonl` (the UI's *Pharmacist review* tab writes the lines for them). The next run loads them: in `output_examples/cold_warm/` the same recall goes from 3 `needs_review` items (cold) to 2 (warm).

Every agent action and sponsor call is written to `logs/trace-<run_id>.jsonl` and printed to stdout. The trace records which agent acted, what it handed to whom, the Critic's verification query and its result, and `served_by`, the model that actually answered.

## AI and model usage

**Models:**
- NVIDIA **Nemotron 3.5 Super VL 120B** (`nvidia/nemotron-3.5-super-vl-120b-a12b`), served through a Meterless Nightshift lane, for the Reconciler's ambiguous-match decisions and the Reporter's summary. Every committed live trace records it as `served_by`.
- NVIDIA **Nemotron 3.5 Lightning 30B** is configured as a second Nightshift lane.
- There is no direct NVIDIA client: every model call goes through Nightshift. The Planner, Critic and ranking are deterministic by design.

**Sponsor technology:**
- **Zetaris:** the federated SQL layer over the four sources, with a USL semantic layer under `recallguard.product_exposure_v`. Agents use it for catalogue discovery, retrieval and the Critic's independent verification queries (details below).
- **Meterless:** Nightshift is the default model provider (`LLM_PROVIDER=meterless`). The World Model engine holds shared, provenance-tracked entities; H-MEM stores confirmed alias decisions across runs.
- **NVIDIA:** the Nemotron models above, through Nightshift.

**Frameworks:** none. The orchestration is our own Python code, with FastAPI for the API and Streamlit for the UI.

**Development tools:** AI-assisted coding was used for scaffolding, tests and documentation. All code was reviewed and tested by the team.

**Fallbacks:**
- `adapter_fallback`: Zetaris down → DuckDB.
- Nightshift retries 429 / 5xx / empty responses up to 3 times; after that, or with no token, `generate` returns `heuristic_fallback` and the agent applies its deterministic rules.
- `heuristic_fallback`: no credentials, or sample mode.

Each one is logged in the trace.

## Data

RecallGuard reconciles **real regulator data** against a pharmacy chain's **synthetic** internal systems.

| Source | Real or synthetic | Rows | Licence / provenance |
|---|---|---|---|
| Cancelled pharmaceutical products (data.gov.my) | real | 1,615 | CC BY 4.0 |
| Approved pharmaceutical products (data.gov.my) | real | 2,000 (seeded sample of 28,327) | CC BY 4.0 |
| Licensed importers and wholesalers (data.gov.my) | real | 479 + 1,019 | CC BY 4.0 |
| NPRA product recall notices, Jan 2023 to Aug 2026 | real | 173 notices, 391 batches | NPRA website; reuse terms not stated, cited and used for this non-commercial project only |
| NPRA recall guideline (DRGD Appendix 34, July 2026) | real | 17 pages | NPRA; source of the severity and action rules |
| Inventory stock, stock transfers, POS sales, supplier deliveries | **synthetic** | 92 / 17 / 389 / 97 (seed 42) | generated by `scripts/generate_synthetic.py` |

data.gov.my: *the data should not be used as the basis for legal action.* Source URLs, fetch dates, row counts and checksums are in `data/sample/regulator/manifest.json`; column meanings in `data/README.md`.

**Why both kinds.** The data.gov.my registers carry registration numbers but **no batch numbers and no cancellation dates**. Real batch numbers exist only in NPRA's recall notices, so `scripts/scrape_npra.py` takes one dated snapshot of that page (multi-batch cells such as "2311021 and 2311022", numbered lists and Malay month names are parsed; the original text is kept as `batch_raw`). The chain's internal systems can't be real, so they are generated around those real recalls.

**What the synthetic chain looks like.** 8 outlets stock real recalled products next to real unaffected ones. Each system records things its own way, as real systems do:

| System | Batch | Product name | MAL number |
|---|---|---|---|
| Inventory (Postgres) | `5036723` | Glumet XR Tablet 500mg | usually present |
| POS (Postgres) | `5036723`, lowercase | `glumet xr tab 500mg` | never |
| Supplier portal (REST API) | `503-6723` | `GLUMET XR TABLET 500MG (BOX 30S)` | sometimes |

On top of that, every dataset contains each of these injected conflicts at least once: batch typos (`5o36723`), missing MAL numbers, sales after the recall date, sales from an outlet showing zero stock, stock delivered but never booked into inventory, transfers booked by only one outlet, deliveries from an unlicensed supplier, and a delivery with no outlet. **Decoys** (same product, unaffected batch) must not be flagged. Loyalty IDs are hashed synthetic values; there is no personal data.

**Three datasets, three jobs.** Each has its own answer key, read only by `scripts/evaluate.py`; agents never read it (enforced by the adapter and a test).

| Folder | Seed | Used for |
|---|---|---|
| `data/sample/` | 42 | sample mode (what you run) and the live demo |
| `data/tuning/seed7/` | 7 | tuning matching thresholds |
| `data/holdout/seed99/` | 99 | the honest score: created after all tuning, never used to change code |

Everything regenerates byte-for-byte:

```bash
python scripts/fetch_regulator.py        # re-downloads data.gov.my (new snapshot date)
python scripts/scrape_npra.py --offline  # re-parses the saved NPRA page; drop --offline to fetch again
python scripts/generate_synthetic.py --seed 42
python scripts/generate_synthetic.py --seed 7  --out data/tuning/seed7
python scripts/generate_synthetic.py --seed 99 --out data/holdout/seed99
```

## Zetaris: the federated data layer

In live mode **every data read goes through Zetaris**. The four internal sources stay where they are, in separate systems with no shared IDs:

| Source | Lives in | Registered in Zetaris as |
|---|---|---|
| Inventory (stock, transfers) | Postgres container `rg-inventory` | JDBC datasource `inventory_pg` |
| POS (sales) | Postgres container `rg-pos` | JDBC datasource `pos_pg` |
| Regulator registers + NPRA recalls | Postgres container `rg-regulator` | JDBC datasource `regulator_pg` |
| Supplier portal (deliveries) | small REST service `rg-supplier-api` (JSON over HTTP) | Lightning REST table `supplier_rest.deliveries` |

**Semantic layer: a Zetaris USL model.** `scripts/zetaris_register.py` compiles the Unified Semantic Layer model `recallguard_usl` (namespace `lightning.metastore.recallguard`) and activates its table `product_exposure` from a union of all four sources. Batch and MAL-number normalisation (upper-case, alphanumerics only) happens **inside Zetaris**, so `5036723`, `503-6723` and `s036723` line up in one column. The agents read it through the view `recallguard.product_exposure_v`, one row per internal record with its source and record ID for provenance.

How the agents use Zetaris:

- **Planner**: discovers the sources from the Zetaris catalogue (`SHOW DATASOURCES`, `SHOW LIGHTNING DATABASES`, `SHOW TABLES`, `DESCRIBE`) and fails the run if a required table or column is missing.
- **Retriever**: reads the USL-backed view, with values passed as parameters, never formatted into SQL.
- **Conflict Critic**: runs its **own** verification queries against the raw tables (not the view), so a mistake in the view or in matching cannot confirm itself.

**Sample mode is the same design without Zetaris.** A DuckDB adapter exposes the same table and view names over `data/sample/`, built from the same view definition, so agent code is identical in both modes. If Zetaris fails mid-run, the adapter falls back to DuckDB and the trace records `adapter_fallback` with the reason.

**Measured on live Zetaris (24 Oct):** the USL table and the view return 595 rows, identical to the DuckDB twin; `python scripts/evaluate.py --data-dir data/sample --live` scores 22/22 with adapter `zetaris` on every recall. USL activation is a live query, not a copy: rows changed in Postgres appear immediately.

**Zetaris behaviours we found and worked around** (details in `rules/AGENTS.md` §5.1):

- `CAST(x AS VARCHAR)` is rejected by the parser; use `STRING` or `DATE`.
- `GROUP BY` with an `OR` group and a function such as `UPPER()` in the same `WHERE` silently drops the filter; the Critic selects rows and counts in Python instead.
- `source` is reserved in USL DDL (backticks are stored literally), so the USL column is `source_system` and the view renames it.
- `400 Not Allowed` means a wrong org ID *or* an invalid API key; `docker logs zetaris-api-1` says which.

**Set it up** (Zetaris platform running first; it creates the `zetaris_default` network):

```bash
docker compose up -d                  # rg-inventory, rg-pos, rg-regulator, rg-supplier-api
python scripts/load_postgres.py       # loads data/sample into the three databases
python scripts/zetaris_register.py    # datasources, REST table, USL model, view; ends with row counts
```

`zetaris_register.py` is safe to re-run; `--dry-run` prints the SQL with passwords masked; `--no-usl` builds the view directly on the sources instead.

## Evaluation

`scripts/evaluate.py` runs every recall in a dataset through the full pipeline and scores the result against that dataset's answer key. An exposure is one (recall, outlet, batch) and counts as found only if the outlet and normalised batch match.

```bash
python scripts/evaluate.py --data-dir data/holdout/seed99           # hold-out, sample mode
python scripts/evaluate.py --data-dir data/sample --live            # through Zetaris
python scripts/evaluate.py --result output_examples/ambiguous-names/result.json --recall-id NPRA-2dd68f59bb
```

| Dataset | Exposures found | Extra | Precision | Quantities correct | Status correct | Decoys flagged |
|---|---|---|---|---|---|---|
| **Hold-out, seed 99 (sample mode)** | **31 / 31** | 3 | **0.91** | **31 / 31** | 29 / 31 | **0** |
| Seed 42, live Zetaris | 22 / 22 | 0 | 1.00 | 22 / 22 | 22 / 22 | 0 |
| Seed 42, sample mode | 22 / 22 | 0 | 1.00 | 22 / 22 | 22 / 22 | 0 |
| Seed 7 (tuning set) | 16 / 16 | 0 | 1.00 | 16 / 16 | 16 / 16 | 0 |

"Quantities correct" means on-hand units, units sold since the recall date and distinct customers all match. "Status" is `confirmed` vs `needs_review`.

**Read the hold-out row first.** Seed 7 was used for tuning, and two misses found on seed 42 were fixed afterwards, so their perfect scores are not independent. Seed 99 was generated after all tuning and has not been used to change code. What it shows:

- **No affected outlet was missed** and every quantity was right, including on a recall listing 16 batches and on a product covered by two separate NPRA notices.
- **3 extra rows, all marked `needs_review`:** for a Glumet XR **750mg** recall, stock of a recalled **500mg** batch was treated as a near-miss typo of a 750mg batch two digits away. A pharmacist would see these, since none was confirmed, but it is a real weakness: matching does not yet separate strengths of the same brand.
- **2 status disagreements:** the system asked for review where the answer key says the evidence was sufficient. That is over-caution, not a missed recall.

Limits of this evaluation: the data is synthetic (it shows the method works on realistic mess, not a real chain's exposure), the datasets are small (6 recalls, 8 outlets each), and the answer key encodes our own labelling rules for when a case needs review.

## Output examples

Every file in `output_examples/` was saved from a real run (`scripts/run_example.py`, `scripts/demo_cold_warm.py`); none is hand-written. See `output_examples/README.md` for what each one shows.

## Project status (24 Oct)

<!-- Keep this table honest: update it as features merge. -->
| Component | Status |
|---|---|
| Five agents and orchestrator, `recall_alert` and `daily_scan` | ✅ merged |
| Zetaris adapter, registration, USL semantic layer, catalogue discovery | ✅ merged, verified live |
| DuckDB twin for sample mode, `adapter_fallback` | ✅ merged |
| Nightshift generator, World Model, H-MEM with pharmacist verdicts | ✅ merged |
| Real regulator data, NPRA recall snapshot, synthetic chain (3 seeds), `evaluate.py` | ✅ merged |
| API, CLI, Docker image, Streamlit UI, examples, clean-clone check | ✅ merged |
| Optional guideline search (`app/rag/`) | built, not used by the agents |

## Known limitations

- Internal chain data is synthetic. Results show the method, not a real chain's exposure.
- Outputs are exposure reviews for a pharmacist to confirm, not regulatory decisions.
- The live mode needs Zetaris and Nightshift running on the same machine. Judges can use sample mode.
- Matching does not yet separate strengths of the same brand (the 3 extra hold-out rows above), and the datasets are small (6 recalls and 8 outlets each).
- `daily_scan` covers the newest `SCAN_LIMIT` (default 5) recalls per run, within a `SCAN_BUDGET_S` time budget; skipped recalls are listed, never dropped.
- In sample mode there is no model call: the agents' deterministic rules make every decision (`heuristic_fallback`).

## Testing

```bash
pytest -q
scripts/clean_clone_check.sh          # fresh clone, empty .env, tests, sample run, container /health and /run
python scripts/evaluate.py --data-dir data/holdout/seed99   # score against the hold-out answer key
```

## Third-party code and licences

| Library | Licence |
|---|---|
| FastAPI | MIT |
| Uvicorn | BSD-3-Clause |
| pydantic | MIT |
| httpx | BSD-3-Clause |
| DuckDB | MIT |
| psycopg | LGPL-3.0 |
| PyArrow | Apache-2.0 |
| RapidFuzz | MIT |
| PyYAML | MIT |
| Streamlit | Apache-2.0 |
| pandas | BSD-3-Clause |
| pytest | MIT |
| Ruff | MIT |

Sponsor documentation copied into `docs/` belongs to its owners.
