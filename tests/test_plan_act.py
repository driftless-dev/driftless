"""P4.3: `plan --act` closes the loop (migrate + open PR/issue).

These exercise the `_act_on_trigger` helper that `plan --act` calls per
actionable trigger, using the deterministic regression scenario so there's no
network and (with create=False) no git/gh side effects.
"""

from pathlib import Path

from driftless.cli import _act_on_trigger
from scenarios import build_scenario


def test_act_dry_run_blocked_migration_previews_issue(tmp_path: Path):
    # No repair generator -> the naive swap regresses -> blocked -> issue.
    wf = build_scenario(tmp_path, current="old-model")
    ok, summary = _act_on_trigger(
        "ticket_classifier",
        wf,
        "new-model",
        generator_name="none",
        create=False,
        seed=1,
        cwd=tmp_path,
    )
    assert ok
    assert "blocked" in summary
    assert "would open issue" in summary
    # Dry run: a report was written but no branch/PR was created.
    assert (tmp_path / ".driftless" / "reports" / "ticket_classifier.md").is_file()
    assert not (tmp_path / ".git").exists()


def test_act_dry_run_passing_migration_previews_pr(tmp_path: Path):
    # Same model id for current/target so the naive swap passes with no edits ->
    # a "ready" PR/issue is previewed without any repair generator.
    wf = build_scenario(tmp_path, current="old-model")
    ok, summary = _act_on_trigger(
        "ticket_classifier",
        wf,
        "old-model",
        generator_name="none",
        create=False,
        seed=1,
        cwd=tmp_path,
    )
    assert ok
    assert "would open" in summary


def test_act_reports_hard_error_as_not_ok(tmp_path: Path):
    wf = build_scenario(tmp_path, current="old-model")
    ok, summary = _act_on_trigger(
        "ticket_classifier",
        wf,
        "new-model",
        generator_name="none",
        create=False,
        seed=1,
        cwd=tmp_path / "does-not-exist",
    )
    assert not ok
    assert "error" in summary
