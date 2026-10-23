"""ReporterAgent: rules table decides severity and action (deterministic); the
model only writes the one-paragraph summary, with a templated fallback.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable

import yaml

from app.llm import GenerationResult, generate as _generate
from app.reconcile.aggregate import UNASSIGNED, ExposureDraft
from app.schemas import Exposure, Recall, RunOutput, TraceEvent

NAME = "ReporterAgent"
RULES = yaml.safe_load((Path(__file__).parent.parent / "rules" / "actions.yaml").read_text(encoding="utf-8"))


def pick_rule(recall: Recall) -> str:
    """Rule key for a recall. Administrative = no degree and no batch (cancelled registrations carry neither)."""
    m = re.search(r"\b(III|II|I)\b", (recall.degree_level or "").upper())
    if m:
        return f"degree-{m.group(1)}"
    return "voluntary-no-degree" if recall.batches or recall.degree_level else "administrative"


_TIERS = ["low", "medium", "high"]


def pick_level(recall: Recall) -> str | None:
    """Recall level A/B/C from the notice wording (App. 34 s4.4); None when the notice gives none."""
    t = (recall.degree_level or "").lower()
    if "sub-distributor" in t or "distributor" in t or "wholesaler" in t:
        return "C"
    if "consumer" in t or re.search(r"level a", t):
        return "A"
    return "B" if "sales" in t or "level b" in t else None


class ReporterAgent:
    def __init__(
        self,
        run_id: str,
        generate: Callable[..., GenerationResult] = _generate,
        emit: Callable[[TraceEvent], None] = lambda e: None,
    ) -> None:
        self.run_id, self.generate, self.emit = run_id, generate, emit

    def report(self, recall: Recall, drafts: list[ExposureDraft]) -> RunOutput:
        key, level = pick_rule(recall), pick_level(recall)
        rule = dict(RULES[key])
        if level == "C":  # distributors only: the chain's shelf stock is not in scope
            rule["severity"] = _TIERS[max(_TIERS.index(rule["severity"]) - 1, 0)]
        real = [d for d in drafts if d.outlet_id != UNASSIGNED]
        # safety recalls rank by units sold, then stock; administrative by stock
        rank = (lambda d: (d.sold_after_date_qty, d.on_hand_qty)) if rule["rank_by"] == "sold" else (lambda d: (d.on_hand_qty,))
        exposures = [self._exposure(recall, d, key, rule, level) for d in sorted(real, key=rank, reverse=True)]
        conflicts = [
            {"outlet_id": d.outlet_id, "batch": d.batch, "reasons": d.reasons, "doubts": d.doubts}
            for d in drafts if d.status == "needs_review"
        ]
        return RunOutput(summary=self._summary(recall, key, rule, exposures, conflicts), exposures=exposures, unresolved_conflicts=conflicts)

    def _exposure(self, recall: Recall, d: ExposureDraft, key: str, rule: dict, level: str | None) -> Exposure:
        action = f"{rule['action']} ({rule['ref']})"
        if level == "C":
            action += " Level C: applies to distribution stock, check whether any shelf stock came from the recalled distributor."
        if d.sold_after_date_qty and level in ("A", None):  # customers only need contacting when the recall reaches consumers
            action += f" Outlet {d.outlet_id} sold {d.sold_after_date_qty} units of batch {d.batch} to {d.distinct_customers} distinct loyalty customers since {recall.date}."
        return Exposure(
            outlet_id=d.outlet_id, product_name=d.product_name, reg_no=d.reg_no, batch=d.batch,
            on_hand_qty=d.on_hand_qty, sold_after_date_qty=d.sold_after_date_qty, distinct_customers=d.distinct_customers,
            severity=rule["severity"], status=d.status, confidence=d.confidence, recommended_action=action,
            rule_ref=f"actions.yaml#{key}", critic_check=d.critic_check, evidence=d.evidence,
        )

    def _summary(self, recall: Recall, key: str, rule: dict, exposures: list[Exposure], conflicts: list[dict]) -> str:
        facts = (
            f"{recall.product_name} ({recall.reg_no}), rule {key}, severity {rule['severity']}: "
            f"{len(exposures)} outlets exposed, {sum(e.on_hand_qty for e in exposures)} units on hand, "
            f"{sum(e.sold_after_date_qty for e in exposures)} units sold since {recall.date}, {len(conflicts)} items need review."
        )
        t0 = time.monotonic()
        res = self.generate(
            f"Write a two-sentence summary for a pharmacist. Use only these facts, add nothing:\n{facts}",
            system_prompt="You summarise recall exposure. Do not give legal or compliance conclusions.",
        )
        self.emit(TraceEvent(
            run_id=self.run_id, agent_name=NAME, action="summarise", input_summary=facts[:200],
            output_summary=(res.text or "templated")[:200], provider=res.provider, served_by=res.served_by,
            sponsor_call="meterless.nightshift" if res.provider == "meterless" else None, duration_ms=int((time.monotonic() - t0) * 1000),
        ))
        return res.text.strip() or facts  # heuristic fallback: the templated facts are the summary
