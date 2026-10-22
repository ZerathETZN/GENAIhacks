"""Shared contracts (AGENTS.md §7). Change these only with the whole team's agreement."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

DISCLAIMER = "For pharmacist review. Not a compliance verdict."

Mode = Literal["recall_alert", "daily_scan"]
Source = Literal["inventory", "pos", "supplier", "regulator"]
Severity = Literal["high", "medium", "low"]
ExposureStatus = Literal["confirmed", "needs_review"]
Provider = Literal["meterless", "nvidia_direct", "heuristic_fallback"]
SponsorCall = Literal[
    "zetaris",
    "meterless.nightshift",
    "meterless.world_model",
    "meterless.hmem",
]


# ---------- 7.1 request ----------


class Recall(BaseModel):
    product_name: str
    reg_no: str
    batches: list[str] = Field(default_factory=list)
    date: str  # YYYY-MM-DD
    degree_level: str | None = None


class RunInput(BaseModel):
    mode: Mode
    recall: Recall | None = None  # required for recall_alert, absent for daily_scan


class RunOptions(BaseModel):
    sample_mode: bool = False
    max_critic_rounds: int = Field(default=2, ge=0, le=5)


class RunRequest(BaseModel):
    run_id: str
    input: RunInput
    options: RunOptions = Field(default_factory=RunOptions)


# ---------- 7.2 result ----------


class Evidence(BaseModel):
    source: Source
    record_id: str
    field: str
    value: Any


class CriticCheck(BaseModel):
    query: str
    expected: Any
    observed: Any
    passed: bool


class Exposure(BaseModel):
    outlet_id: str
    product_name: str
    reg_no: str | None = None
    batch: str
    on_hand_qty: int = 0
    sold_after_date_qty: int = 0
    distinct_customers: int = 0
    severity: Severity
    status: ExposureStatus
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_action: str
    rule_ref: str
    critic_check: CriticCheck | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class RunOutput(BaseModel):
    summary: str
    disclaimer: str = DISCLAIMER
    exposures: list[Exposure] = Field(default_factory=list)
    unresolved_conflicts: list[dict[str, Any]] = Field(default_factory=list)


class AgentInfo(BaseModel):
    name: str
    role: str


class RunError(BaseModel):
    type: str
    message: str
    recoverable: bool


class RunResult(BaseModel):
    run_id: str
    status: Literal["success", "error"]
    output: RunOutput | None = None
    error: RunError | None = None
    agents: list[AgentInfo] = Field(default_factory=list)
    adapter: Literal["zetaris", "duckdb", "duckdb_fallback"] | None = None
    providers_used: list[Provider] = Field(default_factory=list)
    trace_id: str
    log_file: str
    execution_time_seconds: float = 0.0


# ---------- 7.3 trace event ----------


class TraceEvent(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    run_id: str
    agent_name: str
    action: str
    input_summary: str = Field(default="", max_length=200)
    output_summary: str = Field(default="", max_length=200)
    target_agent: str | None = None
    provider: Provider | None = None
    served_by: str | None = None
    sponsor_call: SponsorCall | None = None
    confidence: float | None = None
    retry_count: int = 0
    status: str = "ok"
    duration_ms: int = 0
