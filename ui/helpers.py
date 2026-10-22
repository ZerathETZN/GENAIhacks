"""Pure helpers for the Streamlit UI (testable without Streamlit). Owner: C."""

from __future__ import annotations

from collections import Counter
from typing import Any

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
SEVERITY_BADGE = {"high": "🔴 High", "medium": "🟠 Medium", "low": "🟢 Low"}
STATUS_BADGE = {"confirmed": "✅ Confirmed", "needs_review": "🟡 Needs review"}
REVISION_STATUSES = {"needs_revision", "rejected", "revise", "revision_requested"}
DATA_CAVEAT = (
    "Regulator data: data.gov.my / NPRA open data (CC BY 4.0). It should not be used as the basis for legal action. "
    "Internal inventory, POS and supplier data in this demo is synthetic."
)


def rank_exposures(exposures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Severity first, then units already sold to customers, then stock still on hand."""
    return sorted(
        exposures,
        key=lambda e: (
            SEVERITY_ORDER.get(e.get("severity", "low"), 3),
            -int(e.get("sold_after_date_qty") or 0),
            -int(e.get("distinct_customers") or 0),
            -int(e.get("on_hand_qty") or 0),
            e.get("outlet_id", ""),
        ),
    )


def action_rows(exposures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for rank, e in enumerate(rank_exposures(exposures), start=1):
        rows.append(
            {
                "#": rank,
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


def trace_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Evidence judges look for: handoffs, critic revisions, escalations, sponsor calls, models."""
    return {
        "events": len(events),
        "agents": sorted({e.get("agent_name") for e in events if e.get("agent_name")}),
        "handoffs": sum(1 for e in events if e.get("target_agent")),
        "critic_revisions": sum(
            1 for e in events
            if "critic" in (e.get("agent_name") or "").lower() and (e.get("status") or "") in REVISION_STATUSES
        ),
        "needs_review": sum(1 for e in events if (e.get("status") or "") == "needs_review"),
        "sponsor_calls": dict(Counter(e.get("sponsor_call") for e in events if e.get("sponsor_call"))),
        "served_by": sorted({e.get("served_by") for e in events if e.get("served_by")}),
        "fallbacks": sorted({e.get("action") for e in events if "fallback" in (e.get("action") or "")}),
    }
