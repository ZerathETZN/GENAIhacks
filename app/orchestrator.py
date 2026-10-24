"""Pipeline for one run: Planner -> Retriever -> Reconciler -> aggregate -> Critic -> Reporter.
C's runner calls `run(request)`; it turns any exception into an error RunResult.

recall_alert runs the pipeline for the given recall. daily_scan (AGENTS.md §7.1, "bounded to the regulator
snapshot") runs it for every snapshot recall whose product the chain stocks, newest first, capped at
SCAN_LIMIT, and merges the results into one ranked list. It is the same POST /run, not a separate service.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from app.adapters import DataAdapter
from app.agents.critic import ConflictCriticAgent
from app.agents.planner import PlannerAgent
from app.agents.reconciler import ReconcilerAgent
from app.agents.reporter import ReporterAgent
from app.agents.retriever import RetrieverAgent
from app.llm import GenerationResult, generate
from app.meterless.hmem import MemoryRetrievalService, MemoryStoreService
from app.meterless.world_model import IngestPipelineService, WorldStoreService, norm
from app.reconcile.aggregate import build_drafts
from app.schemas import AgentInfo, Recall, RunOutput, RunRequest, RunResult, TraceEvent
from app.tracing import Tracer

SCAN_LIMIT = int(os.getenv("SCAN_LIMIT", "5"))  # shortcut: recalls per scan, newest first; raise it to cover the whole snapshot
SCAN_BUDGET_S = float(os.getenv("SCAN_BUDGET_S", "300"))  # stop starting new recalls after this; the rest are reported as skipped
MODEL_FAILS_TO_TRIP = 2  # consecutive heuristic fallbacks before the run stops calling the model
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

AGENTS = [
    AgentInfo(name="PlannerAgent", role="discovers the data catalogue and checks the pipeline can run on it"),
    AgentInfo(name="RetrieverAgent", role="reads the data layer and ingests into the World Model"),
    AgentInfo(name="ReconcilerAgent", role="matches records to the recall, consulting H-MEM"),
    AgentInfo(name="ConflictCriticAgent", role="re-checks each exposure against the raw tables"),
    AgentInfo(name="ReporterAgent", role="applies the rules table and ranks the action list"),
]


def default_adapter(sample_mode: bool = False) -> DataAdapter:
    from app.adapters.factory import get_adapter  # owner: A

    return get_adapter(sample_mode=True if sample_mode else None)


def snapshot_recalls(adapter: DataAdapter, limit: int) -> list[tuple[str, Recall]]:
    """Newest snapshot recalls whose reg_no the chain holds (in stock, or delivered)."""
    stocked = {r["reg_no_norm"] for r in adapter.query(
        "SELECT DISTINCT reg_no_norm FROM recallguard.product_exposure_v WHERE reg_no_norm IS NOT NULL", limit=100000)}
    rows = adapter.query(
        "SELECT recall_id, recall_date, product_name, reg_no, batches, all_batches, degree, level "
        "FROM regulator_pg.npra_recalls ORDER BY recall_date DESC", limit=10000)
    out = []
    for r in rows:
        if norm(r["reg_no"] or "") not in stocked:
            continue
        # Zetaris may return booleans and NULLs as strings; all_batches means "every batch", i.e. no batch list
        every = str(r["all_batches"]).strip().lower() == "true"
        batches = [] if every else [b for b in str(r["batches"] or "").split("|") if b and b.lower() != "nan"]
        level = " ".join(str(x) for x in (r["degree"], r["level"]) if x and str(x).lower() != "nan") or None
        out.append((r["recall_id"], Recall(product_name=r["product_name"], reg_no=r["reg_no"], batches=batches,
                                           date=str(r["recall_date"])[:10], degree_level=level)))
    return out[:limit]


def run(request: RunRequest, adapter: DataAdapter | None = None, state_dir: str | None = None) -> RunResult:
    mode, recall = request.input.mode, request.input.recall
    if mode == "recall_alert" and recall is None:
        raise ValueError("mode 'recall_alert' needs input.recall")
    t0 = time.monotonic()
    run_id = request.run_id
    adapter = adapter or default_adapter(request.options.sample_mode)
    state = Path(state_dir or os.getenv("STATE_DIR", "state"))
    state.mkdir(parents=True, exist_ok=True)
    log_dir = os.getenv("LOG_DIR", "logs")
    tracer = Tracer(run_id, log_dir)

    providers: set[str] = set()
    fails = 0  # consecutive failed model calls; a dead gateway otherwise costs the full retry sequence on every call

    def gen(*args, **kwargs) -> GenerationResult:
        nonlocal fails
        if request.options.sample_mode or fails >= MODEL_FAILS_TO_TRIP:  # judges' path, or model given up for this run
            providers.add("heuristic_fallback")
            return GenerationResult(text="", provider="heuristic_fallback", served_by=None, latency_ms=0)
        res = generate(*args, **kwargs)
        providers.add(res.provider)
        fails = fails + 1 if res.provider == "heuristic_fallback" else 0
        if fails == MODEL_FAILS_TO_TRIP:
            tracer.emit(TraceEvent(run_id=run_id, agent_name="Orchestrator", action="model_unavailable", status="degraded",
                                   output_summary=f"{fails} model calls in a row fell back; deterministic rules for the rest of this run"))
        return res

    # The World Model is per-run evidence; H-MEM persists across runs (that is the point of the warm start).
    world = IngestPipelineService(WorldStoreService(str(state / f"world-{run_id}.db")))
    hmem = MemoryStoreService(str(state / "hmem.db"))
    # Pharmacist verdicts from earlier runs (AGENTS.md §7.5) are loaded before matching, so the warm run uses them.
    hmem.load_jsonl(os.getenv("DECISIONS_FILE", "data/feedback/decisions.jsonl"), "human_verdict", run_id)

    def process(rc: Recall, summarise: bool) -> RunOutput:
        rows = RetrieverAgent(adapter, world, run_id, tracer.emit).retrieve(rc)
        candidates = ReconcilerAgent(MemoryRetrievalService(hmem), run_id, gen, tracer.emit).reconcile(rc, rows)
        drafts = ConflictCriticAgent(adapter, hmem, run_id, tracer.emit).review(rc, build_drafts(rc, candidates))
        return ReporterAgent(run_id, gen, tracer.emit).report(rc, drafts, summarise)

    PlannerAgent(adapter, run_id, tracer.emit).plan()
    output = process(recall, True) if mode == "recall_alert" else _scan(adapter, run_id, tracer, process, gen)

    if getattr(adapter, "fallback_reason", None):
        tracer.emit(TraceEvent(run_id=run_id, agent_name="Orchestrator", action="adapter_fallback", output_summary=str(adapter.fallback_reason)[:200], status="degraded"))
    return RunResult(
        run_id=run_id, status="success", output=output, agents=AGENTS, adapter=getattr(adapter, "result_name", adapter.name),
        providers_used=sorted(providers), trace_id=f"trace-{run_id}", log_file=str(tracer.path),
        execution_time_seconds=max(round(time.monotonic() - t0, 3), 0.001),
    )


def _scan(adapter: DataAdapter, run_id: str, tracer: Tracer, process, gen) -> RunOutput:
    t0 = time.monotonic()
    recalls = snapshot_recalls(adapter, SCAN_LIMIT)
    tracer.emit(TraceEvent(run_id=run_id, agent_name="Orchestrator", action="daily_scan_select", input_summary=f"limit={SCAN_LIMIT}",
                           output_summary=f"{len(recalls)} snapshot recalls match stocked products", duration_ms=int((time.monotonic() - t0) * 1000)))
    exposures, conflicts = [], []
    for rid, rc in recalls:
        if time.monotonic() - t0 > SCAN_BUDGET_S:
            tracer.emit(TraceEvent(run_id=run_id, agent_name="Orchestrator", action="scan_recall_skipped", input_summary=rid,
                                   output_summary=f"time budget {SCAN_BUDGET_S:.0f}s used up", status="degraded"))
            conflicts.append({"recall_id": rid, "error": f"skipped: scan time budget of {SCAN_BUDGET_S:.0f}s used up; rerun to cover it"})
            continue
        try:
            out = process(rc, False)
        except Exception as exc:  # one bad recall must not hide the others; it is reported, never dropped silently
            tracer.emit(TraceEvent(run_id=run_id, agent_name="Orchestrator", action="scan_recall_failed", input_summary=rid,
                                   output_summary=f"{type(exc).__name__}: {exc}"[:200], status="error"))
            conflicts.append({"recall_id": rid, "error": f"{type(exc).__name__}: {exc}"[:300]})
            continue
        for e in out.exposures:
            e.recall_id = rid
        exposures += out.exposures
        conflicts += [{"recall_id": rid, **c} for c in out.unresolved_conflicts]
    exposures.sort(key=lambda e: (_SEVERITY_ORDER[e.severity], -e.sold_after_date_qty, -e.on_hand_qty))
    facts = (f"Daily scan: {len(recalls)} snapshot recalls match products the chain stocks; {len(exposures)} outlet exposures "
             f"({sum(e.severity == 'high' for e in exposures)} high), {sum(e.on_hand_qty for e in exposures)} units on hand, "
             f"{sum(e.sold_after_date_qty for e in exposures)} sold since each recall, {len(conflicts)} items need review.")
    res = gen(f"Write a two-sentence summary for a pharmacist. Use only these facts, add nothing:\n{facts}",
              system_prompt="You summarise recall exposure. Do not give legal or compliance conclusions.")
    tracer.emit(TraceEvent(run_id=run_id, agent_name="ReporterAgent", action="summarise", input_summary=facts[:200], output_summary=(res.text or "templated")[:200],
                           provider=res.provider, served_by=res.served_by, sponsor_call="meterless.nightshift" if res.provider == "meterless" else None))
    return RunOutput(summary=res.text.strip() or facts, exposures=exposures, unresolved_conflicts=conflicts)
