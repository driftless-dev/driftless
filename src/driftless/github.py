"""GitHub surface: turn a migration result into a PR (or an issue).

A successful migration with file changes becomes a branch + commit + pull
request whose body is the evidence-rich markdown report. A partial/blocked
migration -- or a success that requires only an operational model change --
becomes an issue, so the team always gets an actionable artifact.

Git/gh side effects only happen when ``create=True``; the default is a dry run
that writes the PR body to disk and prints what it would do. We never
auto-merge and never push to the base branch.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .contract import Workflow
from .errors import DriftlessError


@dataclass
class PullRequestPlan:
    kind: str  # "pr" | "issue"
    title: str
    body: str
    branch: str = ""
    base: str | None = None
    commit_message: str = ""
    files: list[str] = field(default_factory=list)
    draft: bool = False


def _set_by_path(data: dict, dotted: str, value) -> None:
    keys = dotted.split(".")
    node = data
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    node[keys[-1]] = value


def apply_model_change(workflow: Workflow, target_model: str, *, cwd: Path | None = None) -> str | None:
    """Update a config-file-based model reference to ``target_model``.

    Returns the edited relative path, or ``None`` when the model is selected via
    an env var (no in-repo file to change).
    """
    cwd = (cwd or Path.cwd()).resolve()
    spec = workflow.model
    if not (spec.config_file and spec.config_path):
        return None

    path = (cwd / spec.config_file).resolve()
    if not path.is_file():
        raise DriftlessError(f"model config file not found: {spec.config_file}")

    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        data = json.loads(text)
        _set_by_path(data, spec.config_path, target_model)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    else:
        data = yaml.safe_load(text) or {}
        _set_by_path(data, spec.config_path, target_model)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return spec.config_file


def build_pr_plan(
    result: dict,
    report_md: str,
    *,
    committed_files: list[str],
) -> PullRequestPlan:
    """Build a PR/issue plan from a migration result dict + its report."""
    workflow = result["workflow"]
    current = result["current_model"]
    target = result["target_model"]
    branch = f"driftless/{workflow}-to-{target}"

    if result["succeeded"] and committed_files:
        title = f"chore: migrate {workflow} from {current} to {target}"
        return PullRequestPlan(
            kind="pr",
            title=title,
            body=report_md,
            branch=branch,
            commit_message=title,
            files=sorted(set(committed_files)),
        )

    if result["succeeded"] and not committed_files:
        # Naive swap passes but the model is env-var selected: operational change.
        title = f"Model migration ready: {workflow} -> {target} (no code change)"
        body = (
            f"`{workflow}` can move from `{current}` to `{target}` with no prompt/config "
            f"changes.\n\nThe model is selected via an environment variable, so update it "
            f"in your deployment configuration.\n\n---\n\n{report_md}"
        )
        return PullRequestPlan(kind="issue", title=title, body=body)

    title = f"driftless: migration blocked: {workflow} -> {target}"
    return PullRequestPlan(kind="issue", title=title, body=report_md)


# --------------------------------------------------------------------------- #
# Execution (git + gh)
# --------------------------------------------------------------------------- #
def _run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise DriftlessError(
            f"command failed: {' '.join(args)}",
            hint=(proc.stderr or proc.stdout or "").strip()[:500],
        )
    return proc


def _gh_json(args: list[str], *, cwd: Path) -> list | None:
    """Run a read-only ``gh`` query returning JSON; ``None`` if it can't be run.

    Best-effort: a missing/unauthenticated ``gh`` returns ``None`` so dedupe never
    blocks a legitimate creation on a transient query failure.
    """
    try:
        proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    except (FileNotFoundError, OSError):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def existing_open_item(plan: PullRequestPlan, *, cwd: Path) -> str | None:
    """Return a human-readable ref to an already-open PR/issue for this plan.

    Dedupe key: the deterministic branch for PRs (``driftless/<wf>-to-<model>``)
    and the exact title for issues. ``None`` means "none found / couldn't check".
    """
    if plan.kind == "pr" and plan.branch:
        rows = _gh_json(
            ["gh", "pr", "list", "--head", plan.branch, "--state", "open",
             "--json", "number,url"],
            cwd=cwd,
        )
        if rows:
            return f"PR #{rows[0].get('number')} ({rows[0].get('url', plan.branch)})"
        return None

    rows = _gh_json(
        ["gh", "issue", "list", "--state", "open", "--search", f"{plan.title} in:title",
         "--json", "number,title,url"],
        cwd=cwd,
    )
    if rows:
        for row in rows:
            if row.get("title") == plan.title:
                return f"issue #{row.get('number')} ({row.get('url', '')})".strip()
    return None


def execute_plan(
    plan: PullRequestPlan,
    *,
    cwd: Path | None = None,
    create: bool = False,
    push: bool = True,
    dedupe: bool = True,
) -> list[str]:
    """Execute (or dry-run) a plan. Returns a list of human-readable actions.

    When ``create`` and ``dedupe`` are both set, an already-open PR/issue for the
    same move short-circuits creation so the bot doesn't pile up duplicates.
    """
    cwd = (cwd or Path.cwd()).resolve()
    actions: list[str] = []

    if create and dedupe:
        existing = existing_open_item(plan, cwd=cwd)
        if existing:
            actions.append(f"skipped: already open {existing}")
            return actions

    if plan.kind == "issue":
        actions.append(f"open issue: {plan.title!r}")
        if create:
            with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
                fh.write(plan.body)
                body_file = fh.name
            _run(["gh", "issue", "create", "--title", plan.title, "--body-file", body_file], cwd=cwd)
            actions.append("issue created")
        return actions

    actions.append(f"create branch: {plan.branch}")
    actions.append(f"commit files: {', '.join(plan.files)}")
    actions.append(f"open {'draft ' if plan.draft else ''}PR: {plan.title!r}")
    if not create:
        return actions

    _run(["git", "checkout", "-b", plan.branch], cwd=cwd)
    _run(["git", "add", *plan.files], cwd=cwd)
    _run(["git", "commit", "-m", plan.commit_message], cwd=cwd)
    if push:
        _run(["git", "push", "-u", "origin", plan.branch], cwd=cwd)

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(plan.body)
        body_file = fh.name
    gh_args = ["gh", "pr", "create", "--title", plan.title, "--body-file", body_file]
    if plan.base:
        gh_args += ["--base", plan.base]
    if plan.draft:
        gh_args += ["--draft"]
    _run(gh_args, cwd=cwd)
    actions.append("PR created")
    return actions
