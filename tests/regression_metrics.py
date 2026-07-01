"""Append-only metrics log for live regression evals (P0.1)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_METRICS_PATH = Path(".driftless/regression-metrics.jsonl")


def metrics_path() -> Path:
    raw = os.environ.get("DRIFTLESS_REGRESSION_METRICS", "").strip()
    return Path(raw) if raw else DEFAULT_METRICS_PATH


def record_live_eval(
    *,
    scenario: str,
    provider: str,
    status: str,
    iterations: int,
    final_f1: float | None,
    baseline_f1: float | None = None,
    schema_error_rate: float | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Append one JSON line with run quality metrics for trend tracking."""
    entry: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "scenario": scenario,
        "provider": provider,
        "status": status,
        "iterations": iterations,
        "final_f1": final_f1,
        "baseline_f1": baseline_f1,
        "schema_error_rate": schema_error_rate,
    }
    if extra:
        entry.update(extra)

    path = metrics_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
    return path


def latest_metric(
    path: Path | None = None,
    *,
    scenario: str,
    provider: str,
) -> dict[str, Any] | None:
    """Return the most recent metrics entry for ``scenario`` + ``provider``."""
    path = path or metrics_path()
    if not path.is_file():
        return None
    latest: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("scenario") == scenario and entry.get("provider") == provider:
            latest = entry
    return latest


class MetricsDegradationError(Exception):
    """Raised when a live eval regresses against the committed baseline."""


def check_baseline(
    baseline: dict[str, Any],
    *,
    scenario: str,
    provider: str,
    path: Path | None = None,
) -> None:
    """Fail if the latest live-eval metrics violate the baseline floor."""
    spec = baseline.get(scenario, {}).get(provider)
    if spec is None:
        return

    entry = latest_metric(path, scenario=scenario, provider=provider)
    if entry is None:
        raise MetricsDegradationError(f"no metrics recorded for {scenario}/{provider}")

    issues: list[str] = []
    required_status = spec.get("require_status")
    if required_status and entry.get("status") != required_status:
        issues.append(f"status {entry.get('status')!r} != {required_status!r}")

    min_f1 = spec.get("min_final_f1")
    final_f1 = entry.get("final_f1")
    if min_f1 is not None and (final_f1 is None or final_f1 < min_f1):
        issues.append(f"final_f1 {final_f1} below floor {min_f1}")

    max_iterations = spec.get("max_iterations")
    iterations = entry.get("iterations")
    if max_iterations is not None and iterations is not None and iterations > max_iterations:
        issues.append(f"iterations {iterations} above ceiling {max_iterations}")

    if issues:
        raise MetricsDegradationError("; ".join(issues))
