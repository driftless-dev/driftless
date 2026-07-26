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

import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from .contract import Workflow
from .errors import DriftlessError


@dataclass
class PullRequestPlan:
    kind: str  # "pr" | "issue" | "skip"
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


def _repo_path(cwd: Path, rel: str, *, setting: str) -> Path:
    """Resolve a configured path and require it to remain inside the repository."""
    root = cwd.resolve()
    resolved = (root / rel).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise DriftlessError(
            f"{setting} path escapes the repository: {rel}",
            hint="Use a repository-relative path that resolves inside the project root.",
        )
    return resolved


def model_change_file(workflow: Workflow, *, cwd: Path | None = None) -> str | None:
    """Return the config file needed for a model change, without modifying it."""
    cwd = (cwd or Path.cwd()).resolve()
    spec = workflow.model
    if not (spec.config_file and spec.config_path):
        return None

    path = _repo_path(cwd, spec.config_file, setting="model.config_file")
    if not path.is_file():
        raise DriftlessError(f"model config file not found: {spec.config_file}")
    return spec.config_file


def apply_model_change(workflow: Workflow, target_model: str, *, cwd: Path | None = None) -> str | None:
    """Update a config-file-based model reference to ``target_model``.

    Returns the edited relative path, or ``None`` when the model is selected via
    an env var (no in-repo file to change).
    """
    cwd = (cwd or Path.cwd()).resolve()
    config_file = model_change_file(workflow, cwd=cwd)
    if config_file is None:
        return None

    spec = workflow.model
    assert spec.config_path is not None
    path = _repo_path(cwd, config_file, setting="model.config_file")
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        data = json.loads(text)
        _set_by_path(data, spec.config_path, target_model)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    else:
        data = yaml.safe_load(text) or {}
        _set_by_path(data, spec.config_path, target_model)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return config_file


def _branch_component(value: str) -> str:
    """Make an identifier safe for use as one Git branch path component."""
    sanitized = re.sub(r"[^A-Za-z0-9_-]+", "-", value)
    sanitized = re.sub(r"-+", "-", sanitized).strip("-")
    if sanitized and sanitized == value:
        return sanitized
    readable = sanitized or "unknown"
    suffix = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{readable}-{suffix}"


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
    branch = f"driftless/{_branch_component(workflow)}-to-{_branch_component(target)}"

    if result.get("status") == "no_change":
        return PullRequestPlan(
            kind="skip",
            title=f"No refinement changes: {workflow}",
            body=report_md,
        )

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

    Callers decide whether query unavailability is fatal. Create operations use
    it fail-closed so a transient failure cannot silently produce duplicates.
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
    and the exact title for issues. Query failures raise rather than allowing a
    create operation to continue without duplicate protection.
    """
    if plan.kind == "pr" and plan.branch:
        rows = _gh_json(
            ["gh", "pr", "list", "--head", plan.branch, "--state", "open",
             "--json", "number,url"],
            cwd=cwd,
        )
        if rows is None:
            raise DriftlessError(
                "could not check for an existing pull request",
                hint="Verify that gh is installed and authenticated, then retry; "
                "use --no-dedupe only if duplicate creation is acceptable.",
            )
        if rows:
            return f"PR #{rows[0].get('number')} ({rows[0].get('url', plan.branch)})"
        return None

    rows = _gh_json(
        ["gh", "issue", "list", "--state", "open", "--search", f"{plan.title} in:title",
         "--json", "number,title,url"],
        cwd=cwd,
    )
    if rows is None:
        raise DriftlessError(
            "could not check for an existing issue",
            hint="Verify that gh is installed and authenticated, then retry; "
            "use --no-dedupe only if duplicate creation is acceptable.",
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
    prepare_files: Callable[[], object] | None = None,
) -> list[str]:
    """Execute (or dry-run) a plan. Returns a list of human-readable actions.

    When ``create`` and ``dedupe`` are both set, an already-open PR/issue for the
    same move short-circuits creation so the bot doesn't pile up duplicates.
    """
    cwd = (cwd or Path.cwd()).resolve()
    actions: list[str] = []

    if plan.kind == "skip":
        return ["no changes; no PR or issue needed"]

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
            try:
                _run(
                    ["gh", "issue", "create", "--title", plan.title, "--body-file", body_file],
                    cwd=cwd,
                )
            finally:
                Path(body_file).unlink(missing_ok=True)
            actions.append("issue created")
        return actions

    actions.append(f"create branch: {plan.branch}")
    actions.append(f"commit files: {', '.join(plan.files)}")
    actions.append(f"open {'draft ' if plan.draft else ''}PR: {plan.title!r}")
    if not create:
        return actions

    _run(["git", "checkout", "-b", plan.branch], cwd=cwd)
    rollback: Callable[[], object] | None = None
    try:
        if prepare_files is not None:
            prepared = prepare_files()
            if callable(prepared):
                rollback = prepared
        _run(["git", "add", *plan.files], cwd=cwd)
        _run(["git", "commit", "-m", plan.commit_message], cwd=cwd)
    except (DriftlessError, OSError):
        if rollback is not None:
            try:
                rollback()
            except Exception:
                # Preserve the git failure and still attempt to clear the index.
                pass
        try:
            _run(["git", "reset", "--", *plan.files], cwd=cwd)
        except (DriftlessError, OSError):
            pass
        raise
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
    try:
        _run(gh_args, cwd=cwd)
    finally:
        Path(body_file).unlink(missing_ok=True)
    actions.append("PR created")
    return actions
