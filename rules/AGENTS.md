# AGENTS.md: RecallGuard (Open Agent Hackathon 2026, Track 1)

> **Context for coding agents** (Cursor Agent, Codex). Read this file fully before writing code.
> - If anything here conflicts with a direct instruction from a teammate, follow the teammate and update this file in the same commit.
> - Version 2.2, 23 Oct 2026. Agreed the `product_exposure_v` column contract with B (§7.4), `?` parameter handling (§5.1), Critic reads raw tables, and data findings from the real regulator files (§4.1, §4.2).
> - Version 2, 21 Oct 2026. Supersedes v1: the provider is now Nightshift-first, Zetaris is reached over REST, regulator data comes from data.gov.my open data, and `metadata.json` is added.

---

## 1. What we are building

**RecallGuard** is a multi-agent system for a **retail pharmacy chain's operations manager**. It finds every outlet that still holds, or has sold, a product that Malaysia's drug regulator (NPRA / Drug Control Authority) has **recalled or deregistered**.

It reconciles **real public regulator data** against the chain's **fragmented internal systems**: inventory, point of sale, and supplier deliveries. These systems share no IDs and often disagree. The output is a **severity-ranked, per-outlet action list**. Every fact in it is traced to its source system and record, with a confidence score, and every item is marked **"for pharmacist review"**.

- **Team Invictus** (3 people):
  - **A (Ethan):** data and Zetaris.
  - **B:** agents and Meterless.
  - **C:** product and delivery.
- **Track:** Solving Fragmented Intelligence. Track wording: *"discover and work across fragmented data sources"*.
- **Build window:** 22 Oct 2026 00:00 UTC to 27 Oct 2026 23:45 UTC.
- **Internal submit target:** 27 Oct 12:00 UTC. Ties go to the earlier submission.

---

## 2. Non-negotiable rules (violations can disqualify the team or lose Sponsor Tech points)

1. **No hardcoded outputs.** Never return pre-written answers, never branch on known sample inputs, never read `output_examples/` at runtime.
2. **No fabricated logs.** Traces are written only by real execution.
3. **No secrets in the repo.**
   - Credentials come only from env vars.
   - Only `.env.example` (placeholders) is committed. `.env` is gitignored.
   - Mask keys in logs.
4. **Power rule: Meterless Runtime (Nightshift) must be a working AI provider in the product** (organiser clarification, 22 Oct). It is added *alongside* other providers, and existing providers may stay.
   - Every model call goes through `app/llm/generator.py`, which selects the provider via `LLM_PROVIDER=meterless|heuristic`.
   - **Default is `meterless`.** The demo video and committed live traces must show real calls served through Meterless, never a mocked call.
   - Use the organisers' Cursor prompt (HackOS → Power section) to add the integration, then check it against §5.2 (headers, timeouts, `served_by` tracing).
5. **Zetaris and Meterless must be load-bearing and running locally** for the live demo:
   - Every data read in live mode goes through Zetaris.
   - Agent context goes through the Meterless engines.
6. **Build rule: at least ONE Meterless engine integrated into the running application, with proof** (organiser clarification, 22 Oct). The engines are product components; using them as coding aids doesn't count.
   - **Required:** World Model.
   - **Should:** H-MEM, cuttable.
   - **Proof:** a reproducible feature test with committed traces from real runs (§5.2).
7. **`SAMPLE_MODE=true` runs real agent logic with no credentials and no network.**
   - Uses the DuckDB adapter over `data/sample/` plus the heuristic generator.
   - Must not replay saved outputs.
8. **Bounded runs.**
   - Every external call has a timeout.
   - Every loop has a cap.
   - A full run targets under 10 minutes.
9. **Agents never read `data/ground_truth/`.** It exists only for `scripts/evaluate.py`, enforced by a test.
10. **Synthetic data is labelled synthetic** everywhere. Real data is cited with its licence.
11. **No runtime human-in-the-loop.**
    - Ambiguous cases become `needs_review`.
    - Human verdicts return between runs via `data/feedback/decisions.jsonl`.
12. **Do not invent sponsor APIs.** If behaviour isn't documented in `docs/` or confirmed in §11, stop, leave `TODO(verify):`, and ask the team.
13. **Responsible AI.**
    - Outputs are exposure reviews "for pharmacist review", never compliance verdicts.
    - Include the data.gov.my caveat: the data should not be used as the basis for legal action.

---

## 3. Architecture

