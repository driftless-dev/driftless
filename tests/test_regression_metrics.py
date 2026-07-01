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


def test_check_baseline_flags_regression(tmp_path, monkeypatch):
    from regression_metrics import MetricsDegradationError, check_baseline, record_live_eval

    path = tmp_path / "metrics.jsonl"
    monkeypatch.setenv("DRIFTLESS_REGRESSION_METRICS", str(path))
    record_live_eval(
        scenario="ticket_classifier",
        provider="openai",
        status="pass",
        iterations=2,
        final_f1=0.95,
    )
    baseline = {
        "ticket_classifier": {
            "openai": {"require_status": "pass", "min_final_f1": 0.85, "max_iterations": 8}
        }
    }
    check_baseline(baseline, scenario="ticket_classifier", provider="openai")

    record_live_eval(
        scenario="ticket_classifier",
        provider="openai",
        status="pass",
        iterations=2,
        final_f1=0.70,
    )
    with pytest.raises(MetricsDegradationError, match="final_f1"):
        check_baseline(baseline, scenario="ticket_classifier", provider="openai")


def test_check_all_baselines_skips_missing_scenarios(tmp_path, monkeypatch):
    from regression_metrics import check_all_baselines, record_live_eval

    path = tmp_path / "metrics.jsonl"
    monkeypatch.setenv("DRIFTLESS_REGRESSION_METRICS", str(path))
    record_live_eval(
        scenario="ticket_classifier",
        provider="openai",
        status="pass",
        iterations=2,
        final_f1=0.95,
    )
    baseline = {
        "ticket_classifier": {
            "openai": {"require_status": "pass", "min_final_f1": 0.85, "max_iterations": 8}
        },
        "qa_scorer": {
            "openai": {"require_status": "pass", "min_final_score": 0.85, "max_iterations": 8}
        },
    }
    check_all_baselines(baseline, provider="openai", require_all=False)
