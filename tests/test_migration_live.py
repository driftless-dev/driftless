"""Live optimizer quality eval (opt-in).

Unlike the deterministic regression, this runs the *real* LLM patch generator
against the same gradeable scenario, so it catches quality regressions in the
actual repair prompt / parsing / candidate strategy. It is nondeterministic and
costs tokens, so it only runs when explicitly enabled:

    DRIFTLESS_LIVE_EVAL=1 OPENAI_API_KEY=... pytest tests/test_migration_live.py

In CI it runs on a schedule / manual dispatch (see
.github/workflows/migration-regression.yml), never on regular PRs.

Each run appends quality metrics to ``.driftless/regression-metrics.jsonl``
(uploaded as a workflow artifact) so scheduled runs can flag degradation over
time, not just pass/fail.
"""

from __future__ import annotations

import os

import pytest

from driftless.engine import MigrationStatus, run_migration
from regression_metrics import record_live_eval
from scenarios import build_scenario


def _live_eval_enabled() -> bool:
    flag = os.environ.get("DRIFTLESS_LIVE_EVAL") or os.environ.get("MM_LIVE_EVAL")
    if flag != "1":
        return False
    return bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))


def _provider_configured(provider: str) -> bool:
    if provider == "openai":
        return bool(os.environ.get("OPENAI_API_KEY"))
    if provider == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    return False


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.skipif(not _live_eval_enabled(), reason="set DRIFTLESS_LIVE_EVAL=1 and a provider API key")
def test_llm_optimizer_recovers_known_regression(tmp_path, provider: str):
    if not _provider_configured(provider):
        pytest.skip(f"{provider} API key not configured")

    from driftless.generators import LLMPatchGenerator

    wf = build_scenario(tmp_path)
    generator = LLMPatchGenerator(provider=provider, num_candidates=2)
    result = run_migration(
        "ticket_classifier", wf, "new-model", generator=generator, cwd=tmp_path, seed=1
    )

    record_live_eval(
        scenario="ticket_classifier",
        provider=provider,
        status=result.status.value,
        iterations=result.iterations,
        final_f1=result.final.f1,
        baseline_f1=result.baseline.f1,
        schema_error_rate=result.final.schema_error_rate,
    )

    assert result.status == MigrationStatus.PASS, result.message
    assert result.final.f1 is not None and result.final.f1 >= 0.9
    assert (result.final.schema_error_rate or 0.0) <= 0.02