```
trigger (recall_alert | daily_scan)
   │
   ▼
PlannerAgent ────────── DISCOVERS sources via adapter.catalogue() (Zetaris: SHOW DATASOURCES / SHOW LIGHTNING DATABASES /
   │                    SHOW TABLES / DESCRIBE; DuckDB: information_schema) → picks tables with batch-, MAL- or reg_no-like columns → query plan
   ▼
RetrieverAgent ──────── parameterised queries via DataAdapter (Zetaris REST live / DuckDB sample)
   │                    prefers the Zetaris unified view `recallguard.product_exposure_v`
   │                    ingests every row into the World Model with provenance
   ▼
ReconcilerAgent ─────── deterministic normalisation + rapidfuzz scoring; only ambiguous candidates go to the LLM (batched)
   │                    reads H-MEM for previously confirmed alias decisions
   ▼
ConflictCriticAgent ─── for every candidate exposure, RUNS ITS OWN verification query through Zetaris
   │                    (e.g. on-hand qty of batch X at outlet Y) and compares with the Reconciler's claim
   │   ├─ mismatch / weak evidence → revision request (max MAX_CRITIC_ROUNDS=2)
   │   └─ still unresolved → status = needs_review
   ▼
ReporterAgent ───────── severity tiering + action rules table → ranked per-outlet action list
   │                    (+ customer-contact counts from POS)
   ▼
JSON result + static HTML report + logs/trace-<run_id>.jsonl
```

| Agent | Model (via Nightshift) | Input | Output |
|---|---|---|---|
| PlannerAgent | reasoning | trigger + catalogue metadata | query plan |
| RetrieverAgent | none (deterministic) | plan | World Model entities |
| ReconcilerAgent | fast, ambiguous cases only, batched | entities + H-MEM | exposure candidates + match evidence |
| ConflictCriticAgent | reasoning + its own Zetaris queries | candidates | approve / revise / needs_review |
| ReporterAgent | reasoning (summary text only) | approved exposures + rules table | ranked action list |

**The trace must show:**
- catalogue discovery
- delegation
- **the Critic's independent Zetaris query and at least one rejection or revision** on realistic data
- escalation to `needs_review`

Never collapse agents into one prompt.

---

## 4. Data sources (four fragmented sources + one document)

All databases run as **containers on the Zetaris Docker network `zetaris_default`**, so Zetaris reaches them by container name. Ours are prefixed `rg-` to avoid clashing with Zetaris's own `postgres` service.

| # | Source | Container / Zetaris name | Real or synthetic | Notes |
|---|---|---|---|---|
| 1 | Inventory system | `rg-inventory` (Postgres) → datasource `inventory_pg` | synthetic | uppercase batches, MAL no. mostly present, stock transfers table |
| 2 | POS system | `rg-pos` (Postgres) → datasource `pos_pg` | synthetic | lowercase batches, internal SKU, no MAL no., hashed synthetic `loyalty_id` |
| 3 | Regulator registers | `rg-regulator` (Postgres) → datasource `regulator_pg` | **real**, data.gov.my, CC BY 4.0 | cancelled pharmaceutical products, approved products, licensed importers and wholesalers, plus the NPRA recall-notice snapshot |
| 4 | Supplier portal | `rg-supplier-api` (FastAPI) → Lightning DB `supplier_rest`, table `deliveries` | synthetic | REST JSON; hyphenated batches, supplier product names |
| doc | NPRA recall guideline | `data/docs/` | real | the source of the action rules table (§5.4) |

### 4.1 Regulator data (real)

`scripts/fetch_regulator.py` downloads the data.gov.my Parquet files:
- e.g. `https://storage.data.gov.my/healthcare/pharmaceutical_products_cancelled.parquet`
- plus the approved products, importers and wholesalers datasets.

The script then:
- keeps the full downloads in `data/raw/<name>_<date>.parquet` (gitignored)
- writes snapshots to `data/sample/regulator/<name>.parquet` (committed, for sample mode). `pharmaceutical_products` (28k rows) is cut to a seeded 2,000-row subset; the other three are kept whole.
- writes `data/sample/regulator/manifest.json` (URL, fetch date, row counts, sha256); licence and caveat are in `data/README.md`
- does **not** load Postgres; `load_postgres.py` does that.

**What the real files do and don't contain (verified 22 Oct):**
- `reg_no` is present in all product files. **There are no batch numbers anywhere on data.gov.my.** Real batches come only from the NPRA recall notices, so `scrape_npra.py` is required, not optional.
- `pharmaceutical_products_cancelled` has **no cancellation date**. Its `date_end` is the registration expiry and can be in the future. Never treat `date_end` as the cancellation date.

**Why not register the Parquet directly in Zetaris?** Zetaris file tables read `s3a://` paths. A browser or download URL is not a valid `PATH`, and Zetaris cannot read files on a laptop. Loading the data into Postgres keeps it federated and reproducible.

