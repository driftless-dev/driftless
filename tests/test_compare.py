from driftless.calibrate import suggest_thresholds
from driftless.compare import check_thresholds
from driftless.contract import ThresholdsSpec
from driftless.evaluation import Metrics


def _metrics(**kw) -> Metrics:
    base = dict(n=100, schema_error_rate=0.0, refusal_rate=0.0)
    base.update(kw)
    return Metrics(**base)


def test_min_thresholds_pass_and_fail():
    thresholds = ThresholdsSpec(min_f1=0.9, min_precision=0.9)
    baseline = _metrics(f1=0.95, precision=0.95)

    good = check_thresholds(thresholds, baseline, _metrics(f1=0.92, precision=0.91))
    assert all(c.passed for c in good)

    bad = check_thresholds(thresholds, baseline, _metrics(f1=0.80, precision=0.95))
    failed = {c.name for c in bad if not c.passed}
    assert failed == {"min_f1"}


def test_max_schema_error_rate():
    thresholds = ThresholdsSpec(max_schema_error_rate=0.01)
    baseline = _metrics(schema_error_rate=0.0)
    checks = check_thresholds(thresholds, baseline, _metrics(schema_error_rate=0.05))
    assert any(c.name == "max_schema_error_rate" and not c.passed for c in checks)


def test_cost_increase_check():
    thresholds = ThresholdsSpec(max_cost_increase=0.0)
    baseline = _metrics(total_cost=1.0)
    # target cheaper -> passes
    cheaper = check_thresholds(thresholds, baseline, _metrics(total_cost=0.6))
    assert any(c.name == "max_cost_increase" and c.passed for c in cheaper)
    # target pricier -> fails
    pricier = check_thresholds(thresholds, baseline, _metrics(total_cost=1.4))
    assert any(c.name == "max_cost_increase" and not c.passed for c in pricier)


def test_cost_check_skipped_without_data():
    thresholds = ThresholdsSpec(max_cost_increase=0.0)
    baseline = _metrics(total_cost=None)
    checks = check_thresholds(thresholds, baseline, _metrics(total_cost=None))
    cost = next(c for c in checks if c.name == "max_cost_increase")
    assert cost.passed and "skipped" in cost.detail


def test_latency_increase():
    thresholds = ThresholdsSpec(max_latency_increase=0.10)
    baseline = _metrics(avg_latency_ms=100.0)
    checks = check_thresholds(thresholds, baseline, _metrics(avg_latency_ms=120.0))
    assert any(c.name == "max_latency_increase" and not c.passed for c in checks)


# --------------------------------------------------------------------------- #
# P2.2: relative no-regression default
# --------------------------------------------------------------------------- #
def test_no_thresholds_uses_no_regression_default():
    thresholds = ThresholdsSpec()  # nothing configured
    baseline = _metrics(f1=0.90, schema_error_rate=0.01)

    # Target holds quality within tolerance -> passes the no-regression bar.
    ok = check_thresholds(thresholds, baseline, _metrics(f1=0.89, schema_error_rate=0.01))
    assert ok and all(c.passed for c in ok)
    assert any(c.name == "no_regression_f1" for c in ok)

    # Target regresses well beyond tolerance -> fails.
    bad = check_thresholds(thresholds, baseline, _metrics(f1=0.70, schema_error_rate=0.01))
    assert any(c.name == "no_regression_f1" and not c.passed for c in bad)


def test_absolute_threshold_suppresses_relative():
    thresholds = ThresholdsSpec(min_f1=0.8)
    baseline = _metrics(f1=0.95)
    checks = check_thresholds(thresholds, baseline, _metrics(f1=0.85))
    assert not any(c.name.startswith("no_regression") for c in checks)
    assert any(c.name == "min_f1" for c in checks)


def test_regression_tolerance_is_configurable():
    thresholds = ThresholdsSpec(regression_tolerance=0.10)
    baseline = _metrics(f1=0.90)
    # 0.82 is within a 0.10 band of 0.90 -> passes.
    checks = check_thresholds(thresholds, baseline, _metrics(f1=0.82))
    assert all(c.passed for c in checks)


def test_suggest_thresholds_from_metrics():
    metrics = _metrics(f1=0.92, precision=0.95, recall=0.90, schema_error_rate=0.01)
    suggested = suggest_thresholds(metrics, margin=0.03)
    assert suggested["min_f1"] == 0.89
    assert suggested["min_precision"] == 0.92
    assert suggested["max_schema_error_rate"] == 0.04


def test_suggest_thresholds_skips_unmeasured():
    metrics = _metrics(schema_error_rate=0.0)  # no f1/precision/recall
    suggested = suggest_thresholds(metrics)
    assert "min_f1" not in suggested
    assert suggested["max_schema_error_rate"] == 0.03
