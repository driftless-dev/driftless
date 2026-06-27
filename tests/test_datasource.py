"""P3.1: external-dataset fetch step for the `poll` job."""

from pathlib import Path

import pytest

from driftless import datasource
from driftless.contract import DataSourceSpec, Workflow
from driftless.datasource import fetch_dataset
from driftless.errors import HarnessError, DriftlessError


def _workflow(data_source: dict | None) -> Workflow:
    eval_block = {"labels_path": "labels.jsonl", "id_field": "id"}
    if data_source is not None:
        eval_block["data_source"] = data_source
    return Workflow.model_validate(
        {
            "run": {"command": "true", "input_path": "inputs.jsonl", "output_path": "out.jsonl"},
            "model": {"current": "m", "env_var": "M"},
            "eval": eval_block,
        }
    )


def test_no_data_source_is_a_noop(tmp_path: Path):
    result = fetch_dataset(_workflow(None), cwd=tmp_path)
    assert result.fetched is False
    assert result.actions == []


def test_command_fetch_writes_dataset(tmp_path: Path):
    wf = _workflow({"command": "printf '%s\\n' '{\"id\":\"a\",\"label\":\"x\"}' > labels.jsonl"})
    result = fetch_dataset(wf, cwd=tmp_path)
    assert result.fetched is True
    assert (tmp_path / "labels.jsonl").read_text().strip() == '{"id":"a","label":"x"}'


def test_command_failure_raises(tmp_path: Path):
    wf = _workflow({"command": "exit 3"})
    with pytest.raises(HarnessError, match="failed"):
        fetch_dataset(wf, cwd=tmp_path)


def test_url_fetch_writes_inputs_and_labels(tmp_path: Path, monkeypatch):
    payloads = {
        "https://x/inputs.jsonl": b'{"id":"a","text":"hi"}\n',
        "https://x/labels.jsonl": b'{"id":"a","label":"billing"}\n',
    }
    seen = []

    def fake_get(url, timeout):
        seen.append(url)
        return payloads[url]

    monkeypatch.setattr(datasource, "_http_get", fake_get)
    wf = _workflow({"inputs_url": "https://x/inputs.jsonl", "labels_url": "https://x/labels.jsonl"})
    result = fetch_dataset(wf, cwd=tmp_path)
    assert result.fetched is True
    assert (tmp_path / "inputs.jsonl").read_bytes() == payloads["https://x/inputs.jsonl"]
    assert (tmp_path / "labels.jsonl").read_bytes() == payloads["https://x/labels.jsonl"]
    assert set(seen) == set(payloads)


def test_url_fetch_sends_bearer_token(tmp_path: Path, monkeypatch):
    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}\n"

    def fake_urlopen(req, timeout):
        captured["auth"] = req.headers.get("Authorization")
        return FakeResp()

    monkeypatch.setattr(datasource.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv(datasource.DATASOURCE_TOKEN_ENV, "sekret")
    wf = _workflow({"inputs_url": "https://x/inputs.jsonl"})
    fetch_dataset(wf, cwd=tmp_path)
    assert captured["auth"] == "Bearer sekret"


def test_labels_url_without_labels_path_errors(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(datasource, "_http_get", lambda url, timeout: b"{}\n")
    wf = Workflow.model_validate(
        {
            "run": {"command": "true", "input_path": "inputs.jsonl", "output_path": "out.jsonl"},
            "model": {"current": "m", "env_var": "M"},
            "eval": {"score_field": "q", "data_source": {"labels_url": "https://x/labels.jsonl"}},
        }
    )
    with pytest.raises(DriftlessError, match="labels_path"):
        fetch_dataset(wf, cwd=tmp_path)


def test_data_source_requires_a_mechanism():
    with pytest.raises(ValueError, match="command and/or"):
        DataSourceSpec.model_validate({})