**Recall notices:**
- These are not on data.gov.my.
- `scripts/scrape_npra.py` fetches the NPRA Product Recall table **once** into `data/sample/regulator/npra_recalls.csv`, which is then loaded into `rg-regulator`.
- Parse multi-batch fields ("2311021 and 2311022") into lists; keep `batch_raw` for provenance.

### 4.2 Synthetic internal data

`scripts/generate_synthetic.py --seed 42 --outlets 8 --records 500` writes `data/sample/*.csv|json` and `data/ground_truth/exposures.json`.

- **Seeding:** the product catalogue uses real recalled or cancelled `reg_no` and batch values from §4.1, mixed with clean products.
- **Injected conflicts** (random, seeded):
  - batch format variants
  - name variants and typos (Malay vs English)
  - missing MAL number
  - delivered but missing from inventory
  - sale after the recall or cancellation date (the recall date comes from NPRA; for cancelled products with no NPRA notice, use a synthetic cancellation date and label it synthetic)
  - sale from an outlet showing zero stock
  - one-sided transfers
  - delivery from an unlicensed supplier
- **Decoys:** same product, non-affected batch. These must NOT be flagged.
- **Tuning vs scoring:** tune matching thresholds on a seed other than 42. Seed 42 is what `evaluate.py` scores, so tuning on it inflates the results.

---

## 5. Sponsor technology integration

### 5.1 Zetaris: federated data layer (required)

**Access path: REST, not JDBC** (no Java in our image). See `docs/zetaris/` and the getting-started client-setup guide.

| Item | Value |
|---|---|
| API base | `ZETARIS_REST_URL` (local default `http://localhost:8888/api/v1.0`; from inside our container `http://host.docker.internal:8888/api/v1.0`) |
| Run SQL | `POST {ZETARIS_REST_URL}/sql-editor/sqls/run` |
| Headers | `Authorization: Bearer ${ZETARIS_API_KEY}`, `X-Org-ID: ${ZETARIS_ORG_ID}` (numeric, from Management → Organisation), `X-Request-ID: <uuid4 per request>` |
| Body | `{"queryId": "<uuid4>", "sql": "...", "source": "SqlEditor", "limit": N}` |
| Response (verified 21 Oct) | `{"headers": ["one"], "data": [["1"]], "total": 1, "timeUsed": 382}`. Rows are **lists, not dicts**: zip each row with `headers`. All values are **strings**: cast them. |
| Errors | `401` → new API key (Management → API Tokens). `400 Not Allowed` → wrong org ID **or** an invalid/expired API key (`docker logs zetaris-api-1` says `Org id mismatch` or `Api token is not allowed`). A `ZETARIS_*` variable left in the shell overrides `.env`. `400` on a valid request → non-UUID `X-Request-ID` or `queryId`. |

**Lightning SQL rules:**
- One statement per call.
- Use qualified names: `<source>.<table>`.
- It's the Spark SQL dialect.
- **REST returns values as strings** (decimals may use exponent format). Cast in the adapter before comparing.
- After any schema change in a source DB, run `REFRESH DATASOURCE TABLES FROM <datasource>`. Zetaris caches column metadata.
- **Verified on our instance (23 Oct), write agent SQL accordingly:**
  - Use `CAST(x AS STRING)`, never `CAST(x AS VARCHAR)`: Zetaris rejects `VARCHAR` with a parse error (`expecting 'METADATA'`). DuckDB accepts `STRING` too. To compare dates, prefer `CAST(col AS DATE) >= CAST(? AS DATE)`.
  - **Bug: `GROUP BY` + a `WHERE` that combines an `OR` group with a function such as `UPPER(REPLACE(...))` silently drops the whole filter** and aggregates every row. Each part alone is fine, and plain `SUM`/`COUNT` without `GROUP BY` is fine. Workaround: select the filtered rows and group in Python.
  - Registered names match §7.4 exactly (`inventory_pg.stock`, `pos_pg.sales`, `supplier_rest.deliveries`, `regulator_pg.*`). The REST table returns `qty` as `bigint` and dates as `string`; the view casts them.
  - Schemastore view: `CREATE SCHEMASTORE VIEW <name> WITH CONTAINER recallguard AS SELECT ...`, queried as `recallguard.<name>`, dropped with `DROP SCHEMASTORE VIEW <name> FROM recallguard`. Re-creating an existing view fails, so `zetaris_register.py` drops first.

