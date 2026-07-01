#!/usr/bin/env python3
"""Compare the latest live-eval metrics against the committed baseline (P0.1)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from regression_metrics import MetricsDegradationError, check_baseline, metrics_path  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=["openai", "anthropic"])
    parser.add_argument(
        "--scenario",
        default="ticket_classifier",
        help="Scenario name recorded in regression-metrics.jsonl",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=ROOT / "tests" / "fixtures" / "live_eval_baseline.json",
    )
    parser.add_argument(
        "--metrics",
        type=Path,
        default=None,
        help="Metrics JSONL path (default: DRIFTLESS_REGRESSION_METRICS or .driftless/...)",
    )
    args = parser.parse_args()

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    path = args.metrics or metrics_path()
    try:
        check_baseline(
            baseline,
            scenario=args.scenario,
            provider=args.provider,
            path=path,
        )
    except MetricsDegradationError as exc:
        print(f"live-eval degradation: {exc}", file=sys.stderr)
        return 1

    print(f"live-eval ok: {args.scenario}/{args.provider} within baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
