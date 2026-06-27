"""P3.1: `poll --act` closes the loop (refine + open PR/issue) per dataset change."""

from pathlib import Path

from driftless.cli import _act_on_data_change
from driftless.datastate import load_state
from scenarios import build_scenario


def test_poll_act_dry_run_previews_without_side_effects(tmp_path: Path):
    wf = build_scenario(tmp_path, current="old-model")
    ok, summary = _act_on_data_change(
        "ticket_classifier", wf, generator_name="none", create=False, seed=1, cwd=tmp_path
    )
    assert ok
    assert "refine" in summary
    assert "would open" in summary
    # Dry run: report written, but no git and no recorded state.
    assert (tmp_path / ".driftless" / "reports" / "ticket_classifier.md").is_file()
    assert not (tmp_path / ".git").exists()
    assert load_state(cwd=tmp_path) == {}


def test_poll_act_reports_hard_error(tmp_path: Path):
    wf = build_scenario(tmp_path, current="old-model")
    ok, summary = _act_on_data_change(
        "ticket_classifier", wf, generator_name="none", create=False, seed=1,
        cwd=tmp_path / "missing",
    )
    assert not ok
    assert "error" in summary
