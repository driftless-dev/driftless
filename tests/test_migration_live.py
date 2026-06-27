"""Live optimizer quality eval (opt-in).

Unlike the deterministic regression, this runs the *real* LLM patch generator
against the same gradeable scenario, so it catches quality regressions in the
actual repair prompt / parsing / candidate strategy. It is nondeterministic and
costs tokens, so it only runs when explicitly enabled:

    MM_LIVE_EVAL=1 OPENAI_API_KEY=... pytest tests/test_migration_live.py

In CI it runs on a schedule / manual dispatch (see
.github/workflows/migration-regression.yml), never on regular PRs.
"""

import os

import pytest

from driftless.engine import MigrationStatus, run_migration
from scenarios import build_scenario

_LIVE = os.environ.get("MM_LIVE_EVAL") == "1" and (
    os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
)


@pytest.mark.skipif(
    not _LIVE, reason="set MM_LIVE_EVAL=1 and a provider API key to run the live optimizer eval"
)
def test_llm_optimizer_recovers_known_regression(tmp_path):
    from driftless.generators import LLMPatchGenerator

    wf = build_scenario(tmp_path)
    generator = LLMPatchGenerator(num_candidates=2)
    result = run_migration(
        "ticket_classifier", wf, "new-model", generator=generator, cwd=tmp_path, seed=1
    )

    assert result.status == MigrationStatus.PASS, result.message
    assert result.final.f1 >= 0.9
    assert (result.final.schema_error_rate or 0.0) <= 0.02
