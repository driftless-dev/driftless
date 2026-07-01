from pathlib import Path

import pytest

from regression_metrics import metrics_path, record_live_eval


def test_record_live_eval_appends_jsonl(tmp_path, monkeypatch):
    path = tmp_path / "metrics.jsonl"
    monkeypatch.setenv("DRIFTLESS_REGRESSION_METRICS", str(path))

    record_live_eval(
        scenario="ticket_classifier",
        provider="openai",
        status="pass",
        iterations=2,
        final_f1=0.95,
        baseline_f1=0.5,
    )
    record_live_eval(
        scenario="ticket_classifier",
        provider="openai",
        status="pass",
        iterations=3,
        final_f1=0.93,
    )

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert '"iterations": 2' in lines[0]
    assert '"iterations": 3' in lines[1]
    assert metrics_path() == path
