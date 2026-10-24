from app.agents.reconciler import ReconcilerAgent
from app.llm import GenerationResult
from app.meterless.hmem import MemoryRetrievalService, MemoryStoreService
from app.schemas import Recall

RECALL = Recall(product_name="Paracetamol 500mg Tablet", reg_no="MAL12345678A", batches=["NSC-24067", "NSC-24068"], date="2026-10-01")


def rec(rid, batch="nsc24067", name="Paracetamol 500mg Tablet", reg_no="MAL12345678A", source="inventory"):
    return {"source": source, "record_id": rid, "product_name": name, "reg_no": reg_no, "batch": batch}


def agent(generate=None, store=None, events=None):
    # never the real generate(): a token in the environment (C's app loads .env) would call Nightshift from a unit test
    kw = {"generate": generate or fake_generate()}
    emit = events.append if events is not None else (lambda e: None)
    return ReconcilerAgent(MemoryRetrievalService(store or MemoryStoreService()), "r1", emit=emit, **kw)


def fake_generate(text="", provider="heuristic_fallback", calls=None):
    def g(prompt, system_prompt=None, model=None, json_schema=None):
        if calls is not None:
            calls.append(prompt)
        return GenerationResult(text=text, provider=provider, served_by="gpt" if text else None, latency_ms=1)

    return g


def test_exact_reg_no_and_batch_format_variant_match_without_model():
    calls = []
    recs = [rec("I1", batch="NSC 24067"), rec("P1", source="pos", batch="nsc-24068", reg_no=None)]
    out = agent(fake_generate(calls=calls)).reconcile(RECALL, recs)
    assert [(c.status, c.via) for c in out] == [("match", "reg_no"), ("match", "name_fuzzy")]
    assert calls == []


def test_decoy_batch_and_other_product_are_not_flagged():
    assert agent().reconcile(RECALL, [rec("I1", batch="XYZ99999"), rec("I2", reg_no="MAL99999999Z")]) == []


def test_adjacent_batch_is_review_not_match():
    out = agent().reconcile(RECALL, [rec("I1", batch="NSC24069")])
    assert [c.status for c in out] == ["needs_review"]


def test_empty_batches_means_every_batch_is_affected():
    admin = Recall(product_name="X", reg_no="MAL12345678A", batches=[], date="2026-10-01")
    assert [c.status for c in agent().reconcile(admin, [rec("I1", batch="ANY1")])] == ["match"]


def test_ambiguous_goes_to_model_in_one_batched_call():
    calls, events = [], []
    text = '{"verdicts":[{"id":0,"verdict":"same"},{"id":1,"verdict":"different"},{"id":2,"verdict":"unsure"}]}'
    recs = [rec(f"P{i}", source="pos", reg_no=None, name="Panadol Paracetamol") for i in range(3)]
    out = agent(fake_generate(text, "meterless", calls), events=events).reconcile(RECALL, recs)
    assert len(calls) == 1
    assert [(c.record["record_id"], c.status, c.via) for c in out] == [("P0", "match", "llm"), ("P2", "needs_review", "unresolved")]
    ev = [e for e in events if e.action == "resolve_ambiguous"][0]
    assert (ev.provider, ev.served_by, ev.sponsor_call) == ("meterless", "gpt", "meterless.nightshift")


def test_without_model_thresholds_decide_ambiguous():
    recs = [
        rec("P1", source="pos", reg_no=None, name="Paracetamol 500 mg Caplet"),  # identity ~0.82
        rec("P2", source="pos", reg_no=None, name="Paracetamol 650mg Syrup"),  # identity ~0.72: different product
        rec("P3", source="pos", reg_no=None, name="Calpol"),  # identity ~0.27: dropped
    ]
    out = {c.record["record_id"]: (c.status, c.via) for c in agent().reconcile(RECALL, recs)}
    assert out == {"P1": ("match", "heuristic"), "P2": ("needs_review", "unresolved")}


def test_hmem_alias_resolves_without_model_and_is_traced():
    store = MemoryStoreService()
    store.remember_alias("product_name", "Panadol", RECALL.product_name, "critic_check", "r0", "ConflictCriticAgent")
    calls, events = [], []
    recs = [rec("P1", source="pos", reg_no=None, name="Panadol")]
    out = agent(fake_generate(calls=calls), store, events).reconcile(RECALL, recs)
    assert [(c.status, c.via) for c in out] == [("match", "hmem")] and calls == []
    assert any(e.sponsor_call == "meterless.hmem" for e in events)
