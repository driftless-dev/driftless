"""Live optimizer quality eval (opt-in).

Unlike the deterministic regression, this runs the *real* LLM patch generator
against shared gradeable scenarios, so it catches quality regressions in the
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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from driftless.engine import MigrationResult, MigrationStatus, run_migration
from regression_metrics import record_live_eval
from scenarios import (
    build_extraction_scenario,
    build_hallucination_scenario,
    build_judge_scenario,
    build_scenario,
    build_score_scenario,
    build_verbosity_scenario,
)


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


@dataclass(frozen=True)
class LiveScenario:
    name: str
    workflow: str
    build: Callable[[Path], Any]
    target_model: str
    min_f1: float | None = None
    min_score: float | None = None
    max_schema_error_rate: float | None = 0.02


LIVE_SCENARIOS = [
    LiveScenario(
        name="ticket_classifier",
        workflow="ticket_classifier",
        build=build_scenario,
        target_model="new-model",
        min_f1=0.9,
    ),
    LiveScenario(
        name="ticket_extractor",
        workflow="ticket_extractor",
        build=build_extraction_scenario,
        target_model="new-model",
        min_f1=0.9,
        max_schema_error_rate=None,
    ),
    LiveScenario(
        name="qa_scorer",
        workflow="qa_scorer",
        build=build_score_scenario,
        target_model="new-model",
        min_score=0.9,
    ),
    LiveScenario(
        name="verbosity_drift",
        workflow="ticket_classifier",
        build=build_verbosity_scenario,
        target_model="new-model",
        min_f1=0.9,
    ),
    LiveScenario(
        name="label_hallucination",
        workflow="ticket_classifier",
        build=build_hallucination_scenario,
        target_model="new-model",
        min_f1=0.9,
    ),
    LiveScenario(
        name="summarizer_judge",
        workflow="summarizer",
        build=build_judge_scenario,
        target_model="new-model",
        min_score=0.9,
    ),
]


def _assert_within_floor(scenario: LiveScenario, result: MigrationResult) -> None:
    assert result.status == MigrationStatus.PASS, result.message
    if scenario.min_f1 is not None:
        assert result.final.f1 is not None and result.final.f1 >= scenario.min_f1
    if scenario.min_score is not None:
        assert result.final.score is not None and result.final.score >= scenario.min_score
    if scenario.max_schema_error_rate is not None:
        assert (result.final.schema_error_rate or 0.0) <= scenario.max_schema_error_rate


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("scenario", LIVE_SCENARIOS, ids=[s.name for s in LIVE_SCENARIOS])
@pytest.mark.skipif(not _live_eval_enabled(), reason="set DRIFTLESS_LIVE_EVAL=1 and a provider API key")
def test_llm_optimizer_recovers_regression(tmp_path: Path, provider: str, scenario: LiveScenario):
    if not _provider_configured(provider):
        pytest.skip(f"{provider} API key not configured")

    from driftless.generators import LLMPatchGenerator

    wf = scenario.build(tmp_path)
    generator = LLMPatchGenerator(provider=provider, num_candidates=2)
    result = run_migration(
        scenario.workflow,
        wf,
        scenario.target_model,
        generator=generator,
        cwd=tmp_path,
        seed=1,
    )

    record_live_eval(
        scenario=scenario.name,
        provider=provider,
        status=result.status.value,
        iterations=result.iterations,
        final_f1=result.final.f1,
        baseline_f1=result.baseline.f1,
        final_score=result.final.score,
        baseline_score=result.baseline.score,
        schema_error_rate=result.final.schema_error_rate,
    )

    _assert_within_floor(scenario, result)
