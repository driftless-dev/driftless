import json
import subprocess
from pathlib import Path

import pytest
import yaml

from driftless import github
from driftless.contract import Workflow
from driftless.errors import DriftlessError
from driftless.github import (
    apply_contract_current,
    apply_model_change,
    build_pr_plan,
    execute_plan,
    existing_open_item,
    planned_model_files,
    runtime_model_note,
)


@pytest.fixture
def mocked_git_context(monkeypatch):
    monkeypatch.setattr(github, "current_git_branch", lambda *, cwd: "main")
    monkeypatch.setattr(
        github, "ensure_pr_branch_available", lambda plan, *, cwd, push: None
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
    assert plan.draft is True
    assert plan.workflow == "support_classifier"
    assert plan.target_model == "gpt-5-mini"


def test_branch_components_are_sanitized_deterministically():
    result = _result()
    result["workflow"] = "support/classifier @ prod"
    result["target_model"] = "openai/gpt-5:mini@2026.07"

    first = build_pr_plan(result, "REPORT", committed_files=["prompt.md"])
    second = build_pr_plan(result, "REPORT", committed_files=["prompt.md"])

    assert first.branch.startswith("driftless/support-classifier-prod-")
    assert "-to-openai-gpt-5-mini-2026-07-" in first.branch
    assert second.branch == first.branch


def test_sanitized_branch_components_resist_collisions():
    slash = _result()
    slash["workflow"] = "foo/bar"
    hyphen = _result()
    hyphen["workflow"] = "foo-bar"

    slash_plan = build_pr_plan(slash, "REPORT", committed_files=["prompt.md"])
    hyphen_plan = build_pr_plan(hyphen, "REPORT", committed_files=["prompt.md"])

    assert slash_plan.branch != hyphen_plan.branch
    assert "foo-bar-" in slash_plan.branch
    assert "foo-bar-to-" in hyphen_plan.branch


def test_no_change_builds_skip_plan_and_never_executes(tmp_path, monkeypatch):
    plan = build_pr_plan(
        _result(status="no_change", succeeded=True), "REPORT", committed_files=[]
    )
    assert plan.kind == "skip"

    monkeypatch.setattr(
        github,
        "_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not execute")),
    )
    monkeypatch.setattr(
        github,
        "existing_open_item",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not query")),
    )
    assert execute_plan(plan, cwd=tmp_path, create=False) == [
        "no changes; no PR or issue needed"
    ]
    assert execute_plan(plan, cwd=tmp_path, create=True) == [
        "no changes; no PR or issue needed"
    ]


def test_success_without_files_builds_operational_issue():
    plan = build_pr_plan(_result(status="model_change_only"), "REPORT", committed_files=[])
    assert plan.kind == "issue"
    assert "no code change" in plan.title
    assert "environment variable" in plan.body


def test_success_with_contract_file_builds_pr_and_runtime_note():
    note = "This update sets `model.current` in the Driftless contract to `gpt-5-mini`."
    plan = build_pr_plan(
        _result(status="model_change_only"),
        "REPORT",
        committed_files=["driftless.yml"],
        runtime_note=note,
    )
    assert plan.kind == "pr"
    assert "driftless.yml" in plan.files
    assert note in plan.body
    assert "REPORT" in plan.body


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


def test_model_config_path_must_stay_inside_repo(tmp_path: Path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.yml"
    outside.write_text("model: gpt-4o-mini\n")
    wf = Workflow.model_validate(
        {
            "run": {"command": "true", "input_path": "i", "output_path": "o"},
            "model": {
                "current": "gpt-4o-mini",
                "config_file": f"../{outside.name}",
                "config_path": "model",
            },
        }
    )

    with pytest.raises(DriftlessError, match="escapes the repository"):
        apply_model_change(wf, "gpt-5-mini", cwd=tmp_path)

    assert yaml.safe_load(outside.read_text())["model"] == "gpt-4o-mini"


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


def test_existing_open_item_fails_closed_when_gh_query_fails(tmp_path, monkeypatch):
    plan = build_pr_plan(_result(), "REPORT", committed_files=["p.md"])
    monkeypatch.setattr(github, "_gh_json", lambda args, *, cwd: None)
    with pytest.raises(DriftlessError, match="could not check"):
        existing_open_item(plan, cwd=tmp_path)


def test_execute_plan_create_fails_closed_when_dedupe_query_fails(tmp_path, monkeypatch):
    plan = build_pr_plan(_result(), "REPORT", committed_files=["p.md"])
    monkeypatch.setattr(github, "_gh_json", lambda args, *, cwd: None)
    monkeypatch.setattr(
        github,
        "_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not create")),
    )

    with pytest.raises(DriftlessError, match="could not check"):
        execute_plan(plan, cwd=tmp_path, create=True, dedupe=True)


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


