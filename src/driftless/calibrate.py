"""Baseline-derived threshold suggestions (the educational half of P2.2).

A first-time user can't guess reasonable ``min_f1`` / ``max_schema_error_rate``
values. ``suggest_thresholds`` turns measured baseline metrics into a starting
``thresholds:`` block (achieved metric minus a safety margin), which the user can
accept or edit. Pure and reused by the ``calibrate`` CLI command.
"""

from __future__ import annotations

from .evaluation import Metrics

DEFAULT_MARGIN = 0.03


def suggest_thresholds(metrics: Metrics, *, margin: float = DEFAULT_MARGIN) -> dict:
    """Suggested absolute thresholds grounded in measured baseline metrics.

    Only emits a key when the underlying metric was actually measured, so we
    never invent a bar for something we couldn't evaluate.
    """
    out: dict[str, float] = {}
    if metrics.f1 is not None:
        out["min_f1"] = round(max(0.0, metrics.f1 - margin), 3)
    if metrics.score is not None:
        out["min_score"] = round(max(0.0, metrics.score - margin), 3)
    if metrics.precision is not None:
        out["min_precision"] = round(max(0.0, metrics.precision - margin), 3)
    if metrics.recall is not None:
        out["min_recall"] = round(max(0.0, metrics.recall - margin), 3)
    if metrics.schema_error_rate is not None:
        out["max_schema_error_rate"] = round(min(1.0, metrics.schema_error_rate + margin), 3)
    return out
