"""P5.2: endpoint-based workflow execution in the harness."""

import json

import pytest

from driftless import harness
from driftless.contract import RunSpec, Workflow
from driftless.errors import HarnessError
from driftless.harness import run_workflow


def _read_out(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _endpoint_workflow(**run_overrides) -> Workflow:
    run = {
        "endpoint": "https://svc.example.com/classify",
        "input_path": "inputs.jsonl",
        "output_path": "out.jsonl",
    }
    run.update(run_overrides)
    return Workflow.model_validate(
        {
            "run": run,
            "model": {"current": "gpt-4o-mini"},
            "eval": {"labels_path": "labels.jsonl", "label_field": "label", "id_field": "id"},
        }
    )


def _write_inputs(tmp_path, records):
    (tmp_path / "inputs.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


def test_endpoint_run_posts_each_record_and_writes_outputs(tmp_path, monkeypatch):
    _write_inputs(tmp_path, [{"id": "a", "text": "billing issue"}, {"id": "b", "text": "crash"}])
    seen = []

    def fake_post(url, payload, headers, timeout):
        body = json.loads(payload.decode("utf-8"))
        seen.append((url, body, headers))
        # Endpoint returns only a label; harness should copy the id through.
        return json.dumps({"label": "billing" if "billing" in body["text"] else "technical"})

    monkeypatch.setattr(harness, "_http_post", fake_post)
    monkeypatch.delenv(harness.ENDPOINT_TOKEN_ENV, raising=False)

    result = run_workflow(_endpoint_workflow(), "gpt-5-mini", cwd=tmp_path)

    assert result.ok
    rows = _read_out(result.output_path)
    assert [r["label"] for r in rows] == ["billing", "technical"]
    # id carried through from the input since the response omitted it.
    assert [r["id"] for r in rows] == ["a", "b"]
    # The model was injected into every request body under the default key.
    assert all(body["model"] == "gpt-5-mini" for _, body, _ in seen)
    assert seen[0][0] == "https://svc.example.com/classify"


def test_endpoint_respects_custom_model_param(tmp_path, monkeypatch):
    _write_inputs(tmp_path, [{"id": "a", "text": "x"}])
    captured = {}

    def fake_post(url, payload, headers, timeout):
        captured["body"] = json.loads(payload.decode("utf-8"))
        return json.dumps({"id": "a", "label": "technical"})

    monkeypatch.setattr(harness, "_http_post", fake_post)
    run_workflow(_endpoint_workflow(model_param="model_id"), "m1", cwd=tmp_path)
    assert captured["body"]["model_id"] == "m1"


def test_endpoint_sends_bearer_token_when_set(tmp_path, monkeypatch):
    _write_inputs(tmp_path, [{"id": "a", "text": "x"}])
    captured = {}

    def fake_post(url, payload, headers, timeout):
        captured["headers"] = headers
        return json.dumps({"id": "a", "label": "technical"})

    monkeypatch.setattr(harness, "_http_post", fake_post)
    monkeypatch.setenv(harness.ENDPOINT_TOKEN_ENV, "sekret")
    run_workflow(_endpoint_workflow(), "m1", cwd=tmp_path)
    assert captured["headers"]["Authorization"] == "Bearer sekret"


def test_endpoint_non_json_response_is_a_harness_error(tmp_path, monkeypatch):
    _write_inputs(tmp_path, [{"id": "a", "text": "x"}])
    monkeypatch.setattr(harness, "_http_post", lambda *a, **k: "not json")
    with pytest.raises(HarnessError, match="non-JSON"):
        run_workflow(_endpoint_workflow(), "m1", cwd=tmp_path)


def test_endpoint_non_object_response_is_a_harness_error(tmp_path, monkeypatch):
    _write_inputs(tmp_path, [{"id": "a", "text": "x"}])
    monkeypatch.setattr(harness, "_http_post", lambda *a, **k: json.dumps([1, 2, 3]))
    with pytest.raises(HarnessError, match="must be a JSON object"):
        run_workflow(_endpoint_workflow(), "m1", cwd=tmp_path)


def test_endpoint_missing_inputs_is_a_harness_error(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "_http_post", lambda *a, **k: "{}")
    with pytest.raises(HarnessError, match="input dataset not found"):
        run_workflow(_endpoint_workflow(), "m1", cwd=tmp_path)


def test_run_requires_command_or_endpoint():
    with pytest.raises(ValueError, match="either 'command' or 'endpoint'"):
        RunSpec.model_validate({"input_path": "i", "output_path": "o"})


def test_run_rejects_both_command_and_endpoint():
    with pytest.raises(ValueError, match="only one of"):
        RunSpec.model_validate(
            {"command": "echo hi", "endpoint": "http://x", "input_path": "i", "output_path": "o"}
        )


def test_endpoint_concurrency_must_be_in_range():
    with pytest.raises(ValueError, match="endpoint_concurrency"):
        RunSpec.model_validate(
            {
                "endpoint": "http://x",
                "input_path": "i",
                "output_path": "o",
                "endpoint_concurrency": 0,
            }
        )


def test_endpoint_concurrency_preserves_order_and_parallelizes(tmp_path, monkeypatch):
    import threading
    import time

    records = [{"id": str(i), "text": "x"} for i in range(8)]
    _write_inputs(tmp_path, records)
    lock = threading.Lock()
    in_flight = 0
    max_in_flight = 0

    def fake_post(url, payload, headers, timeout):
        nonlocal in_flight, max_in_flight
        body = json.loads(payload.decode("utf-8"))
        with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        time.sleep(0.03)
        with lock:
            in_flight -= 1
        return json.dumps({"id": body["id"], "label": "ok"})

    monkeypatch.setattr(harness, "_http_post", fake_post)
    result = run_workflow(
        _endpoint_workflow(endpoint_concurrency=4), "m1", cwd=tmp_path
    )

    assert result.ok
    assert max_in_flight >= 3
    rows = _read_out(result.output_path)
    assert [r["id"] for r in rows] == [str(i) for i in range(8)]
    assert "concurrency=4" in result.stdout
