"""Compare a current model against a target model through the real workflow.

This runs the baseline (current model) and the naive target (target model,
original files), evaluates both, and checks the target against the contract
thresholds. Whether the naive target passes determines whether a migration
(prompt/config repair, Milestone 3) is even needed.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .contract import ThresholdsSpec, Workflow
from .errors import DriftlessError
from .evaluation import Metrics, evaluate
from .harness import run_workflow
from .progress import log as progress_log


@dataclass
class ThresholdCheck:
    name: str
    passed: bool
    detail: str


@dataclass
class Comparison:
    workflow: str
    current_model: str
    target_model: str
    baseline: Metrics
    target: Metrics
    checks: list[ThresholdCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


# Default no-regression band used when no absolute quality threshold is set.
DEFAULT_REGRESSION_TOLERANCE = 0.02


def _pct_increase(baseline: float | None, target: float | None) -> float | None:
    if baseline is None or target is None or baseline == 0:
        return None
    return (target - baseline) / baseline


def _relative_checks(
    thresholds: ThresholdsSpec, baseline: Metrics, target: Metrics
) -> list[ThresholdCheck]:
    """No-regression-vs-baseline checks, applied when no absolute bar is set.

    This makes ``thresholds:`` optional: with none configured the bar becomes
    "don't drop quality (or raise errors) beyond a tolerance vs. the current
    model" — measured the same way on every run, so the user supplies nothing.
    """
    tol = (
        thresholds.regression_tolerance
        if thresholds.regression_tolerance is not None
        else DEFAULT_REGRESSION_TOLERANCE
    )
    checks: list[ThresholdCheck] = []

    if baseline.f1 is not None:
        metric = "f1"
    elif baseline.score is not None:
        metric = "score"
    elif baseline.accuracy is not None:
        metric = "accuracy"
    else:
        metric = None
    if metric is not None:
        base_q = getattr(baseline, metric)
        tgt_q = getattr(target, metric)
        ok = tgt_q is not None and tgt_q >= base_q - tol
        shown = f"{tgt_q:.3f}" if tgt_q is not None else "n/a"
        checks.append(
            ThresholdCheck(
                f"no_regression_{metric}", ok, f"{shown} >= {base_q:.3f} - {tol:g}"
            )
        )

    for name, attr in (("schema_error_rate", "schema_error_rate"), ("refusal_rate", "refusal_rate")):
        base_e = getattr(baseline, attr)
        if base_e is None:
            continue
        tgt_e = getattr(target, attr)
        ok = tgt_e is not None and tgt_e <= base_e + tol
        shown = f"{tgt_e:.3f}" if tgt_e is not None else "n/a"
        checks.append(
            ThresholdCheck(f"no_regression_{name}", ok, f"{shown} <= {base_e:.3f} + {tol:g}")
        )
    return checks


def check_thresholds(
    thresholds: ThresholdsSpec, baseline: Metrics, target: Metrics
) -> list[ThresholdCheck]:
    checks: list[ThresholdCheck] = []

    def minimum(name: str, value: float | None, floor: float | None) -> None:
        if floor is None:
            return
        ok = value is not None and value >= floor
        shown = f"{value:.3f}" if value is not None else "n/a"
        checks.append(ThresholdCheck(name, ok, f"{shown} >= {floor}"))

    def maximum(name: str, value: float | None, ceiling: float | None) -> None:
        if ceiling is None:
            return
        ok = value is not None and value <= ceiling
        shown = f"{value:.3f}" if value is not None else "n/a"
        checks.append(ThresholdCheck(name, ok, f"{shown} <= {ceiling}"))

    # No absolute quality bar configured -> fall back to no-regression vs baseline.
    if not thresholds.has_absolute_quality():
        checks.extend(_relative_checks(thresholds, baseline, target))

    minimum("min_f1", target.f1, thresholds.min_f1)
    minimum("min_precision", target.precision, thresholds.min_precision)
    minimum("min_recall", target.recall, thresholds.min_recall)
    minimum("min_score", target.score, thresholds.min_score)
    maximum(
        "max_schema_error_rate", target.schema_error_rate, thresholds.max_schema_error_rate
    )

    if thresholds.max_cost_increase is not None:
        inc = _pct_increase(baseline.total_cost, target.total_cost)
        if inc is None:
            checks.append(
                ThresholdCheck("max_cost_increase", True, "no cost data (skipped)")
            )
        else:
            checks.append(
                ThresholdCheck(
                    "max_cost_increase",
                    inc <= thresholds.max_cost_increase,
                    f"{inc:+.1%} <= {thresholds.max_cost_increase:+.0%}",
                )
            )

    if thresholds.max_latency_increase is not None:
        inc = _pct_increase(baseline.avg_latency_ms, target.avg_latency_ms)
        if inc is None:
            checks.append(
                ThresholdCheck("max_latency_increase", True, "no latency data (skipped)")
            )
        else:
            checks.append(
                ThresholdCheck(
                    "max_latency_increase",
                    inc <= thresholds.max_latency_increase,
                    f"{inc:+.1%} <= {thresholds.max_latency_increase:+.0%}",
                )
            )

    return checks


def _metric_summary(metrics: Metrics) -> str:
    if metrics.f1 is not None:
        return f"{metrics.f1:.3f}"
    if metrics.score is not None:
        return f"score={metrics.score:.3f}"
    if metrics.accuracy is not None:
        return f"acc={metrics.accuracy:.3f}"
    return "n/a"


def compare_models(
    workflow_name: str,
    workflow: Workflow,
    target_model: str,
    *,
    judge: object | None = None,
    cwd: Path | None = None,
) -> Comparison:
    cwd = (cwd or Path.cwd()).resolve()
    current = workflow.model.current

    # LLM-as-judge grading: build the judge once so both runs grade consistently.
    if judge is None and workflow.eval.grading == "judge":
        from .judges import build_judge

        judge_spec = workflow.eval.judge
        if judge_spec is None:
            raise DriftlessError(
                "judge grading requires eval.judge in the contract",
                hint="add a judge block to driftless.yml",
            )
        judge = build_judge(judge_spec)

    progress_log(f"compare: baseline run ({current})...")
    baseline_run = run_workflow(workflow, current, cwd=cwd)
    baseline_metrics = evaluate(workflow, baseline_run, judge=judge, cwd=cwd)
    progress_log(
        f"compare: baseline done — "
        f"F1={_metric_summary(baseline_metrics)}, n={baseline_metrics.n}"
    )

    progress_log(f"compare: target run ({target_model})...")
    target_run = run_workflow(workflow, target_model, cwd=cwd)
    target_metrics = evaluate(workflow, target_run, judge=judge, cwd=cwd)
    progress_log(
        f"compare: target done — "
        f"F1={_metric_summary(target_metrics)}, n={target_metrics.n}"
    )

    checks = check_thresholds(workflow.thresholds, baseline_metrics, target_metrics)

    return Comparison(
        workflow=workflow_name,
        current_model=current,
        target_model=target_model,
        baseline=baseline_metrics,
        target=target_metrics,
        checks=checks,
    )


def save_comparison(comparison: Comparison, cwd: Path | None = None) -> Path:
    cwd = (cwd or Path.cwd()).resolve()
    out_dir = cwd / ".driftless" / "compare"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{comparison.workflow}.json"
    payload = {
        "workflow": comparison.workflow,
        "current_model": comparison.current_model,
        "target_model": comparison.target_model,
        "baseline": asdict(comparison.baseline),
        "target": asdict(comparison.target),
        "checks": [asdict(c) for c in comparison.checks],
        "passed": comparison.passed,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path
