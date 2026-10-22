"""Guards the Day-1 contracts so A, B and C can build against them in parallel."""

import inspect

import pytest

from app.adapters import AdapterError, DataAdapter
from app.llm import GenerationResult, generate
from app.schemas import Exposure, RunRequest, RunResult, TraceEvent


def test_run_request_matches_section_7_1():
    req = RunRequest.model_validate(
        {
            "run_id": "demo-001",
            "input": {
                "mode": "recall_alert",
                "recall": {
                    "product_name": "X",
                    "reg_no": "MAL12345678A",
                    "batches": ["2311021"],
                    "date": "2026-10-01",
                    "degree_level": "II",
                },
            },
            "options": {"sample_mode": True, "max_critic_rounds": 2},
        }
    )
    assert req.input.recall.batches == ["2311021"]


def test_run_result_error_shape():
    res = RunResult(
        run_id="r",
        status="error",
        error={"type": "AdapterError", "message": "down", "recoverable": True},
        trace_id="trace-r",
        log_file="logs/trace-r.jsonl",
    )
    assert res.error.recoverable


def test_exposure_rejects_bad_confidence():
    with pytest.raises(ValueError):
        Exposure(
            outlet_id="OUT-01", product_name="X", batch="B", severity="high",
            status="confirmed", confidence=1.5, recommended_action="a", rule_ref="r",
        )


def test_trace_summary_capped_at_200_chars():
    with pytest.raises(ValueError):
        TraceEvent(run_id="r", agent_name="A", action="x", input_summary="a" * 201)


def test_data_adapter_is_abstract():
    with pytest.raises(TypeError):
        DataAdapter()

    class Fake(DataAdapter):
        name = "fake"

        def query(self, sql, params=None, limit=1000):
            return [{"one": 1}][:limit]

    assert Fake().query("SELECT 1") == [{"one": 1}]
    assert AdapterError("x").recoverable is True


def test_generate_signature_is_locked():
    params = list(inspect.signature(generate).parameters)
    assert params == ["prompt", "system_prompt", "model", "json_schema"]
    assert set(GenerationResult.model_fields) == {"text", "provider", "served_by", "latency_ms"}