def test_execute_plan_create_pr_runs_git_and_gh(
    tmp_path, monkeypatch, mocked_git_context
):
    """create=True must invoke the full git checkout -> commit -> push -> gh pr path."""
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "p.md").write_text("hello\n")
    plan = build_pr_plan(_result(), "REPORT BODY", committed_files=["prompts/p.md"])
    events: list[list[str] | str] = []

    def fake_run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        events.append(args)
        stdout = ""
        if args[:3] == ["gh", "pr", "create"]:
            stdout = "https://github.com/acme/app/pull/9\n"
        return subprocess.CompletedProcess(args, 0, stdout, "")

    monkeypatch.setattr(github, "_run", fake_run)
    monkeypatch.setattr(github, "existing_open_item", lambda plan, *, cwd: None)
    monkeypatch.setattr(github, "find_open_blocked_issue", lambda *a, **k: None)

    actions = execute_plan(
        plan,
        cwd=tmp_path,
        create=True,
        push=True,
        dedupe=True,
        prepare_files=lambda: events.append("prepare files"),
    )

    assert actions[-1] == "PR created: https://github.com/acme/app/pull/9"
    calls = [event for event in events if isinstance(event, list)]
    assert calls[0] == ["git", "checkout", "-b", plan.branch, "main"]
    assert events[1] == "prepare files"
    assert calls[1] == ["git", "add", "prompts/p.md"]
    assert calls[2][:2] == ["git", "commit"]
    assert calls[2][3] == plan.commit_message
    assert calls[3] == ["git", "push", "-u", "origin", plan.branch]
    assert calls[4][:3] == ["gh", "pr", "create"]
    assert plan.title in calls[4]
    assert "--body-file" in calls[4]
    assert "--draft" in calls[4]


@pytest.mark.parametrize("failing_command", [("git", "add"), ("git", "commit")])
def test_execute_plan_rolls_back_and_unstages_precommit_failure(
    tmp_path, monkeypatch, failing_command, mocked_git_context
):
    plan = build_pr_plan(_result(), "REPORT", committed_files=["p.md"])
    events: list[object] = []

    def fake_run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        events.append(args)
        if tuple(args[:2]) == failing_command:
            raise DriftlessError("expected failure")
        return subprocess.CompletedProcess(args, 0, "", "")

    def prepare():
        events.append("prepare")

        def rollback():
            events.append("rollback")

        return rollback

    monkeypatch.setattr(github, "_run", fake_run)

    with pytest.raises(DriftlessError, match="expected failure"):
        execute_plan(
            plan, cwd=tmp_path, create=True, dedupe=False, prepare_files=prepare
        )

    assert events[0] == ["git", "checkout", "-b", plan.branch, "main"]
    assert events[1] == "prepare"
    assert "rollback" in events
    assert ["git", "reset", "--", "p.md"] in events
    assert events[-1] == ["git", "branch", "-D", plan.branch]


def test_execute_plan_discards_new_local_branch_when_push_fails(
    tmp_path, monkeypatch, mocked_git_context
):
    plan = build_pr_plan(_result(), "REPORT", committed_files=["p.md"])
    events: list[object] = []

    def fake_run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        events.append(args)
        if args[:2] == ["git", "push"]:
            raise DriftlessError("push failed")
        return subprocess.CompletedProcess(args, 0, "", "")

    def prepare():
        events.append("prepare")
        return lambda: events.append("rollback")

    monkeypatch.setattr(github, "_run", fake_run)

    with pytest.raises(DriftlessError, match="push failed"):
        execute_plan(
            plan, cwd=tmp_path, create=True, dedupe=False, prepare_files=prepare
        )

    assert "rollback" not in events
    assert not any(
        isinstance(event, list) and event[:2] == ["git", "reset"]
        for event in events
    )
    assert events[-1] == ["git", "branch", "-D", plan.branch]