**Registration** (`scripts/zetaris_register.py`, idempotent, reads credentials from env, never hardcodes them):
- `CREATE DATASOURCE inventory_pg|pos_pg|regulator_pg ... OPTIONS (jdbcdriver "org.postgresql.Driver", jdbcurl "jdbc:postgresql://rg-<name>:5432/<db>", username, password, fetchsize "1000")`
- then `REGISTER DATASOURCE TABLES FROM <ds>`
- `CREATE LIGHTNING DATABASE supplier_rest`, then `CREATE LIGHTNING REST TABLE deliveries FROM supplier_rest REQUEST(endpoint "http://rg-supplier-api:8000/deliveries", method "get", response_type "json", http_encoding "URLENCODED") HEADER () BODY ()`
- `CREATE SCHEMASTORE CONTAINER recallguard`

**Unified view (core, not a stretch goal):** `recallguard.product_exposure_v`.
- It joins inventory + POS + supplier + regulator.
- It does batch and registration-number normalisation **in Zetaris SQL** (upper-casing, stripping hyphens and spaces).
- Agents query this view first. Its columns are fixed in §7.4.
- **The Critic does not verify against this view.** It runs its own targeted query on the raw source tables (§7.4), so its check is independent of what the Reconciler read.
- **Preferred:** Unified Semantic Layer (`COMPILE USL` → `ACTIVATE USL TABLE`). USL constraints: scalar column types only, the namespace must exist under `lightning.metastore`, and multi-table `COMPILE USL` is sent intact.
- **Fallback, if USL blocks us for more than 2 hours:** `CREATE SCHEMASTORE VIEW`. It is still Zetaris-side and still load-bearing. Record which one we used in `metadata.json`. **Status 23 Oct: the schemastore view is live** (`zetaris_register.py`); USL not tried yet.

**Adapters:**
- `app/adapters/data_adapter.py`: `DataAdapter.query(sql, params=None, limit=1000) -> list[dict]`, plus `name`.
- `app/adapters/zetaris_adapter.py`: the REST implementation above. Timeout 30 s, one retry on 5xx.
- `app/adapters/duckdb_adapter.py`: the sample-mode twin over `data/sample/`, exposing the **same logical table and view names**.
  - Keep agent SQL plain ANSI.
  - Put dialect differences (e.g. string functions) in small helpers, not scattered through agents.
- **Catalogue discovery:** `adapter.catalogue()` returns the same structure from both adapters: `{adapter, statements, tables: [{source, kind: datasource|lightning_db|view, table, columns: [{name, type}]}], skipped}`. Zetaris runs `SHOW DATASOURCES`, `SHOW LIGHTNING DATABASES`, `SHOW TABLES IN <source>` and `DESCRIBE <table>` (built-in sample DBs `NY_TAXI`/`TPCDS_DB` are listed under `skipped`); DuckDB reads `information_schema`. The Planner calls this, never raw `SHOW` SQL, and logs `statements` in its trace event.
- **Parameters:** agents write positional `?` placeholders and pass values in `params`.
  - DuckDB binds them natively.
  - Zetaris REST has no parameter support, so `zetaris_adapter.py` substitutes them in **one tested function**: strings are single-quoted with `'` and `\` escaped (Spark SQL treats backslash as an escape); `int`/`float`/`Decimal` are validated and inlined; `date`/`datetime` become `DATE '...'`/`TIMESTAMP '...'`; `None` becomes `NULL`; any other type raises. The number of `?` must equal `len(params)`. `?` inside string literals in the SQL text is not a placeholder.
  - Agents never build SQL by string formatting values themselves.
- **Selection:** `SAMPLE_MODE=true` or missing Zetaris env → DuckDB. On a Zetaris failure at runtime → DuckDB, logged as `adapter_fallback` with the reason.

### 5.2 Meterless (required): Nightshift provider + engines

**Nightshift is the primary model provider.**

| Item | Value |
|---|---|
| Base URL | `METERLESS_BASE_URL` (e.g. `http://127.0.0.1:8088/v1`; from our container use `host.docker.internal`) |
| Auth | `METERLESS_RUNTIME_TOKEN`, the Runtime token from Nightshift → Setup → Providers → Runtime endpoint |
| Model | `METERLESS_MODEL` (current working value: `openrouter/nvidia/nemotron-3.5-lightning:free`) |
| Headers | `meterless-app: recallguard` on every request; `meterless-scope: user` on chat requests |

Rules:
- `max_tokens >= 800`. Nemotron reasons before answering, and small limits return empty responses (502 `empty_response`).
- Client timeout 180 s, because a model load can be slow.
- **Always record `response.model` in the trace (`served_by`).** Nightshift may serve a different model than the one requested.
- Free-tier lanes are rate-limited, so **batch ambiguous matches into one call** and keep deterministic matching first.

