"""Deterministic matching of one internal record against a recall (AGENTS.md §3, ReconcilerAgent).

Records are neutral dicts: {source, record_id, product_name, reg_no, batch, ...};
the Retriever maps each system's columns onto these keys.

Batch rule: a batch must match exactly after normalisation (or via a verified
H-MEM alias). Batches like 2311021 / 2311022 are different lots, so a fuzzy
batch never auto-matches; a near-miss is flagged for review instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz, utils

from app.meterless.hmem import MemoryRetrievalService
from app.meterless.world_model import norm
from app.schemas import Evidence, Recall

ID_STRONG = 0.9  # identity >= this is a match
ID_WEAK = 0.6  # identity below this is not the same product
BATCH_NEAR = 85  # fuzz.ratio at or above this (but not equal) is a near-miss


@dataclass
class Match:
    label: str  # match | ambiguous | near_miss | no_match
    identity: float
    via: str  # reg_no | hmem | name_fuzzy
    reasons: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)


def _batch_state(recall: Recall, rec: dict[str, Any], hmem: MemoryRetrievalService) -> str:
    if not recall.batches:  # administrative deregistration: every batch is affected
        return "any"
    got = norm(rec.get("batch") or "")
    if not got:
        return "none"
    for b in recall.batches:
        if got == norm(b) or hmem.same("batch", rec["batch"], b):
            return "exact"
    near = max(fuzz.ratio(got, norm(b)) for b in recall.batches)
    return "near" if near >= BATCH_NEAR else "none"


def _identity(recall: Recall, rec: dict[str, Any], hmem: MemoryRetrievalService) -> tuple[float, str]:
    if rec.get("reg_no"):
        return (1.0, "reg_no") if norm(rec["reg_no"]) == norm(recall.reg_no) else (0.0, "reg_no")
    name = rec.get("product_name") or ""
    if hmem.same("product_name", name, recall.product_name):
        return 0.98, "hmem"
    score = fuzz.token_set_ratio(name, recall.product_name, processor=utils.default_process) / 100
    return score, "name_fuzzy"


def classify(recall: Recall, rec: dict[str, Any], hmem: MemoryRetrievalService) -> Match:
    batch = _batch_state(recall, rec, hmem)
    identity, via = _identity(recall, rec, hmem)
    m = Match("no_match", identity, via, [f"batch={batch}", f"identity={identity:.2f} via {via}"])
    if batch == "none" or identity < ID_WEAK:
        return m
    if batch == "near":
        m.label = "near_miss" if identity >= ID_STRONG else "no_match"
    else:
        m.label = "match" if identity >= ID_STRONG else "ambiguous"
    if m.label != "no_match":
        src, rid = rec["source"], rec["record_id"]
        m.evidence = [Evidence(source=src, record_id=rid, field=f, value=rec[f]) for f in ("batch", "reg_no", "product_name") if rec.get(f)]
    return m