def test_execute_plan_removes_new_remote_branch_when_pr_creation_fails(
    tmp_path, monkeypatch, mocked_git_context
):
    plan = build_pr_plan(_result(), "REPORT", committed_files=["p.md"])
    events: list[list[str]] = []

    def fake_run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        events.append(args)
        if args[:3] == ["gh", "pr", "create"]:
            raise DriftlessError("PR creation failed")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(github, "_run", fake_run)
    monkeypatch.setattr(github, "existing_open_item", lambda plan, *, cwd: None)

    with pytest.raises(DriftlessError, match="PR creation failed"):
        execute_plan(plan, cwd=tmp_path, create=True, dedupe=False, push=True)

    assert ["git", "push", "-u", "origin", plan.branch] in events
    assert ["git", "push", "origin", "--delete", plan.branch] in events
    assert events[-1] == ["git", "branch", "-D", plan.branch]


def test_execute_plan_keeps_local_recovery_branch_if_remote_cleanup_fails(
    tmp_path, monkeypatch, mocked_git_context
):
    plan = build_pr_plan(_result(), "REPORT", committed_files=["p.md"])
    events: list[list[str]] = []

    def fake_run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        events.append(args)
        if args[:3] == ["gh", "pr", "create"]:
            raise DriftlessError("PR creation failed")
        if args[:4] == ["git", "push", "origin", "--delete"]:
            raise DriftlessError("remote cleanup failed")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(github, "_run", fake_run)
    monkeypatch.setattr(github, "existing_open_item", lambda plan, *, cwd: None)

    with pytest.raises(DriftlessError, match="PR creation failed"):
        execute_plan(plan, cwd=tmp_path, create=True, dedupe=False, push=True)

    assert ["git", "push", "origin", "--delete", plan.branch] in events
    assert ["git", "branch", "-D", plan.branch] not in events


def test_execute_plan_accepts_pr_confirmed_after_create_response_is_lost(
    tmp_path, monkeypatch, mocked_git_context
):
    plan = build_pr_plan(_result(), "REPORT", committed_files=["p.md"])
    events: list[list[str]] = []

    def fake_run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        events.append(args)
        if args[:3] == ["gh", "pr", "create"]:
            raise DriftlessError("connection lost after request")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(github, "_run", fake_run)
    monkeypatch.setattr(
        github,
        "existing_open_item",
        lambda plan, *, cwd: "PR #42 (https://example.test/42)",
    )

    actions = execute_plan(
        plan, cwd=tmp_path, create=True, dedupe=False, push=True
    )

    assert actions[-1] == "PR created"
    assert ["git", "push", "origin", "--delete", plan.branch] not in events
    assert ["git", "branch", "-D", plan.branch] not in events


def test_execute_plan_preserves_branches_when_pr_recovery_check_is_uncertain(
    tmp_path, monkeypatch, mocked_git_context
):
    plan = build_pr_plan(_result(), "REPORT", committed_files=["p.md"])
    events: list[list[str]] = []

    def fake_run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        events.append(args)
        if args[:3] == ["gh", "pr", "create"]:
            raise DriftlessError("connection lost after request")
        return subprocess.CompletedProcess(args, 0, "", "")

    def uncertain_existing_item(plan, *, cwd):
        raise DriftlessError("GitHub query unavailable")

    monkeypatch.setattr(github, "_run", fake_run)
    monkeypatch.setattr(github, "existing_open_item", uncertain_existing_item)

    with pytest.raises(DriftlessError, match="connection lost after request"):
        execute_plan(plan, cwd=tmp_path, create=True, dedupe=False, push=True)

    assert ["git", "push", "origin", "--delete", plan.branch] not in events
    assert ["git", "branch", "-D", plan.branch] not in events


def test_execute_plan_dedupe_skips_file_preparation(tmp_path, monkeypatch):
    plan = build_pr_plan(_result(), "REPORT", committed_files=["p.md"])
    monkeypatch.setattr(github, "existing_open_item", lambda plan, *, cwd: "PR #7")

    prepared = False

    def prepare() -> None:
        nonlocal prepared
        prepared = True

    actions = execute_plan(
        plan,
        cwd=tmp_path,
        create=True,
        dedupe=True,
        prepare_files=prepare,
    )

    assert actions == ["skipped: already open PR #7"]
    assert not prepared


