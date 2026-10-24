"""Pure helpers for the Streamlit UI (testable without Streamlit). Owner: C."""

from __future__ import annotations

from collections import Counter
from itertools import pairwise
from typing import Any

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
SEVERITY_BADGE = {"high": "🔴 High", "medium": "🟠 Medium", "low": "🟢 Low"}
STATUS_BADGE = {"confirmed": "✅ Confirmed", "needs_review": "🟡 Needs review"}
REVISION_STATUSES = {"needs_revision", "rejected", "revise", "revision_requested"}
DATA_CAVEAT = (
    "Regulator data comes from data.gov.my (CC BY 4.0; it should not be used as the basis for legal action) and NPRA's "
    "public recall notices. Internal inventory, POS and supplier data in this demo is synthetic."
)


def rank_exposures(exposures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the Reporter's ranking (rules table: units sold for safety recalls, stock on hand for administrative
    ones). Only group by severity, which is a stable sort, so the order inside each tier is the agents' order."""
    return sorted(exposures, key=lambda e: SEVERITY_ORDER.get(e.get("severity", "low"), 3))


def action_rows(exposures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for rank, e in enumerate(rank_exposures(exposures), start=1):
        rows.append(
            {
                "#": rank,
                **({"Recall": e.get("recall_id")} if any(x.get("recall_id") for x in exposures) else {}),
                "Severity": SEVERITY_BADGE.get(e.get("severity"), e.get("severity")),
                "Status": STATUS_BADGE.get(e.get("status"), e.get("status")),
                "Outlet": e.get("outlet_id"),
                "Product": e.get("product_name"),
                "Batch": e.get("batch"),
                "On hand": e.get("on_hand_qty", 0),
                "Sold after date": e.get("sold_after_date_qty", 0),
                "Customers": e.get("distinct_customers", 0),
                "Confidence": e.get("confidence"),
                "Action": e.get("recommended_action"),
            }
        )
    return rows


def contact_line(e: dict[str, Any]) -> str | None:
    sold, customers = int(e.get("sold_after_date_qty") or 0), int(e.get("distinct_customers") or 0)
    if sold <= 0:
        return None
    who = f" to {customers} distinct (synthetic) loyalty customer{'s' if customers != 1 else ''}" if customers else ""
    return f"{e.get('outlet_id')} sold {sold} unit{'s' if sold != 1 else ''} of batch {e.get('batch')}{who} after the notice date."


def counts(exposures: list[dict[str, Any]]) -> dict[str, int]:
    c = Counter(e.get("status") for e in exposures)
    return {
        "exposures": len(exposures),
        "confirmed": c.get("confirmed", 0),
        "needs_review": c.get("needs_review", 0),
        "outlets": len({e.get("outlet_id") for e in exposures}),
        "high": sum(1 for e in exposures if e.get("severity") == "high"),
    }


def trace_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for ev in events:
        target = ev.get("target_agent")
        rows.append(
            {
                "Time": (ev.get("timestamp") or "")[11:19],
                "Agent": ev.get("agent_name"),
                "Action": ev.get("action"),
                "→": target or "",
                "Status": ev.get("status"),
                "Sponsor": ev.get("sponsor_call") or "",
                "Served by": ev.get("served_by") or "",
                "Output": ev.get("output_summary") or "",
                "ms": ev.get("duration_ms", 0),
            }
        )
    return rows


def _is_critic_rejection(ev: dict[str, Any]) -> bool:
    if "critic" not in (ev.get("agent_name") or "").lower():
        return False
    return (ev.get("status") or "") in REVISION_STATUSES or "passed=False" in (ev.get("output_summary") or "")


def _is_escalation(ev: dict[str, Any]) -> bool:
    return (ev.get("status") or "") == "needs_review" or "status=needs_review" in (ev.get("output_summary") or "")


def pipeline(events: list[dict[str, Any]]) -> list[str]:
    """Agents in the order they first acted, e.g. Planner -> Retriever -> Reconciler -> Critic -> Reporter."""
    seen: list[str] = []
    for ev in events:
        a = ev.get("agent_name")
        if a and a != "Orchestrator" and a not in seen:
            seen.append(a)
    return seen


def trace_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Evidence judges look for: handoffs, Critic checks and rejections, escalations, sponsor calls, models."""
    agents_seq = [e.get("agent_name") for e in events if e.get("agent_name") and e.get("agent_name") != "Orchestrator"]
    explicit = sum(1 for e in events if e.get("target_agent"))
    transitions = sum(1 for a, b in pairwise(agents_seq) if a != b)
    return {
        "events": len(events),
        "agents": pipeline(events),
        "handoffs": max(explicit, transitions),
        "critic_checks": sum(1 for e in events if "critic" in (e.get("agent_name") or "").lower()),
        "critic_revisions": sum(1 for e in events if _is_critic_rejection(e)),
        "needs_review": sum(1 for e in events if _is_escalation(e)),
        "sponsor_calls": dict(Counter(e.get("sponsor_call") for e in events if e.get("sponsor_call"))),
        "served_by": sorted({e.get("served_by") for e in events if e.get("served_by")}),
        "fallbacks": sorted({e.get("action") for e in events
                             if "fallback" in (e.get("action") or "") or (e.get("status") or "") == "degraded"}),
    }


def review_items(conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten unresolved_conflicts[].doubts into questions a pharmacist can answer (AGENTS.md §7.5)."""
    items = []
    for c in conflicts:
        for d in c.get("doubts") or []:
            items.append({**d, "outlet_id": c.get("outlet_id"), "recall_id": c.get("recall_id")})
    return items


def verdict_line(doubt: dict[str, Any], verdict: str, decided_by: str, decided_at: str, run_id: str,
                 note: str = "") -> dict[str, Any]:
    """One decisions.jsonl line in the HumanVerdict shape. Written by a person between runs, never by an agent."""
    return {"field": doubt["field"], "alias": doubt["alias"], "canonical": doubt["canonical"], "verdict": verdict,
            "decided_by": decided_by, "decided_at": decided_at, "run_id": run_id, "note": note}
