"""Pipeline for one run: Retriever -> Reconciler -> aggregate -> Critic -> Reporter.
C's runner calls `run(request)`; it turns any exception into an error RunResult.

Only recall_alert is built. daily_scan needs a Planner that scans the regulator
catalogue (shortcut: raises until that exists; upgrade when the Planner exists).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from app.adapters import DataAdapter
from app.agents.critic import ConflictCriticAgent
from app.agents.reconciler import ReconcilerAgent
from app.agents.reporter import ReporterAgent
from app.agents.retriever import RetrieverAgent
from app.llm import GenerationResult, generate
from app.meterless.hmem import MemoryRetrievalService, MemoryStoreService
from app.meterless.world_model import IngestPipelineService, WorldStoreService
from app.reconcile.aggregate import build_drafts
from app.schemas import AgentInfo, RunRequest, RunResult, TraceEvent
from app.tracing import Tracer

AGENTS = [
    AgentInfo(name="RetrieverAgent", role="reads the data layer and ingests into the World Model"),
    AgentInfo(name="ReconcilerAgent", role="matches records to the recall, consulting H-MEM"),
    AgentInfo(name="ConflictCriticAgent", role="re-checks each exposure against the raw tables"),
    AgentInfo(name="ReporterAgent", role="applies the rules table and ranks the action list"),
]


def default_adapter(sample_mode: bool = False) -> DataAdapter:
    from app.adapters.factory import get_adapter  # owner: A

    return get_adapter(sample_mode=True if sample_mode else None)


def run(request: RunRequest, adapter: DataAdapter | None = None, state_dir: str | None = None) -> RunResult:
    if request.input.mode != "recall_alert" or request.input.recall is None:
        raise NotImplementedError("only recall_alert runs with a recall are built; daily_scan needs the Planner")
    t0 = time.monotonic()
    recall, run_id = request.input.recall, request.run_id
    adapter = adapter or default_adapter(request.options.sample_mode)
    state = Path(state_dir or os.getenv("STATE_DIR", "state"))
    state.mkdir(parents=True, exist_ok=True)
    log_dir = os.getenv("LOG_DIR", "logs")
    tracer = Tracer(run_id, log_dir)

    providers: set[str] = set()

    def gen(*args, **kwargs) -> GenerationResult:
        if request.options.sample_mode:  # judges' path: no model calls
            res = GenerationResult(text="", provider="heuristic_fallback", served_by=None, latency_ms=0)
        else:
            res = generate(*args, **kwargs)
        providers.add(res.provider)
        return res

    # The World Model is per-run evidence; H-MEM persists across runs (that is the point of the warm start).
    world = IngestPipelineService(WorldStoreService(str(state / f"world-{run_id}.db")))
    hmem = MemoryStoreService(str(state / "hmem.db"))

    rows = RetrieverAgent(adapter, world, run_id, tracer.emit).retrieve(recall)
    candidates = ReconcilerAgent(MemoryRetrievalService(hmem), run_id, gen, tracer.emit).reconcile(recall, rows)
    drafts = ConflictCriticAgent(adapter, hmem, run_id, tracer.emit).review(recall, build_drafts(recall, candidates))
    output = ReporterAgent(run_id, gen, tracer.emit).report(recall, drafts)

    if getattr(adapter, "fallback_reason", None):
        tracer.emit(TraceEvent(run_id=run_id, agent_name="Orchestrator", action="adapter_fallback", output_summary=str(adapter.fallback_reason)[:200], status="degraded"))
    return RunResult(
        run_id=run_id, status="success", output=output, agents=AGENTS, adapter=getattr(adapter, "result_name", adapter.name),
        providers_used=sorted(providers), trace_id=f"trace-{run_id}", log_file=str(tracer.path),
        execution_time_seconds=max(round(time.monotonic() - t0, 3), 0.001),
    )
