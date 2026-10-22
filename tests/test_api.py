"""Part C: API, CLI and runner behaviour. Uses an injected fake orchestrator; never a canned result in app code."""

import json
import sys
import types

import pytest
from fastapi.testclient import TestClient

from app.schemas import RunRequest, RunResult

REQ = {
    "run_id": "t-001",
    "input": {"mode": "recall_alert",
              "recall": {"product_name": "X", "reg_no": "MAL1", "batches": ["B1"], "date": "2026-10-01"}},
    "options": {"sample_mode": True},
}


@pytest.fixture(autouse=True)
def tmp_logs(tmp_path, monkeypatch):
    from app import runner
    monkeypatch.setattr(runner, "LOG_DIR", tmp_path)
    monkeypatch.delenv("SAMPLE_MODE", raising=False)
    yield tmp_path


@pytest.fixture
def fake_orchestrator(monkeypatch, tmp_logs):
    calls = []

    def run(request: RunRequest) -> RunResult:
        calls.append(request)
        (tmp_logs / f"trace-{request.run_id}.jsonl").write_text(
            json.dumps({"run_id": request.run_id, "agent_name": "PlannerAgent", "action": "plan"}) + "\nnot json\n")
        return RunResult(run_id=request.run_id, status="success",
                         output={"summary": "s", "exposures": []},
                         trace_id=f"trace-{request.run_id}", log_file=f"logs/trace-{request.run_id}.jsonl")

    monkeypatch.setitem(sys.modules, "app.orchestrator", types.SimpleNamespace(run=run))
    return calls


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_health_sample_mode_skips_external_checks(client, monkeypatch):
    monkeypatch.setenv("SAMPLE_MODE", "true")
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["meterless"]["status"] == "skipped"


def test_health_never_leaks_token(client, monkeypatch):
    monkeypatch.setenv("METERLESS_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "secret-token-123")
    assert "secret-token-123" not in client.get("/health").text


def test_run_without_orchestrator_is_honest_error(client, monkeypatch):
    monkeypatch.setitem(sys.modules, "app.orchestrator", None)  # import raises ModuleNotFoundError
    body = client.post("/run", json=REQ).json()
    assert body["status"] == "error" and body["error"]["type"] == "NotImplemented"


def test_run_success_saved_and_trace_served(client, fake_orchestrator):
    body = client.post("/run", json=REQ).json()
    assert body["status"] == "success" and body["execution_time_seconds"] > 0
    assert client.get("/runs/t-001").json()["run_id"] == "t-001"
    trace = client.get("/runs/t-001/trace").json()
    assert [e["agent_name"] for e in trace] == ["PlannerAgent"]  # malformed line skipped


def test_orchestrator_exception_becomes_structured_error(client, monkeypatch):
    class Boom(RuntimeError):
        recoverable = False

    def run(_):
        raise Boom("zetaris down")

    monkeypatch.setitem(sys.modules, "app.orchestrator", types.SimpleNamespace(run=run))
    body = client.post("/run", json=REQ).json()
    assert body["error"] == {"type": "Boom", "message": "zetaris down", "recoverable": False}


def test_env_sample_mode_forces_option(client, fake_orchestrator, monkeypatch):
    monkeypatch.setenv("SAMPLE_MODE", "true")
    client.post("/run", json={**REQ, "options": {"sample_mode": False}})
    assert fake_orchestrator[0].options.sample_mode is True


def test_recall_alert_needs_recall(client, fake_orchestrator):
    body = client.post("/run", json={**REQ, "input": {"mode": "recall_alert"}}).json()
    assert body["status"] == "error" and not fake_orchestrator


@pytest.mark.parametrize("bad", ["../etc", "a/b", "", "x" * 70])
def test_unsafe_run_ids_rejected(client, fake_orchestrator, bad):
    body = client.post("/run", json={**REQ, "run_id": bad}).json()
    assert body["status"] == "error" and not fake_orchestrator


def test_trace_endpoint_rejects_traversal(client):
    assert client.get("/runs/..%2Fsecret/trace").status_code in (400, 404)


def test_cli_runs_example_and_writes_output(fake_orchestrator, tmp_path):
    import run
    src = tmp_path / "in.json"
    src.write_text(json.dumps(REQ))
    out = tmp_path / "out.json"
    assert run.main(["--input", str(src), "--output", str(out)]) == 0
    assert json.loads(out.read_text())["status"] == "success"


def test_cli_bad_input_exit_code(tmp_path):
    import run
    bad = tmp_path / "bad.json"
    bad.write_text('{"run_id": "x"}')
    assert run.main(["--input", str(bad)]) == 2
    assert run.main(["--input", str(tmp_path / "missing.json")]) == 2


def test_input_examples_match_contract():
    from pathlib import Path
    files = sorted(Path("input_examples").glob("example_*.json"))
    assert len(files) >= 3, "judges expect at least three sample inputs"
    for f in files:
        RunRequest.model_validate_json(f.read_text())
