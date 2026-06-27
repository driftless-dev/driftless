"""Tests for the dataset-change refinement path (`refine` / MAXIMIZE objective).

Reuses the deterministic regression scenario, but pins the model and runs the
engine in MAXIMIZE mode: the dataset is the thing that "changed", so the loop
should push quality up within budget, validate on holdout, commit the improved
prompt, and propose fresh thresholds -- without ever gating on the stale ones.
"""

from pathlib import Path

from driftless.engine import MigrationStatus, Objective, run_migration
from scenarios import ScriptedRepair, build_scenario


def _refine(tmp_path: Path, current: str, generator=None):
    wf = build_scenario(tmp_path, current=current)
    return wf, run_migration(
        "ticket_classifier",
        wf,
        wf.model.current,  # model is pinned in refine
        generator=generator,
        cwd=tmp_path,
        seed=1,
        objective=Objective.MAXIMIZE,
    )


def test_refine_improves_and_commits_under_pinned_model(tmp_path: Path):
    # The pinned "new-model" regresses on the (new) dataset until the prompt is
    # repaired. MAXIMIZE should drive quality up and commit the refined prompt.
    wf, result = _refine(tmp_path, "new-model", generator=ScriptedRepair())

    assert result.status == MigrationStatus.PASS, result.message
    assert result.current_model == result.target_model == "new-model"
    assert result.final.f1 > result.baseline.f1
    # The refined prompt is the deliverable -> it is committed.
    assert result.edited_files == ["prompts/system.txt"]
    committed = (tmp_path / "prompts" / "system.txt").read_text(encoding="utf-8").lower()
    assert "raw json" in committed and "money-back" in committed


def test_refine_does_not_gate_on_stale_thresholds(tmp_path: Path):
    # Even with no repair generator, refine never returns BLOCKED: stale
    # thresholds don't apply. The best (here, unchanged) prompt is kept.
    wf, result = _refine(tmp_path, "new-model", generator=None)
    assert result.status == MigrationStatus.NO_CHANGE
    assert result.edited_files == []


def test_refine_suggests_thresholds_from_holdout(tmp_path: Path):
    wf, result = _refine(tmp_path, "new-model", generator=ScriptedRepair())
    assert result.holdout is not None
    # Suggested thresholds are derived from achieved holdout metrics.
    assert "min_f1" in result.suggested_thresholds
    assert result.suggested_thresholds["min_f1"] <= (result.holdout.f1 or 0.0)
    assert "max_schema_error_rate" in result.suggested_thresholds


def test_refine_no_change_when_already_optimal(tmp_path: Path):
    # The well-behaved "old-model" already scores F1==1.0 on its dataset, so no
    # candidate can beat it -> NO_CHANGE, nothing committed, but still a fresh
    # threshold suggestion grounded in the achieved metrics.
    wf, result = _refine(tmp_path, "old-model", generator=ScriptedRepair())
    assert result.status == MigrationStatus.NO_CHANGE
    assert result.edited_files == []
    assert result.suggested_thresholds.get("min_f1", 0.0) > 0.9


def test_refine_holdout_is_no_regression_not_absolute(tmp_path: Path):
    # In refine the holdout checks compare refined-vs-current (no-regression),
    # never the stale absolute bar.
    wf, result = _refine(tmp_path, "new-model", generator=ScriptedRepair())
    names = {c.name for c in result.holdout_checks}
    assert any(n.startswith("no_regression_") for n in names)


def test_migrate_path_is_unchanged_by_default_objective(tmp_path: Path):
    # Guard: the default objective still behaves like migrate (BLOCKED without a
    # generator on a genuine regression).
    wf = build_scenario(tmp_path, current="old-model")
    result = run_migration("ticket_classifier", wf, "new-model", cwd=tmp_path, seed=1)
    assert result.status == MigrationStatus.BLOCKED
