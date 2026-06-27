"""Deterministic data-change regression tests.

The companion to ``test_migration_regression.py``: that one guards the *model*
dependency (a model swap regresses quality until the prompt is repaired); this
one guards the *dataset* dependency (the labels change under a fixed,
well-behaved model until the prompt is refined). Together they prove the harness
covers both ways a prompt goes out of date -- the "two dependencies" framing.

No secrets, no network: the model is simulated and the generator is scripted.
"""

from pathlib import Path

from driftless.engine import MigrationStatus, Objective, run_migration
from scenarios import DataChangeRepair, build_data_change_scenario


def _refine(tmp_path: Path, generator=None):
    wf = build_data_change_scenario(tmp_path)
    return wf, run_migration(
        "ticket_classifier",
        wf,
        wf.model.current,  # refine pins the model -- the dataset is what changed
        generator=generator,
        cwd=tmp_path,
        seed=1,
        objective=Objective.MAXIMIZE,
    )


def test_dataset_change_is_repaired_by_refining_the_prompt(tmp_path: Path):
    wf, result = _refine(tmp_path, generator=DataChangeRepair())

    assert result.status == MigrationStatus.PASS, result.message
    # The model never changed -- only the prompt did.
    assert result.current_model == result.target_model == "stable-model"
    assert result.edited_files == ["prompts/system.txt"]
    # Quality genuinely improved on the new labels.
    assert result.final.f1 > result.baseline.f1
    # The new policy is encoded in the committed prompt.
    committed = (tmp_path / "prompts" / "system.txt").read_text(encoding="utf-8").lower()
    assert "charge-reversal" in committed
    # Holdout validated the refined prompt (no-regression, not the stale bar).
    assert result.holdout is not None
    assert any(c.name.startswith("no_regression_") for c in result.holdout_checks)


def test_data_change_scenario_is_non_trivial(tmp_path: Path):
    # Sanity: the starting prompt genuinely under-performs on the new labels, so
    # the test above isn't vacuous. Refine never BLOCKS, so we assert the dip
    # directly on the baseline metrics.
    wf, result = _refine(tmp_path, generator=None)
    assert result.status == MigrationStatus.NO_CHANGE
    assert result.edited_files == []
    assert result.baseline.f1 < 0.9


def test_data_change_leaves_readonly_app_untouched(tmp_path: Path):
    wf = build_data_change_scenario(tmp_path)
    before = (tmp_path / "app.py").read_text(encoding="utf-8")
    run_migration(
        "ticket_classifier",
        wf,
        wf.model.current,
        generator=DataChangeRepair(),
        cwd=tmp_path,
        seed=1,
        objective=Objective.MAXIMIZE,
    )
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == before
