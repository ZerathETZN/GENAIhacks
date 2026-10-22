# RecallGuard

**Multi-agent recall exposure review for pharmacy chains.** Open Agent Hackathon 2026, Track 1: *Solving Fragmented Intelligence*. Team Invictus.

When Malaysia's drug regulator (NPRA) recalls or deregisters a product, a pharmacy chain has to find every outlet that still holds it or has already sold it. The answer is spread across inventory, point-of-sale and supplier systems that share no IDs and often disagree. RecallGuard's agents discover those sources through Zetaris, reconcile them against real regulator data, check each other's claims, and produce a **severity-ranked, per-outlet action list**. Every fact in it is traced to its source record.

> **For pharmacist review. Not a compliance verdict.** Regulator data comes from data.gov.my and NPRA open data (CC BY 4.0) and should not be used as the basis for legal action. Internal chain data in this project is **synthetic**.

---

## Quick start (sample mode: no credentials, no network)

```bash
git clone https://github.com/ZerathETZN/GENAIhacks.git && cd GENAIhacks
docker compose --profile sample up --build
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
docker compose up -d rg-inventory rg-pos rg-regulator
python scripts/fetch_regulator.py && python scripts/scrape_npra.py
python scripts/generate_synthetic.py --seed 42 && python scripts/load_postgres.py
python scripts/zetaris_register.py
docker compose --profile live up --build        # API :8000, UI :8501
```

`GET /health` reports whether Zetaris and Nightshift are reachable and which Nemotron routes Nightshift exposes.

## Interfaces

| Entry point | Use |
|---|---|
| `python run.py --input <file.json> [--output out.json] [--sample]` | One run; prints the `RunResult` JSON. Exit code 0 means success. |
| `python run.py --serve` | HTTP API on `0.0.0.0:$PORT` |
| `POST /run` | Request in the AGENTS.md §7.1 format, returns a `RunResult` (§7.2). Errors are returned as `status: "error"`, never as a crash. |
| `GET /health` | Liveness, plus Zetaris and Nightshift checks (skipped in sample mode) |
| `GET /runs/{run_id}` · `GET /runs/{run_id}/trace` | Saved result · trace events written by that run |
| `streamlit run ui/app.py` | UI with four views: ranked action list, evidence and Critic checks, agent trace timeline, raw JSON |

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
        → ConflictCriticAgent (runs its own Zetaris verification query; revise up to 2 rounds, else needs_review)
        → ReporterAgent (severity tiers from the NPRA rules table → ranked action list)
```

Every agent action and sponsor call is written to `logs/trace-<run_id>.jsonl` and printed to stdout. The trace records which agent acted, what it handed to whom, the Critic's verification query and its result, and `served_by`, the model that actually answered.

## AI and model usage

**Models:**
- NVIDIA **Nemotron 3.5 Super VL 120B** (`nvidia/nemotron-3.5-super-vl-120b-a12b`) for reasoning: Planner, Critic and Reporter summaries.
- NVIDIA **Nemotron 3.5 Lightning 30B** (`nvidia/nemotron-3.5-lightning-30b-a3b`) for fast batched matching.
- Both are **served through Meterless Nightshift**. There is no direct NVIDIA client: every model call goes through Nightshift.

**Sponsor technology:**
- **Zetaris:** the federated SQL layer over the four sources. Agents use it for catalogue discovery, the unified view `recallguard.product_exposure_v`, and the Critic's independent verification queries.
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

| Source | Real or synthetic | Licence |
|---|---|---|
| Cancelled and approved pharmaceutical products, licensed importers and wholesalers (data.gov.my) | real | CC BY 4.0 |
| NPRA product recall notices (snapshot, dated) | real | NPRA public notices |
| Inventory, POS (with hashed synthetic loyalty IDs), supplier deliveries | **synthetic** (`scripts/generate_synthetic.py --seed 42`) | n/a |

No personal data is used. Agents never read `data/ground_truth/`, which is used only by `scripts/evaluate.py`.

## Project status

<!-- Keep this table honest: update it as features merge. -->
| Component | Status |
|---|---|
| Contracts (`app/schemas.py`), DataAdapter interface, compose for data sources | ✅ merged |
| API, CLI, Docker image, UI, examples, clean-clone check | ✅ merged (Part C) |
| Orchestrator and agents | in progress |
| Zetaris adapter and registration | in progress |
| Nightshift generator, World Model engine, regulator fetch (data.gov.my) | ✅ merged |
| H-MEM | in progress |

## Known limitations

- Internal chain data is synthetic. Results show the method, not a real chain's exposure.
- Outputs are exposure reviews for a pharmacist to confirm, not regulatory decisions.
- The live mode needs Zetaris and Nightshift running on the same machine. Judges can use sample mode.
- *(Add measured limits from real runs before submission.)*

## Testing

```bash
pytest -q
scripts/clean_clone_check.sh          # fresh clone, empty .env, tests, sample run, container /health and /run
```

## Third-party code and licences

| Library | Licence |
|---|---|
| FastAPI | MIT |
| Uvicorn | BSD-3-Clause |
| pydantic | MIT |
| httpx | BSD-3-Clause |
| openai (Python SDK) | Apache-2.0 |
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
