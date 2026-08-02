"""P3.1: `poll --act` closes the loop (refine + open PR/issue) per dataset change."""

from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

from driftless import datastate, github, report
from driftless.cli import _act_on_data_change
from driftless.datastate import load_state
from scenarios import (
    DATA_CHANGE_INITIAL_PROMPT,
    DataChangeRepair,
    build_data_change_scenario,
    build_scenario,
)


def test_poll_act_dry_run_previews_without_side_effects(tmp_path: Path):
    wf = build_scenario(tmp_path, current="old-model")
    ok, summary = _act_on_data_change(
        "ticket_classifier", wf, generator_name="none", create=False, seed=1, cwd=tmp_path
    )
    assert ok
    assert "refine" in summary
    assert "nothing to open" in summary
    assert "open skip" not in summary
    # Dry run: report written, but no git and no recorded state.
    assert (tmp_path / ".driftless" / "reports" / "ticket_classifier.md").is_file()
    assert not (tmp_path / ".git").exists()
    assert load_state(cwd=tmp_path) == {}


def test_poll_act_dry_run_refine_reports_edits_without_writing_files(
    tmp_path: Path, monkeypatch
):
    wf = build_data_change_scenario(tmp_path)
    monkeypatch.setattr(
        "driftless.generators.build_generator", lambda name: DataChangeRepair()
    )

    ok, summary = _act_on_data_change(
        "ticket_classifier",
        wf,
        generator_name="scripted",
        create=False,
        seed=1,
        cwd=tmp_path,
    )

    assert ok
    assert "pass" in summary
    assert "would open pr" in summary
    assert (
        tmp_path / "prompts" / "system.txt"
    ).read_text() == DATA_CHANGE_INITIAL_PROMPT
    assert load_state(cwd=tmp_path) == {}


def test_poll_act_no_change_create_records_state_without_opening(tmp_path: Path):
    wf = build_scenario(tmp_path, current="old-model")
    ok, summary = _act_on_data_change(
        "ticket_classifier", wf, generator_name="none", create=True, seed=1, cwd=tmp_path
    )

    assert ok
    assert "nothing to open" in summary
    assert "open skip" not in summary
    assert load_state(cwd=tmp_path)["ticket_classifier"]
    assert not (tmp_path / ".git").exists()


def test_poll_act_reports_hard_error(tmp_path: Path):
    wf = build_scenario(tmp_path, current="old-model")
    ok, summary = _act_on_data_change(
        "ticket_classifier", wf, generator_name="none", create=False, seed=1,
        cwd=tmp_path / "missing",
    )
    assert not ok
    assert "error" in summary


def test_poll_existing_planned_pr_skips_migration_and_debounces(
    tmp_path: Path, monkeypatch
):
    wf = build_scenario(tmp_path, current="old-model")
    monkeypatch.setattr("driftless.github.current_git_branch", lambda *, cwd: "main")
    monkeypatch.setattr(
        "driftless.github.existing_open_item",
        lambda plan, *, cwd: "PR #9 (https://example.test/9)",
    )
    monkeypatch.setattr(
        "driftless.engine.run_migration",
        lambda *args, **kwargs: pytest.fail("migration must be skipped"),
    )

    ok, summary = _act_on_data_change(
        "ticket_classifier",
        wf,
        generator_name="none",
        create=True,
        seed=1,
        cwd=tmp_path,
        base_branch="main",
    )

    assert ok
    assert "already open PR #9" in summary
    assert load_state(cwd=tmp_path)["ticket_classifier"]


def test_poll_records_state_after_pr_on_base_branch(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    remote = tmp_path / "origin.git"
    repo.mkdir()
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    init = subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if init.returncode != 0 and "Operation not permitted" in init.stderr:
        pytest.skip("sandbox does not permit creating nested git repositories")
    init.check_returncode()
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Driftless Tests"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True)
    wf = build_scenario(repo, current="old-model")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "checkout", "-b", "caller"], cwd=repo, check=True, capture_output=True
    )

    migration_result = SimpleNamespace(status=SimpleNamespace(value="pass"))
    result_dict = {
        "workflow": "ticket_classifier",
        "current_model": "old-model",
        "target_model": "old-model",
        "status": "pass",
        "succeeded": True,
        "edited_files": ["prompts/system.txt"],
    }

    def fake_migration(*args, **kwargs):
        (repo / "prompts" / "system.txt").write_text("refined prompt\n")
        return migration_result

    monkeypatch.setattr("driftless.engine.run_migration", fake_migration)
    monkeypatch.setattr(report, "save_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(report, "result_to_dict", lambda result: result_dict)
    monkeypatch.setattr(report, "render_markdown", lambda *args: "# report")
    monkeypatch.setattr(github, "existing_open_item", lambda plan, *, cwd: None)
    real_run = github._run

    def run_without_external_writes(args, *, cwd):
        if args[:2] == ["git", "push"] or args[0] == "gh":
            return subprocess.CompletedProcess(args, 0, "", "")
        return real_run(args, cwd=cwd)

    monkeypatch.setattr(github, "_run", run_without_external_writes)
    recorded_on: list[str] = []
    real_record = datastate.record_dataset_state

    def record_on_current_branch(name, signature, *, cwd):
        recorded_on.append(
            subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return real_record(name, signature, cwd=cwd)

    monkeypatch.setattr(datastate, "record_dataset_state", record_on_current_branch)

    ok, _ = _act_on_data_change(
        "ticket_classifier",
        wf,
        generator_name="none",
        create=True,
        seed=1,
        cwd=repo,
        base_branch="main",
    )

    assert ok
    assert recorded_on == ["main"]
    assert subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == "caller"
    assert load_state(cwd=repo)["ticket_classifier"]