**Engines** (reference specs in `docs/meterless/`; implement minimal services in Python, using the IMPLEMENT prompts from meterless.ai in Cursor Agent):

| Engine | Our use | Minimum services |
|---|---|---|
| **World Model** | shared grounded entities (Product, Batch, Outlet, StockRecord, SaleRecord, Delivery, RegulatorNotice) with provenance; all agents read via its context builder | `WorldStoreService`, `IngestPipelineService` (idempotent, resumable), `ContextBuilderService` |
| **H-MEM** | confirmed alias mappings and critic lessons across runs | `MemoryStoreService`, `MemoryRetrievalService` |
| Markovian | not planned | n/a |

- Engines never call a model directly. They receive the injected `generate` function.
- **World Model is REQUIRED** (it satisfies the Build rule on its own; Meterless's guide recommends it for the Fragmented track). Proof tests:
  - `tests/test_world_model_ingest.py`: re-ingesting the same run creates no duplicates (idempotent), and a run interrupted mid-ingest resumes cleanly.
  - `tests/test_world_model_provenance.py`: every `evidence[]` item in the result resolves to a World Model record with source system and record ID.
  - Also run the engine's conformance suite from `docs/meterless/` if provided.
- **H-MEM is SHOULD** (cuttable after 24 Oct). If built, `tests/test_hmem_warm_start.py` asserts `warm.needs_review < cold.needs_review` on the same input. Commit both real traces under `output_examples/cold_warm/`.
- Storage: SQLite under `state/` (gitignored). `state/seed_memory.jsonl` is small, committed and documented.

### 5.3 NVIDIA: Nemotron models

- Served **through Nightshift** in the normal path. This is required for the NVIDIA DGX Spark award: at least one Nemotron model through Nightshift in a working feature.
- No direct NVIDIA client (team decision, 22 Oct): every model call goes through Nightshift. Nemotron IDs are only the lane model set in Nightshift.
- Embeddings: only if optional RAG is built (§5.4). Use `nvidia/nemotron-3-embed-1b`; otherwise skip embeddings.

**`app/llm/generator.py` contract:**
```
generate(prompt, system_prompt=None, model=None, json_schema=None) -> GenerationResult(text, provider, served_by, latency_ms)
```
- Provider selection: `LLM_PROVIDER` (default `meterless`). Nightshift retries 429/5xx/`empty_response` up to 3 times with backoff. On a transport failure, exhausted retries, no token, `SAMPLE_MODE`, or `LLM_PROVIDER=heuristic`, `generate` returns `provider=heuristic_fallback` with empty text, and the calling agent applies its own deterministic rules.
- With `json_schema`: request JSON, validate with pydantic, and retry once with the validation error.
- `heuristic_fallback` is real deterministic logic (score thresholds, templated critic rules), logged as `provider=heuristic_fallback`. It never returns canned prose.

### 5.4 Reporter: rules table (default), RAG (optional)

- `app/rules/actions.yaml` maps recall degree or level, and cancellation type, to a **severity tier** and a **required action**, with references to the NPRA guideline section.
  - Deterministic, cheap, explainable.
- **Severity ranking:** safety recalls rank outlets by **units sold to customers** (from POS). Administrative deregistrations rank by stock on hand.
- **Customer-contact line:** e.g. "Outlet 7 sold 12 units of batch X to 9 distinct (synthetic) loyalty customers in the last 30 days."
- **Optional RAG** over the guideline PDF is the first thing to cut if behind.

### 5.5 Cursor

- Cursor is the required development environment.
- Project rules in `.cursor/rules/` point to this file.
- Meterless IMPLEMENT prompts run in Cursor Agent.
- Zetaris's own Cursor connection (getting-started repo, `.env.local`) is used for exploring sources.
- Keep 2–3 screenshots of real Cursor usage for the sponsor explanation.

### 5.6 `metadata.json` (required by all four sponsor overviews)

Root file stating where each sponsor sits:
```json
{
  "project": "RecallGuard",
  "track": "Solving Fragmented Intelligence",
  "sponsors": {
    "zetaris":   { "role": "federated SQL over inventory/POS/supplier/regulator sources; unified view product_exposure_v; Critic verification queries", "files": ["app/adapters/zetaris_adapter.py", "scripts/zetaris_register.py"] },
    "meterless": { "role": "Nightshift primary model provider; World Model + H-MEM engines", "files": ["app/llm/generator.py", "app/meterless/"] },
    "nvidia":    { "role": "Nemotron models served via Nightshift for planner/critic/reporter", "models": ["nemotron-3.5-lightning"] },
    "cursor":    { "role": "development environment; Meterless IMPLEMENT prompts run in Cursor Agent", "files": [".cursor/rules/"] }
  }
}
```
Keep it accurate: update `models` to what traces actually show in `served_by`.

---

## 6. Repository layout

```
/
├── AGENTS.md  README.md  metadata.json  run.py  Dockerfile  docker-compose.yml  requirements.txt  .env.example
├── .cursor/rules/
├── app/
│   ├── main.py                 # FastAPI: POST /run, GET /health (bind 0.0.0.0, $PORT)
│   ├── orchestrator.py         # agents, caps, timeouts, result assembly
│   ├── agents/                 # planner.py retriever.py reconciler.py critic.py reporter.py
│   ├── adapters/               # data_adapter.py zetaris_adapter.py duckdb_adapter.py
│   ├── meterless/              # world_model/ hmem/
│   ├── llm/generator.py
│   ├── reconcile/              # normalise.py match.py
│   ├── rules/actions.yaml
│   ├── report/                 # static HTML report renderer
│   ├── schemas.py              # RunRequest, RunResult, Exposure, Evidence, TraceEvent
│   └── tracing.py
├── services/supplier_api/      # tiny FastAPI serving synthetic deliveries
├── scripts/                    # generate_synthetic.py fetch_regulator.py scrape_npra.py load_postgres.py zetaris_register.py evaluate.py
├── data/ sample/ regulator/ docs/ feedback/ ground_truth/ README.md
├── docs/                       # zetaris/ meterless/ (copied sponsor docs)
├── input_examples/ output_examples/ logs/ state/ tests/
```

`docker-compose.yml`:
- services `rg-inventory`, `rg-pos`, `rg-regulator` (postgres:16-alpine, host ports 5433/5434/5435), `rg-supplier-api` and `app`
- attached to the external network `zetaris_default`
- a `sample` profile runs `app` alone with `SAMPLE_MODE=true`

---

## 7. Contracts

### 7.1 `POST /run` request
```json
{ "run_id": "demo-001",
  "input": { "mode": "recall_alert",
             "recall": { "product_name": "...", "reg_no": "MAL...", "batches": ["..."], "date": "YYYY-MM-DD", "degree_level": "..." } },
  "options": { "sample_mode": true, "max_critic_rounds": 2 } }
```
`mode` is `recall_alert` or `daily_scan`. `daily_scan` is bounded to the regulator snapshot.

### 7.2 Result
```json
{ "run_id": "demo-001", "status": "success",
  "output": {
    "summary": "...", "disclaimer": "For pharmacist review. Not a compliance verdict.",
    "exposures": [ {
      "outlet_id": "OUT-03", "product_name": "...", "reg_no": "MAL...", "batch": "...",
      "on_hand_qty": 12, "sold_after_date_qty": 2, "distinct_customers": 9,
      "severity": "high|medium|low", "status": "confirmed|needs_review", "confidence": 0.87,
      "recommended_action": "...", "rule_ref": "actions.yaml#degree-II",
      "critic_check": { "query": "...", "expected": 12, "observed": 12, "passed": true },
      "evidence": [ { "source": "inventory|pos|supplier|regulator", "record_id": "...", "field": "batch", "value": "NSC-24067" } ] } ],
    "unresolved_conflicts": [] },
  "agents": [ { "name": "PlannerAgent", "role": "..." } ],
  "adapter": "zetaris|duckdb_fallback", "providers_used": ["meterless"],
  "trace_id": "trace-demo-001", "log_file": "logs/trace-demo-001.jsonl", "execution_time_seconds": 0.0 }
```
On failure, return `status: "error"` with `error.type`, `error.message` and `error.recoverable`. Never crash silently.

### 7.3 Trace event (JSONL in `logs/trace-<run_id>.jsonl`, echoed to stdout)
```json
{"timestamp":"...","run_id":"...","agent_name":"ConflictCriticAgent","action":"verify_query","input_summary":"...","output_summary":"...","target_agent":"ReconcilerAgent","provider":"meterless|nvidia_direct|heuristic_fallback|null","served_by":"<response.model or null>","sponsor_call":"zetaris|meterless.nightshift|meterless.world_model|meterless.hmem|null","confidence":0.79,"retry_count":0,"status":"needs_revision","duration_ms":0}
```
Summaries are at most 200 characters. No secrets and no full documents in traces.

### 7.4 Data contract: `recallguard.product_exposure_v` (agreed A ↔ B, 23 Oct)

One row per internal record from inventory, POS or supplier. Identical names and types in Zetaris and DuckDB.

| Column | Type | Meaning |
|---|---|---|
| `source` | text | `inventory`, `pos` or `supplier` |
| `record_id` | text | primary key in the source system; with `source` it is the provenance key |
| `outlet_id` | text | e.g. `OUT-03`; NULL only for a delivery not yet assigned to an outlet |
| `product_name` | text | raw, as the source spells it |
| `reg_no` | text | raw MAL number; NULL where the source has none (POS) |
| `batch` | text | raw batch, as the source spells it |
| `reg_no_norm` | text | upper-case, alphanumerics only |
| `batch_norm` | text | upper-case, alphanumerics only |
| `qty` | integer | units; stock = on hand, sale = sold, delivery = received, transfer = moved (negative at the sending outlet) |
| `event_type` | text | `stock`, `sale`, `delivery` or `transfer` |
| `event_date` | date | snapshot date for stock, otherwise the event date |
| `customer_id` | text | hashed **synthetic** loyalty ID on `sale` rows, NULL otherwise |

- Agents select these columns by name, never `SELECT *`, so adding columns later is not breaking. Renaming or removing one needs both A and B.
- The view does not include regulator rows. Regulator data is read from `regulator_pg.*` tables directly.
- **Raw tables for the Critic** (agreed A ↔ B, 23 Oct; `TODO(verify)` the exact names Zetaris gives them after `REGISTER DATASOURCE TABLES`, and DuckDB mirrors whatever Zetaris shows). No shared key across systems by design: link on `outlet_id` + normalised batch; POS has `sku` but no `reg_no`.

| Table | Columns |
|---|---|
| `inventory_pg.stock` | `stock_id`, `outlet_id`, `product_name`, `reg_no` (NULL possible), `batch` (UPPERCASE), `qty_on_hand` int, `snapshot_date` date |
| `inventory_pg.transfers` | `transfer_id` (shared by both legs), `leg` `out`/`in`, `outlet_id`, `counterparty_outlet_id`, `product_name`, `reg_no`, `batch`, `qty` int (positive), `transfer_date` date. A missing leg is a conflict (`needs_review`); transfers never change on-hand qty. |
| `pos_pg.sales` | `sale_id`, `outlet_id`, `sku`, `product_name`, `batch` (lowercase), `qty` int, `sold_at` timestamp, `loyalty_id` (hashed synthetic, NULL for walk-ins) |
| `supplier_rest.deliveries` | `delivery_id`, `supplier_name`, `supplier_licence_no` (NULL = not licensed), `outlet_id` (NULL = unassigned), `supplier_product_name`, `reg_no`, `batch` (hyphenated), `qty` int, `delivered_on` date |
| `regulator_pg.npra_recalls` | see `data/README.md`; `batches` is `\|`-separated |
| `regulator_pg.pharmaceutical_*` | the four data.gov.my files, columns as published |

- **Adapter selection:** `app.adapters.factory.get_adapter(sample_mode=None, data_dir=None)`. `adapter.result_name` is the `RunResult.adapter` value; `adapter.fallback_reason` feeds the `adapter_fallback` trace event.
- **Answer key** (`data/ground_truth/exposures.json`, read only by `evaluate.py`): `exposures[]` keyed by `recall_id` + `outlet_id` + `batch_norm`, with `on_hand_qty`, `sold_after_date_qty` (sales on or after the recall date), `distinct_customers`, `expected_status`, `conflicts[]`, `evidence[]` (`source`, `record_id`); `unassigned[]` (deliveries with no outlet, expected `needs_review`); `decoys[]` (records of a recalled product with a non-affected batch: flagging them is a false positive). `expected_status` is `needs_review` when the conflicts include `batch_typo`, `one_sided_transfer` or `delivered_not_in_inventory`.
- **Tuning data:** `data/tuning/seed7/` has the same layout with its own `ground_truth/`. Point the DuckDB adapter at it with `data_dir` or `RG_DATA_DIR`.

---

### 7.5 Human verdicts: `data/feedback/decisions.jsonl` (agreed 23 Oct)

One JSON object per line, written by a person **between runs**, validated by `app.schemas.HumanVerdict` and `tests/test_decisions_file.py`. How-to: `data/feedback/README.md`.

```json
{"field": "batch", "alias": "5o34698", "canonical": "5034698", "verdict": "same", "decided_by": "ethan", "decided_at": "2026-10-24T10:00:00Z", "run_id": "demo-001", "note": "POS typo"}
```

- `field`: `batch` | `product_name` | `reg_no`. `verdict`: `same` | `different`.
- H-MEM loads it with `source="human_verdict"` and learns **only `verdict == "same"`** lines as aliases.
- The Critic still handles everything it can verify; this file covers only `needs_review` items from a real run (Rules 2 and 11).

---

## 8. Environment (`.env.example`, placeholders only)
```
METERLESS_BASE_URL=http://127.0.0.1:8088/v1
METERLESS_RUNTIME_TOKEN=your-runtime-token
METERLESS_MODEL=openrouter/nvidia/nemotron-3.5-lightning:free
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_API_KEY=your-nvidia-key
MODEL_REASONING=nvidia/nemotron-3.5-super-vl-120b-a12b
MODEL_FAST=nvidia/nemotron-3.5-lightning-30b-a3b
ZETARIS_REST_URL=http://localhost:8888/api/v1.0
ZETARIS_API_KEY=your-zetaris-api-key
ZETARIS_ORG_ID=1
PG_READER_USER=zetaris_reader
PG_READER_PASSWORD=change-me
PG_ADMIN_PASSWORD=change-me
SAMPLE_MODE=false
MAX_CRITIC_ROUNDS=2
LOG_LEVEL=INFO
PORT=8000
```

## 9. Conventions and commands

**Conventions:**
- Python 3.11, FastAPI, pydantic v2, httpx (explicit timeouts), openai SDK, duckdb, psycopg, rapidfuzz, pyarrow, ruff, pytest.
- Add other dependencies only with a reason.
- Install dependencies at Docker build time only; nothing installs at runtime.

**Commands:**
```bash
docker compose up -d rg-inventory rg-pos rg-regulator rg-supplier-api   # needs Zetaris stack up first (network zetaris_default)
python scripts/fetch_regulator.py && python scripts/scrape_npra.py
python scripts/generate_synthetic.py --seed 42
python scripts/load_postgres.py
python scripts/zetaris_register.py            # idempotent
python run.py --input input_examples/example_1.json
python run.py --serve
python scripts/evaluate.py --run logs/trace-<id>.jsonl
pytest -q
SAMPLE_MODE=true python run.py --input input_examples/example_1.json    # must pass with an empty .env
```

## 10. Definition of done (per feature)

- Works in `SAMPLE_MODE=true` and in live mode.
- Emits trace events for every agent action and sponsor call.
- Has a timeout or cap where it loops or calls out.
- Has at least one test.
- README and `metadata.json` are updated when behaviour, commands or env change.

## 11. Status of questions

**Resolved:**
- Zetaris runs locally in Docker (no hosted instance) and is reached over REST.
- The Meterless runtime token **is** required.
- Working Nemotron IDs are in §5.3.
- Judges run `SAMPLE_MODE`; the live Zetaris + Nightshift run is shown in the demo video.

**Open:**
- How to put NVIDIA-key models in a Nightshift lane. Ask at the Build workshop.
- Whether Nightshift on Windows requires an NVIDIA GPU for cloud-only lanes. This decides which teammate's machine runs live demos.
- Whether `ACTIVATE USL TABLE` works over JDBC datasource tables on our instance. Test on day 2; fall back to a schemastore view.

## 12. Schedule and cut list

| Day (UTC) | Goal |
|---|---|
| 22 Oct | Interfaces committed (`schemas.py`, `DataAdapter`, `generate`); compose + 3 DBs + supplier API; regulator fetch; synthetic generator; Zetaris registration; DuckDB twin; Nightshift-first generator; Planner → Retriever → Reporter skeleton running end-to-end on one `recall_alert` |
| 23–24 Oct | Reconciler, Critic with Zetaris verification queries + revision loop, World Model, H-MEM, catalogue discovery |
| 25 Oct | Unified view, cold/warm test + traces, `evaluate.py`, HTML report, 3 real runs in `output_examples/`; **full clean-clone validation incl. empty `.env`** |
| 26 Oct | Feature freeze. README, `metadata.json`, sponsor explanation, deck, demo video |
| 27 Oct | Submit by 12:00 UTC; fixes only after that |

**Cut in this order if behind:**
1. Optional RAG.
2. `daily_scan` mode.
3. Live NPRA scraping (keep the committed snapshot).
4. USL (keep the schemastore view).
5. H-MEM and the cold/warm demo.

**Never cut:**
- Meterless provider with real traced calls
- World Model and its tests
- Critic verification query
- sample mode
- traces
- `metadata.json`

## 13. Pre-existing work

Code committed before 22 Oct 00:00 UTC is not eligible unless declared. This file and environment setup (Docker, Zetaris install, accounts) are not product code. If any script or data snapshot was prepared earlier, declare it in the submission form.