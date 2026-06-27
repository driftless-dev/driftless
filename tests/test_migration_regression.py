"""Deterministic migration regression tests.

These run on every push (no secrets, no network) and assert that a *known*
model regression is still driven back to passing quality by the engine. If a
change to the loop, evaluation, clustering, or holdout gating breaks repair,
these fail. They are the floor under the project's core value.
"""

from pathlib import Path

from driftless.engine import MigrationStatus, run_migration
from scenarios import ScriptedRepair, build_scenario


def test_known_regression_is_repaired_to_pass(tmp_path: Path):
    wf = build_scenario(tmp_path)
    result = run_migration(
        "ticket_classifier", wf, "new-model", generator=ScriptedRepair(), cwd=tmp_path, seed=1
    )

    assert result.status == MigrationStatus.PASS, result.message
    assert result.final.f1 >= 0.9
    assert (result.final.schema_error_rate or 0.0) <= 0.02
    # Both distinct fixes were needed -> the loop genuinely iterated.
    assert result.iterations >= 2
    # Only the editable file changed, and it carries both repairs.
    assert result.edited_files == ["prompts/system.txt"]
    committed = (tmp_path / "prompts" / "system.txt").read_text(encoding="utf-8").lower()
    assert "raw json" in committed and "money-back" in committed
    # Holdout validation actually happened and passed.
    assert result.holdout is not None
    assert all(c.passed for c in result.holdout_checks)
    # The experiment log records the trajectory: at least two accepted edits.
    assert sum(1 for a in result.experiment_log if a.accepted) >= 2


def test_scenario_is_non_trivial_blocks_without_repair(tmp_path: Path):
    # Sanity: with no repair generator, the regression must NOT pass -- otherwise
    # the test above would be vacuous.
    wf = build_scenario(tmp_path)
    result = run_migration("ticket_classifier", wf, "new-model", cwd=tmp_path, seed=1)
    assert result.status == MigrationStatus.BLOCKED


def test_readonly_files_untouched(tmp_path: Path):
    wf = build_scenario(tmp_path)
    before = (tmp_path / "app.py").read_text(encoding="utf-8")
    run_migration(
        "ticket_classifier", wf, "new-model", generator=ScriptedRepair(), cwd=tmp_path, seed=1
    )
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == before


def test_same_family_swap_is_model_change_only(tmp_path: Path):
    # Migrating within the well-behaved family needs no repair at all.
    wf = build_scenario(tmp_path)
    result = run_migration("ticket_classifier", wf, "old-model-v2", cwd=tmp_path, seed=1)
    assert result.status == MigrationStatus.MODEL_CHANGE_ONLY
    assert result.edited_files == []


def test_repair_works_with_reordered_outputs(tmp_path: Path):
    # Outputs come back in reversed order. id-based alignment must still grade
    # correctly, so the same known regression is repaired to PASS. (Positional
    # alignment would mis-grade and the loop would chase phantom failures.)
    wf = build_scenario(tmp_path, shuffle_outputs=True)
    result = run_migration(
        "ticket_classifier", wf, "new-model", generator=ScriptedRepair(), cwd=tmp_path, seed=1
    )
    assert result.status == MigrationStatus.PASS, result.message
    assert result.final.f1 >= 0.9


def test_small_dataset_warning_is_surfaced(tmp_path: Path):
    # The scenario has 24 examples (< MIN_TOTAL_EXAMPLES), so every run should
    # carry a low-confidence caveat for the reviewer.
    wf = build_scenario(tmp_path)
    result = run_migration(
        "ticket_classifier", wf, "new-model", generator=ScriptedRepair(), cwd=tmp_path, seed=1
    )
    assert any("Small dataset" in w for w in result.warnings)


def test_readonly_context_reaches_the_generator(tmp_path: Path):
    # files.context contents must be threaded to the generator (read-only),
    # without ever being editable.
    wf = build_scenario(tmp_path)
    wf.files.context = ["app.py"]  # surface the parser/app as read-only context
    seen: dict[str, str] = {}

    class CapturingRepair(ScriptedRepair):
        def generate(self, context):
            seen.update(context.context_files)
            return super().generate(context)

    run_migration(
        "ticket_classifier", wf, "new-model", generator=CapturingRepair(), cwd=tmp_path, seed=1
    )
    assert "app.py" in seen
    assert "def base(" in seen["app.py"]
