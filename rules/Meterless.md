## Meterless in RecallGuard

Two separate parts. Do not mix them up.
Repo for engine: https://github.com/Meterless/Meterless/tree/main/engines
**1. Engines (open source, no API key). Implement in our own Python code.**
- Engines are implementation specs (AGENTS.md + docs + runnable TypeScript reference + conformance suite), not a pip package.
- World Model -> app/meterless/world_model/: shared, grounded entities (Product, Batch, Outlet, StockRecord, SaleRecord, Delivery, RegulatorNotice) with provenance. Services: WorldStoreService, IngestPipelineService (idempotent, resumable), ContextBuilderService. All agents read facts through the context builder.
- H-MEM -> app/meterless/hmem/: durable memory across runs (confirmed alias mappings, critic lessons). Services: MemoryStoreService, MemoryRetrievalService. Skip dreaming/sleep. Store an alias only when the Critic's Zetaris check passed or a human verdict in data/feedback/decisions.jsonl confirms it. The Reconciler consults H-MEM before any LLM/heuristic call.
- How to port: the references live outside app/ (npx degit meterless/meterless/engines/<name> reference/<name>; do not commit node_modules). Or you can use GIT clone. Read the engine's AGENTS.md and its tests, then write a minimal Python version with SQLite under state/. Match the service names and contracts from the spec. Do not invent API behaviour; if the spec is silent, leave TODO(verify) and ask.
- Proof: tests/test_hmem_warm_start.py asserts warm.needs_review < cold.needs_review on the same input. World Model test: ingesting the same records twice yields zero duplicates.
- Engines never call a model directly; they receive the injected generate() function.

Repo for nightshift: https://github.com/Meterless/Meterless/tree/main
**2. Nightshift (local AI runtime). Our model provider, called by app/llm/generator.py.**
- Nightshift is a local gateway (default http://127.0.0.1:8088/v1) that speaks the OpenAI chat format and forwards to the provider/model set in its lanes (free Nemotron via OpenRouter). It is NOT part of the engines and has no code in app/meterless/.
- Our app is the client: base URL METERLESS_BASE_URL, token METERLESS_RUNTIME_TOKEN, model METERLESS_MODEL, headers meterless-app: recallguard and meterless-scope: user.
- generate() order: Nightshift -> (transport failure) NVIDIA direct -> (no credentials / SAMPLE_MODE) heuristic_fallback. Retry 429/5xx/empty_response up to 3 times with backoff. max_tokens >= 800.
- Always trace provider and served_by (response.model). Never commit or log the token.
