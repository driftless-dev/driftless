import json
import subprocess
from pathlib import Path

import yaml

from driftless import github
from driftless.contract import Workflow
from driftless.github import (
    apply_model_change,
    build_pr_plan,
    execute_plan,
    existing_open_item,
)


def _result(status="pass", succeeded=True, edited=None):
    return {
        "workflow": "support_classifier",
        "current_model": "gpt-4o-mini",
        "target_model": "gpt-5-mini",
        "status": status,
        "succeeded": succeeded,
        "edited_files": edited or [],
    }


def test_pass_with_files_builds_pr():
    plan = build_pr_plan(_result(), "REPORT", committed_files=["prompts/p.md", "config/llm.yml"])
    assert plan.kind == "pr"
    assert plan.branch == "driftless/support_classifier-to-gpt-5-mini"
    assert "migrate support_classifier from gpt-4o-mini to gpt-5-mini" in plan.title
    assert plan.body == "REPORT"
    assert plan.files == ["config/llm.yml", "prompts/p.md"]


def test_success_without_files_builds_operational_issue():
    plan = build_pr_plan(_result(status="model_change_only"), "REPORT", committed_files=[])
    assert plan.kind == "issue"
    assert "no code change" in plan.title
    assert "environment variable" in plan.body


def test_blocked_builds_issue():
    plan = build_pr_plan(
        _result(status="blocked", succeeded=False), "REPORT", committed_files=[]
    )
    assert plan.kind == "issue"
    assert "blocked" in plan.title


def test_dry_run_does_not_execute(tmp_path: Path):
    plan = build_pr_plan(_result(), "REPORT", committed_files=["prompts/p.md"])
    actions = execute_plan(plan, cwd=tmp_path, create=False)
    assert any("create branch" in a for a in actions)
    assert "PR created" not in actions  # nothing actually happened


def test_apply_model_change_yaml(tmp_path: Path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "llm.yml").write_text(
        yaml.safe_dump({"workflows": {"support_classifier": {"model": "gpt-4o-mini"}}})
    )
    wf = Workflow.model_validate(
        {
            "run": {"command": "true", "input_path": "i", "output_path": "o"},
            "model": {
                "current": "gpt-4o-mini",
                "config_file": "config/llm.yml",
                "config_path": "workflows.support_classifier.model",
            },
        }
    )
    changed = apply_model_change(wf, "gpt-5-mini", cwd=tmp_path)
    assert changed == "config/llm.yml"
    data = yaml.safe_load((tmp_path / "config" / "llm.yml").read_text())
    assert data["workflows"]["support_classifier"]["model"] == "gpt-5-mini"


def test_apply_model_change_json(tmp_path: Path):
    (tmp_path / "llm.json").write_text(json.dumps({"model": "gpt-4o-mini"}))
    wf = Workflow.model_validate(
        {
            "run": {"command": "true", "input_path": "i", "output_path": "o"},
            "model": {"current": "gpt-4o-mini", "config_file": "llm.json", "config_path": "model"},
        }
    )
    changed = apply_model_change(wf, "gpt-5-mini", cwd=tmp_path)
    assert changed == "llm.json"
    assert json.loads((tmp_path / "llm.json").read_text())["model"] == "gpt-5-mini"


def test_existing_open_item_finds_pr_by_branch(tmp_path, monkeypatch):
    plan = build_pr_plan(_result(), "REPORT", committed_files=["p.md"])
    monkeypatch.setattr(
        github, "_gh_json", lambda args, *, cwd: [{"number": 7, "url": "http://x/7"}]
    )
    assert "PR #7" in (existing_open_item(plan, cwd=tmp_path) or "")


def test_existing_open_item_matches_issue_title_exactly(tmp_path, monkeypatch):
    plan = build_pr_plan(
        _result(status="blocked", succeeded=False), "REPORT", committed_files=[]
    )
    rows = [{"number": 3, "title": "unrelated"}, {"number": 9, "title": plan.title, "url": "u"}]
    monkeypatch.setattr(github, "_gh_json", lambda args, *, cwd: rows)
    assert "issue #9" in (existing_open_item(plan, cwd=tmp_path) or "")


