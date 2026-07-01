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