def test_execute_plan_create_pr_no_push_skips_push(
    tmp_path, monkeypatch, mocked_git_context
):
    plan = build_pr_plan(_result(), "REPORT", committed_files=["p.md"])
    calls: list[list[str]] = []

    def fake_run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(github, "_run", fake_run)
    monkeypatch.setattr(github, "existing_open_item", lambda plan, *, cwd: None)
    monkeypatch.setattr(github, "find_open_blocked_issue", lambda *a, **k: None)

    execute_plan(plan, cwd=tmp_path, create=True, push=False, dedupe=False)

    assert not any(a[:2] == ["git", "push"] for a in calls)
    assert calls[-1][:3] == ["gh", "pr", "create"]


def test_execute_plan_closes_matching_blocked_issue(
    tmp_path, monkeypatch, mocked_git_context
):
    (tmp_path / "p.md").write_text("hello\n")
    plan = build_pr_plan(_result(), "REPORT", committed_files=["p.md"])
    calls: list[list[str]] = []
    bodies: list[str] = []

    def fake_run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        calls.append(args)
        stdout = ""
        if args[:3] == ["gh", "pr", "create"]:
            body_file = Path(args[args.index("--body-file") + 1])
            bodies.append(body_file.read_text(encoding="utf-8"))
            stdout = "https://github.com/acme/app/pull/2\n"
        return subprocess.CompletedProcess(args, 0, stdout, "")

    monkeypatch.setattr(github, "_run", fake_run)
    monkeypatch.setattr(github, "existing_open_item", lambda plan, *, cwd: None)
    monkeypatch.setattr(
        github,
        "find_open_blocked_issue",
        lambda *a, **k: {
            "number": 1,
            "title": "driftless: migration blocked: support_classifier -> gpt-5-mini",
        },
    )

    actions = execute_plan(plan, cwd=tmp_path, create=True, dedupe=True)

    assert "closed blocked issue #1" in actions
    assert any(c[:4] == ["gh", "issue", "comment", "1"] for c in calls)
    assert any(c[:4] == ["gh", "issue", "close", "1"] for c in calls)
    assert bodies and "Supersedes #1" in bodies[0]


def test_execute_plan_create_issue_runs_gh(tmp_path, monkeypatch):
    plan = build_pr_plan(
        _result(status="blocked", succeeded=False), "ISSUE BODY", committed_files=[]
    )
    calls: list[list[str]] = []

    def fake_run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        calls.append(args)
        stdout = ""
        if args[:3] == ["gh", "issue", "create"]:
            stdout = "https://github.com/acme/app/issues/3\n"
        return subprocess.CompletedProcess(args, 0, stdout, "")

    monkeypatch.setattr(github, "_run", fake_run)
    monkeypatch.setattr(github, "_gh_json", lambda args, *, cwd: [])

    actions = execute_plan(plan, cwd=tmp_path, create=True)

    assert actions[-1] == "issue created: https://github.com/acme/app/issues/3"
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


def test_apply_contract_current_updates_model_current(tmp_path: Path):
    (tmp_path / "driftless.yml").write_text(
        "version: 1\n"
        "workflows:\n"
        "  support_classifier:\n"
        "    description: keep me\n"
        "    model:\n"
        "      current: gpt-4\n"
        "      env_var: MODEL\n"
    )
    changed = apply_contract_current(
        "support_classifier", "gpt-4o-mini", cwd=tmp_path
    )
    assert changed == "driftless.yml"
    text = (tmp_path / "driftless.yml").read_text()
    assert "current: gpt-4o-mini" in text
    assert "description: keep me" in text
    assert apply_contract_current(
        "support_classifier", "gpt-4o-mini", cwd=tmp_path
    ) is None


