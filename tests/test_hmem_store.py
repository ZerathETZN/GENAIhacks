import json

import pytest

from app.meterless.hmem import MemoryRetrievalService, MemoryStoreService


def _remember(store, **kw):
    args = dict(field="product_name", alias="Parasetamol", canonical="Paracetamol", source="critic_check", run_id="r1", agent_id="ConflictCriticAgent")
    return store.remember_alias(**{**args, **kw})


def test_unverified_source_is_rejected():
    with pytest.raises(ValueError):
        _remember(MemoryStoreService(), source="reconciler_guess")


def test_alias_found_in_both_directions_and_between_siblings():
    store = MemoryStoreService()
    _remember(store)
    _remember(store, alias="Paracetamol 500", canonical="Paracetamol")
    mem = MemoryRetrievalService(store)
    assert mem.same("product_name", "PARASETAMOL", "paracetamol")["source"] == "critic_check"
    assert mem.same("product_name", "Paracetamol", "Parasetamol")
    assert mem.same("product_name", "parasetamol", "Paracetamol-500")  # two aliases, one canonical
    assert mem.same("product_name", "Parasetamol", "Ibuprofen") is None
    assert mem.same("batch", "Parasetamol", "Paracetamol") is None  # scoped by field


def test_format_only_difference_is_not_stored():
    store = MemoryStoreService()
    assert _remember(store, field="batch", alias="nsc-24067", canonical="NSC24067") is False


def test_memory_survives_reopen(tmp_path):
    path = str(tmp_path / "hmem.db")
    _remember(MemoryStoreService(path))
    assert MemoryRetrievalService(MemoryStoreService(path)).same("product_name", "Parasetamol", "Paracetamol")


def test_load_jsonl_marks_source_and_skips_missing_file(tmp_path):
    f = tmp_path / "decisions.jsonl"
    f.write_text(json.dumps({"field": "product_name", "alias": "Parasetamol", "canonical": "Paracetamol"}) + "\n")
    store = MemoryStoreService()
    assert store.load_jsonl(str(f), "human_verdict", "r1") == 1
    assert store.load_jsonl(str(tmp_path / "none.jsonl"), "seed", "r1") == 0
    assert MemoryRetrievalService(store).same("product_name", "Parasetamol", "Paracetamol")["source"] == "human_verdict"