def test_existing_open_item_none_when_no_match(tmp_path, monkeypatch):
    plan = build_pr_plan(_result(), "REPORT", committed_files=["p.md"])
    monkeypatch.setattr(github, "_gh_json", lambda args, *, cwd: [])
    assert existing_open_item(plan, cwd=tmp_path) is None


def test_gh_json_none_when_gh_missing(tmp_path, monkeypatch):
    # A missing/failed gh must not block creation: best-effort returns None.
    plan = build_pr_plan(_result(), "REPORT", committed_files=["p.md"])
    monkeypatch.setattr(github, "_gh_json", lambda args, *, cwd: None)
    assert existing_open_item(plan, cwd=tmp_path) is None


def test_execute_plan_dedupes_against_open_item(tmp_path, monkeypatch):
    plan = build_pr_plan(_result(), "REPORT", committed_files=["p.md"])

    def _boom(*a, **k):
        raise AssertionError("must not run git/gh when a duplicate exists")

    monkeypatch.setattr(github, "existing_open_item", lambda plan, *, cwd: "PR #7")
    monkeypatch.setattr(github, "_run", _boom)
    actions = execute_plan(plan, cwd=tmp_path, create=True, dedupe=True)
    assert any("skipped: already open PR #7" in a for a in actions)


def test_execute_plan_no_dedupe_when_disabled(tmp_path, monkeypatch):
    # With dedupe off we should not even query for existing items.
    plan = build_pr_plan(_result(), "REPORT", committed_files=["p.md"])
    monkeypatch.setattr(
        github, "existing_open_item", lambda *a, **k: (_ for _ in ()).throw(AssertionError())
    )
    actions = execute_plan(plan, cwd=tmp_path, create=False, dedupe=False)
    assert any("create branch" in a for a in actions)


def test_execute_plan_create_pr_runs_git_and_gh(tmp_path, monkeypatch):
    """create=True must invoke the full git checkout -> commit -> push -> gh pr path."""
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "p.md").write_text("hello\n")
    plan = build_pr_plan(_result(), "REPORT BODY", committed_files=["prompts/p.md"])
    calls: list[list[str]] = []

    def fake_run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(github, "_run", fake_run)
    monkeypatch.setattr(github, "existing_open_item", lambda plan, *, cwd: None)

    actions = execute_plan(plan, cwd=tmp_path, create=True, push=True, dedupe=True)

    assert actions[-1] == "PR created"
    assert calls[0] == ["git", "checkout", "-b", plan.branch]
    assert calls[1] == ["git", "add", "prompts/p.md"]
    assert calls[2][:2] == ["git", "commit"]
    assert calls[2][3] == plan.commit_message
    assert calls[3] == ["git", "push", "-u", "origin", plan.branch]
    assert calls[4][:3] == ["gh", "pr", "create"]
    assert plan.title in calls[4]
    assert "--body-file" in calls[4]


def test_execute_plan_create_pr_no_push_skips_push(tmp_path, monkeypatch):
    plan = build_pr_plan(_result(), "REPORT", committed_files=["p.md"])
    calls: list[list[str]] = []

    def fake_run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(github, "_run", fake_run)
    monkeypatch.setattr(github, "existing_open_item", lambda plan, *, cwd: None)

    execute_plan(plan, cwd=tmp_path, create=True, push=False, dedupe=False)

    assert not any(a[:2] == ["git", "push"] for a in calls)
    assert calls[-1][:3] == ["gh", "pr", "create"]


def test_execute_plan_create_issue_runs_gh(tmp_path, monkeypatch):
    plan = build_pr_plan(
        _result(status="blocked", succeeded=False), "ISSUE BODY", committed_files=[]
    )
    calls: list[list[str]] = []

    def fake_run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(github, "_run", fake_run)

    actions = execute_plan(plan, cwd=tmp_path, create=True)

    assert actions[-1] == "issue created"
    assert calls[0][:3] == ["gh", "issue", "create"]
    assert plan.title in calls[0]
    assert "--body-file" in calls[0]


def test_apply_model_change_env_var_returns_none(tmp_path: Path):
    wf = Workflow.model_validate(
        {
            "run": {"command": "true", "input_path": "i", "output_path": "o"},
            "model": {"current": "gpt-4o-mini", "env_var": "M"},
        }
    )
    assert apply_model_change(wf, "gpt-5-mini", cwd=tmp_path) is None