def test_planned_model_files_include_contract_for_env_var_workflow(tmp_path: Path):
    (tmp_path / "driftless.yml").write_text(
        "version: 1\nworkflows:\n  demo:\n    model:\n      current: gpt-4\n"
    )
    wf = Workflow.model_validate(
        {
            "run": {"command": "true", "input_path": "i", "output_path": "o"},
            "model": {"current": "gpt-4", "env_var": "MODEL"},
        }
    )
    assert planned_model_files(
        wf, "gpt-4o-mini", cwd=tmp_path, workflow_name="demo"
    ) == ["driftless.yml"]
    note = runtime_model_note(wf, "gpt-4", "gpt-4o-mini")
    assert "model.current" in note
    assert "$MODEL" in note


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _init_repo(path: Path) -> None:
    init = subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=path,
        capture_output=True,
        text=True,
    )
    if init.returncode != 0 and "Operation not permitted" in init.stderr:
        pytest.skip("sandbox does not permit creating nested git repositories")
    init.check_returncode()
    _git(path, "config", "user.email", "tests@example.com")
    _git(path, "config", "user.name", "Driftless Tests")
    (path / "one.txt").write_text("base one\n")
    (path / "two.txt").write_text("base two\n")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "base")


def test_execute_two_real_git_plans_are_isolated_and_restore_base(
    tmp_path: Path, monkeypatch
):
    _init_repo(tmp_path)
    _git(tmp_path, "checkout", "-b", "caller")
    real_run = github._run

    def run_without_gh(args: list[str], *, cwd: Path):
        if args[0] == "gh":
            return subprocess.CompletedProcess(args, 0, "", "")
        return real_run(args, cwd=cwd)

    monkeypatch.setattr(github, "_run", run_without_gh)

    first = github.PullRequestPlan(
        kind="pr",
        title="first",
        body="body",
        branch="driftless/first",
        base="main",
        commit_message="first",
        files=["one.txt"],
    )
    second = github.PullRequestPlan(
        kind="pr",
        title="second",
        body="body",
        branch="driftless/second",
        base="main",
        commit_message="second",
        files=["two.txt"],
    )

    execute_plan(
        first,
        cwd=tmp_path,
        create=True,
        push=False,
        dedupe=False,
        base_branch="main",
        prepare_files=lambda: (tmp_path / "one.txt").write_text("first\n"),
    )
    assert _git(tmp_path, "branch", "--show-current") == "caller"
    execute_plan(
        second,
        cwd=tmp_path,
        create=True,
        push=False,
        dedupe=False,
        base_branch="main",
        prepare_files=lambda: (tmp_path / "two.txt").write_text("second\n"),
    )

    assert _git(tmp_path, "branch", "--show-current") == "caller"
    assert _git(tmp_path, "diff", "--name-only", "main..driftless/first") == "one.txt"
    assert _git(tmp_path, "diff", "--name-only", "main..driftless/second") == "two.txt"
    assert _git(tmp_path, "show", "driftless/second:one.txt") == "base one"


def test_existing_local_branch_is_rejected_before_mutation(tmp_path: Path):
    _init_repo(tmp_path)
    _git(tmp_path, "branch", "driftless/existing")
    plan = github.PullRequestPlan(
        kind="pr",
        title="x",
        body="x",
        branch="driftless/existing",
        commit_message="x",
        files=["one.txt"],
    )

    with pytest.raises(DriftlessError, match="local branch already exists"):
        execute_plan(plan, cwd=tmp_path, create=True, push=False, dedupe=False)

    assert _git(tmp_path, "branch", "--show-current") == "main"
    assert _git(tmp_path, "status", "--porcelain") == ""


def test_existing_remote_branch_is_rejected_before_mutation(tmp_path: Path):
    repo = tmp_path / "repo"
    remote = tmp_path / "origin.git"
    repo.mkdir()
    _git(tmp_path, "init", "--bare", str(remote))
    _init_repo(repo)
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "branch", "driftless/existing")
    _git(repo, "push", "origin", "driftless/existing")
    _git(repo, "branch", "-D", "driftless/existing")
    plan = github.PullRequestPlan(
        kind="pr",
        title="x",
        body="x",
        branch="driftless/existing",
        commit_message="x",
        files=["one.txt"],
    )

    with pytest.raises(DriftlessError, match="remote branch already exists"):
        execute_plan(plan, cwd=repo, create=True, push=True, dedupe=False)

    assert _git(repo, "branch", "--show-current") == "main"
    assert _git(repo, "status", "--porcelain") == ""
