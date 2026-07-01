#!/usr/bin/env python3
"""Compare the latest live-eval metrics against the committed baseline (P0.1)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from regression_metrics import (  # noqa: E402
    MetricsDegradationError,
    check_all_baselines,
    check_baseline,
    metrics_path,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=["openai", "anthropic"])
    parser.add_argument(
        "--scenario",
        default=None,
        help="Scenario name recorded in regression-metrics.jsonl (default: all in baseline)",
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
    parser.add_argument(
        "--require-all",
        action="store_true",
        help="Fail when any baseline scenario has no recorded metrics",
    )
    args = parser.parse_args()

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    path = args.metrics or metrics_path()
    try:
        if args.scenario:
            check_baseline(
                baseline,
                scenario=args.scenario,
                provider=args.provider,
                path=path,
            )
            print(f"live-eval ok: {args.scenario}/{args.provider} within baseline")
        else:
            check_all_baselines(
                baseline,
                provider=args.provider,
                path=path,
                require_all=args.require_all,
            )
            print(f"live-eval ok: all recorded scenarios for {args.provider} within baseline")
    except MetricsDegradationError as exc:
        print(f"live-eval degradation: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
