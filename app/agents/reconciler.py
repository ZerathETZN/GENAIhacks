"""ReconcilerAgent: deterministic matching first; only ambiguous cases reach the
model, in batched calls. Without a model the agent applies score thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pydantic import BaseModel

from app.llm import generate as default_generate
from app.meterless.hmem import MemoryRetrievalService
from app.reconcile.match import Match, classify
from app.schemas import Evidence, Recall, TraceEvent

NAME = "ReconcilerAgent"
CALL_BATCH = 15  # ambiguous cases per model call (lanes are rate-limited)
MAX_CALLS = 3  # hard cap per reconcile(); the rest fall to the thresholds
HEURISTIC_MIN_IDENTITY = 0.75

_SYSTEM = (
    "You decide whether pharmacy records refer to the same recalled product. "
    "Batch numbers were already matched exactly; judge only the product identity "
    "(names may differ in language, spelling, dosage wording). Say 'unsure' if you cannot tell."
)


class _Verdict(BaseModel):
    id: int
    verdict: Literal["same", "different", "unsure"]


class _Verdicts(BaseModel):
    verdicts: list[_Verdict]


@dataclass
class Candidate:
    record: dict[str, Any]
    status: Literal["match", "needs_review"]
    confidence: float
    via: str
    reasons: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)


class ReconcilerAgent:
    def __init__(
        self,
        hmem: MemoryRetrievalService,
        run_id: str,
        generate: Callable[..., Any] = default_generate,
        emit: Callable[[TraceEvent], None] = lambda e: None,
    ) -> None:
        self.hmem, self.run_id, self.generate, self.emit = hmem, run_id, generate, emit

    def reconcile(self, recall: Recall, records: list[dict[str, Any]]) -> list[Candidate]:
        out: list[Candidate] = []
        ambiguous: list[tuple[dict[str, Any], Match]] = []
        for rec in records:
            m = classify(recall, rec, self.hmem)
            if m.label == "match":
                out.append(Candidate(rec, "match", round(m.identity, 2), m.via, m.reasons, m.evidence))
                if m.via == "hmem":
                    self._trace("hmem_hit", f"{rec['source']}:{rec['record_id']}", "verified alias used", "meterless.hmem", m.identity)
            elif m.label == "near_miss":
                out.append(Candidate(rec, "needs_review", round(m.identity * 0.5, 2), m.via, m.reasons + ["batch near-miss"], m.evidence))
            elif m.label == "ambiguous":
                ambiguous.append((rec, m))
        return out + self._resolve(recall, ambiguous)

    def _resolve(self, recall: Recall, ambiguous: list[tuple[dict[str, Any], Match]]) -> list[Candidate]:
        out: list[Candidate] = []
        for i in range(0, len(ambiguous), CALL_BATCH):
            chunk = ambiguous[i : i + CALL_BATCH]
            verdicts = self._ask_model(recall, chunk) if i // CALL_BATCH < MAX_CALLS else {}
            for idx, (rec, m) in enumerate(chunk):
                v = verdicts.get(idx)
                if v == "different":
                    continue
                if v == "same":
                    out.append(Candidate(rec, "match", 0.8, "llm", m.reasons, m.evidence))
                elif v is None and m.identity >= HEURISTIC_MIN_IDENTITY:
                    out.append(Candidate(rec, "match", round(m.identity * 0.9, 2), "heuristic", m.reasons, m.evidence))
                else:
                    out.append(Candidate(rec, "needs_review", round(m.identity * 0.5, 2), "unresolved", m.reasons, m.evidence))
        return out

    def _ask_model(self, recall: Recall, chunk: list[tuple[dict[str, Any], Match]]) -> dict[int, str]:
        cases = [{"id": i, "name": r.get("product_name"), "reg_no": r.get("reg_no"), "source": r["source"]} for i, (r, _) in enumerate(chunk)]
        prompt = f"Recalled product: {recall.product_name} ({recall.reg_no}).\nRecords:\n{cases}"
        res = self.generate(prompt, system_prompt=_SYSTEM, json_schema=_Verdicts)
        verdicts: dict[int, str] = {}
        if res.provider != "heuristic_fallback" and res.text:
            verdicts = {v.id: v.verdict for v in _Verdicts.model_validate_json(res.text).verdicts}
        self._trace(
            "resolve_ambiguous", f"{len(chunk)} ambiguous cases",
            f"{len(verdicts)} verdicts" if verdicts else "no model verdicts; thresholds applied",
            "meterless.nightshift" if res.provider == "meterless" else None, None,
            provider=res.provider, served_by=res.served_by, duration_ms=res.latency_ms,
        )
        return verdicts

    def _trace(self, action: str, inp: str, out: str, sponsor: str | None, conf: float | None, **kw: Any) -> None:
        self.emit(TraceEvent(
            run_id=self.run_id, agent_name=NAME, action=action, input_summary=inp[:200],
            output_summary=out[:200], sponsor_call=sponsor, confidence=conf, **kw,
        ))
