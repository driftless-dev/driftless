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

from .contract import Workflow, find_contract
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
    workflow: str = ""
    target_model: str = ""


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


def contract_relpath(
    *, cwd: Path, contract_path: Path | str | None = None
) -> str | None:
    """Repository-relative contract path, or ``None`` if it is outside the repo."""
    cwd = cwd.resolve()
    path = Path(contract_path).resolve() if contract_path else find_contract(cwd)
    if path is None or not path.is_file():
        return None
    try:
        return str(path.relative_to(cwd))
    except ValueError:
        return None


def _patch_workflow_current(text: str, workflow_name: str, target_model: str) -> str | None:
    """Set ``workflows.<name>.model.current`` while keeping surrounding text.

    Returns the new file text, or ``None`` when the value is already ``target_model``
    or the field cannot be found.
    """
    lines = text.splitlines(keepends=True)
    in_workflow = False
    in_model = False
    workflow_indent: int | None = None
    model_indent: int | None = None
    header = re.compile(rf"^(\s*){re.escape(workflow_name)}\s*:")
    current_re = re.compile(r"^(\s*)current\s*:\s*(.+?)\s*$")

    for i, line in enumerate(lines):
        stripped = line.lstrip(" \t")
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(stripped)
        match = header.match(line)
        if match:
            in_workflow = True
            workflow_indent = len(match.group(1))
            in_model = False
            continue
        if in_workflow and workflow_indent is not None and indent <= workflow_indent:
            in_workflow = False
            in_model = False
        if in_workflow and re.match(r"model\s*:", stripped):
            in_model = True
            model_indent = indent
            continue
        if in_model and model_indent is not None and indent <= model_indent:
            in_model = False
        if not in_model:
            continue
        cur = current_re.match(line)
        if not cur:
            continue
        raw = cur.group(2).strip().strip("'\"")
        if raw == target_model:
            return None
        newline = "\n" if line.endswith("\n") else ""
        lines[i] = f"{cur.group(1)}current: {target_model}{newline}"
        return "".join(lines)
    return None


def apply_contract_current(
    workflow_name: str,
    target_model: str,
    *,
    cwd: Path | None = None,
    contract_path: Path | str | None = None,
) -> str | None:
    """Set ``model.current`` in the contract. Returns the relative path if edited."""
    cwd = (cwd or Path.cwd()).resolve()
    rel = contract_relpath(cwd=cwd, contract_path=contract_path)
    if rel is None:
        return None
    path = _repo_path(cwd, rel, setting="contract")
    text = path.read_text(encoding="utf-8")
    patched = _patch_workflow_current(text, workflow_name, target_model)
    if patched is None:
        return None
    path.write_text(patched, encoding="utf-8")
    return rel


def planned_model_files(
    workflow: Workflow,
    target_model: str,
    *,
    cwd: Path | None = None,
    contract_path: Path | str | None = None,
    workflow_name: str | None = None,
) -> list[str]:
    """Files a passing migration PR should include to actually bump the model ID."""
    cwd = (cwd or Path.cwd()).resolve()
    files: list[str] = []
    rel = contract_relpath(cwd=cwd, contract_path=contract_path)
    if rel and workflow_name and workflow.model.current != target_model:
        files.append(rel)
    config_file = model_change_file(workflow, cwd=cwd)
    if config_file and config_file not in files:
        files.append(config_file)
    return files


def apply_runtime_model_updates(
    workflow: Workflow,
    target_model: str,
    *,
    cwd: Path | None = None,
    contract_path: Path | str | None = None,
    workflow_name: str | None = None,
) -> list[str]:
    """Write contract + config-file model IDs. Returns relative paths that changed."""
    cwd = (cwd or Path.cwd()).resolve()
    changed: list[str] = []
    if workflow_name:
        rel = apply_contract_current(
            workflow_name, target_model, cwd=cwd, contract_path=contract_path
        )
        if rel:
            changed.append(rel)
    config_file = apply_model_change(workflow, target_model, cwd=cwd)
    if config_file and config_file not in changed:
        changed.append(config_file)
    return changed


def runtime_model_note(workflow: Workflow, current_model: str, target_model: str) -> str:
    """PR/issue note describing which knobs actually change the runtime model."""
    lines = [
        f"This update sets `model.current` in the Driftless contract to `{target_model}` "
        f"(was `{current_model}`)."
    ]
    if workflow.model.config_file:
        lines.append(
            f"It also updates `{workflow.model.config_file}` "
            f"(`{workflow.model.config_path}`)."
        )
    if workflow.model.env_var:
        lines.append(
            f"The harness still reads `${workflow.model.env_var}` when that variable "
            f"is set (Driftless sets it during compare/migrate). Update the env var "
            f"in deployment if production does not read the contract or config file."
        )
    return "\n\n".join(lines)


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
    runtime_note: str | None = None,
) -> PullRequestPlan:
    """Build a PR/issue plan from a migration result dict + its report."""
    workflow = result["workflow"]
    current = result["current_model"]
    target = result["target_model"]
    branch = f"driftless/{_branch_component(workflow)}-to-{_branch_component(target)}"
    body = report_md
    if runtime_note and result.get("succeeded"):
        body = f"{runtime_note}\n\n---\n\n{report_md}"

    if result.get("status") == "no_change":
        return PullRequestPlan(
            kind="skip",
            title=f"No refinement changes: {workflow}",
            body=report_md,
            workflow=workflow,
            target_model=target,
        )

    if result["succeeded"] and committed_files:
        title = f"chore: migrate {workflow} from {current} to {target}"
        return PullRequestPlan(
            kind="pr",
            title=title,
            body=body,
            branch=branch,
            commit_message=title,
            files=sorted(set(committed_files)),
            draft=True,
            workflow=workflow,
            target_model=target,
        )

    if result["succeeded"] and not committed_files:
        # Nothing in-repo to edit (no contract / config file). Operational note.
        title = f"Model migration ready: {workflow} -> {target} (no code change)"
        note = runtime_note or (
            f"`{workflow}` can move from `{current}` to `{target}` with no prompt/config "
            f"changes.\n\nThe model is selected via an environment variable, so update it "
            f"in your deployment configuration."
        )
        return PullRequestPlan(
            kind="issue",
            title=title,
            body=f"{note}\n\n---\n\n{report_md}",
            workflow=workflow,
            target_model=target,
        )

    title = f"driftless: migration blocked: {workflow} -> {target}"
    return PullRequestPlan(
        kind="issue",
        title=title,
        body=report_md,
        workflow=workflow,
        target_model=target,
    )


def planned_pr_identity(
    workflow: str,
    current_model: str,
    target_model: str,
) -> PullRequestPlan:
    """Build the deterministic PR identity available before a migration runs."""
    branch = (
        f"driftless/{_branch_component(workflow)}-to-"
        f"{_branch_component(target_model)}"
    )
    return PullRequestPlan(
        kind="pr",
        title=f"chore: migrate {workflow} from {current_model} to {target_model}",
        body="",
        branch=branch,
        draft=True,
        workflow=workflow,
        target_model=target_model,
    )


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


def _created_url(stdout: str) -> str:
    """Best-effort GitHub URL from ``gh issue/pr create`` stdout."""
    for line in reversed((stdout or "").splitlines()):
        text = line.strip()
        if text.startswith("https://"):
            return text
    return ""


def _created_action(kind: str, stdout: str) -> str:
    url = _created_url(stdout)
    label = "PR created" if kind == "pr" else "issue created"
    return f"{label}: {url}" if url else label


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


def current_git_branch(*, cwd: Path) -> str:
    """Return the checked-out branch, rejecting detached HEAD."""
    proc = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    branch = proc.stdout.strip()
    if proc.returncode != 0 or not branch:
        raise DriftlessError(
            "could not determine the current git branch",
            hint="Run automation from a named branch (not detached HEAD) in a git repository.",
        )
    return branch


def checkout_git_branch(branch: str, *, cwd: Path) -> None:
    """Checkout a known branch."""
    _run(["git", "checkout", branch], cwd=cwd)


def _git_ref_exists(ref: str, *, cwd: Path) -> bool:
    proc = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", ref],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def ensure_pr_branch_available(
    plan: PullRequestPlan,
    *,
    cwd: Path,
    push: bool = True,
) -> None:
    """Fail before mutation when a planned branch already exists."""
    if plan.kind != "pr" or not plan.branch:
        return
    if _git_ref_exists(f"refs/heads/{plan.branch}", cwd=cwd):
        raise DriftlessError(
            f"local branch already exists: {plan.branch}",
            hint="Inspect or remove the branch manually, then retry. Driftless will not "
            "overwrite or reuse unknown local work.",
        )
    if not push:
        return

    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if remote.returncode != 0:
        raise DriftlessError(
            "git remote 'origin' is not configured",
            hint="Configure origin, or use --no-push for local-only execution.",
        )
    probe = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--heads", "origin", plan.branch],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if probe.returncode == 0:
        raise DriftlessError(
            f"remote branch already exists: origin/{plan.branch}",
            hint="Inspect the remote branch and its PR, then remove it or choose a "
            "different migration target. Driftless will not overwrite it.",
        )
    if probe.returncode not in (2,):
        raise DriftlessError(
            f"could not inspect remote branch origin/{plan.branch}",
            hint=(probe.stderr or probe.stdout or "Verify origin access and retry.").strip()[:500],
        )


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


def blocked_issue_title(workflow: str, target_model: str) -> str:
    return f"driftless: migration blocked: {workflow} -> {target_model}"


def find_open_blocked_issue(
    workflow: str, target_model: str, *, cwd: Path
) -> dict | None:
    """Return the open blocked-migration issue for this workflow/target, if any."""
    title = blocked_issue_title(workflow, target_model)
    rows = _gh_json(
        [
            "gh",
            "issue",
            "list",
            "--state",
            "open",
            "--search",
            f"{title} in:title",
            "--json",
            "number,title,url",
        ],
        cwd=cwd,
    )
    if not rows:
        return None
    for row in rows:
        if row.get("title") == title:
            return row
    return None


def close_blocked_issue(number: int, *, cwd: Path, pr_url: str = "") -> None:
    comment = "Superseded by the passing migration PR."
    if pr_url:
        comment = f"Superseded by the passing migration PR: {pr_url}"
    _run(["gh", "issue", "comment", str(number), "--body", comment], cwd=cwd)
    _run(["gh", "issue", "close", str(number)], cwd=cwd)


def execute_plan(
    plan: PullRequestPlan,
    *,
    cwd: Path | None = None,
    create: bool = False,
    push: bool = True,
    dedupe: bool = True,
    prepare_files: Callable[[], object] | None = None,
    base_branch: str | None = None,
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
                proc = _run(
                    ["gh", "issue", "create", "--title", plan.title, "--body-file", body_file],
                    cwd=cwd,
                )
            finally:
                Path(body_file).unlink(missing_ok=True)
            actions.append(_created_action("issue", proc.stdout))
        return actions

    actions.append(f"create branch: {plan.branch}")
    actions.append(f"commit files: {', '.join(plan.files)}")
    actions.append(f"open {'draft ' if plan.draft else ''}PR: {plan.title!r}")
    if not create:
        return actions

    original_branch = current_git_branch(cwd=cwd)
    base_branch = base_branch or original_branch
    ensure_pr_branch_available(plan, cwd=cwd, push=push)
    rollback: Callable[[], object] | None = None
    committed = False
    branch_created = False
    pushed = False
    cleanup_local_branch = False
    try:
        if original_branch != base_branch:
            checkout_git_branch(base_branch, cwd=cwd)
        _run(["git", "checkout", "-b", plan.branch, base_branch], cwd=cwd)
        branch_created = True
        if prepare_files is not None:
            prepared = prepare_files()
            if callable(prepared):
                rollback = prepared
        _run(["git", "add", *plan.files], cwd=cwd)
        _run(["git", "commit", "-m", plan.commit_message], cwd=cwd)
        committed = True
        if push:
            _run(["git", "push", "-u", "origin", plan.branch], cwd=cwd)
            pushed = True

        blocked = None
        if plan.workflow and plan.target_model:
            blocked = find_open_blocked_issue(
                plan.workflow, plan.target_model, cwd=cwd
            )
        body = plan.body
        if blocked and blocked.get("number"):
            body = f"{body.rstrip()}\n\nSupersedes #{blocked['number']}."

        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
            fh.write(body)
            body_file = fh.name
        gh_args = ["gh", "pr", "create", "--title", plan.title, "--body-file", body_file]
        if plan.base:
            gh_args += ["--base", plan.base]
        if plan.draft:
            gh_args += ["--draft"]
        try:
            proc = _run(gh_args, cwd=cwd)
        finally:
            Path(body_file).unlink(missing_ok=True)
        actions.append(_created_action("pr", proc.stdout))
        if blocked and blocked.get("number"):
            try:
                close_blocked_issue(
                    int(blocked["number"]),
                    cwd=cwd,
                    pr_url=_created_url(proc.stdout),
                )
                actions.append(f"closed blocked issue #{blocked['number']}")
            except (DriftlessError, OSError, TypeError, ValueError):
                actions.append(
                    f"could not close blocked issue #{blocked.get('number')}"
                )
        return actions
    except (DriftlessError, OSError):
        artifact_confirmed = False
        cleanup_local_branch = branch_created
        if not committed and rollback is not None:
            try:
                rollback()
            except Exception:
                # Preserve the git failure and still attempt to clear the index.
                pass
        if not committed:
            try:
                _run(["git", "reset", "--", *plan.files], cwd=cwd)
            except (DriftlessError, OSError):
                pass
        if pushed:
            try:
                artifact_confirmed = existing_open_item(plan, cwd=cwd) is not None
            except (DriftlessError, OSError):
                # The create call may have succeeded before its response was
                # lost. Preserve both branches when GitHub cannot confirm.
                cleanup_local_branch = False
            if artifact_confirmed:
                cleanup_local_branch = False
            elif cleanup_local_branch:
                try:
                    _run(["git", "push", "origin", "--delete", plan.branch], cwd=cwd)
                except (DriftlessError, OSError):
                    # Keep the local branch when remote cleanup is uncertain so
                    # the operator retains the commit for manual recovery.
                    cleanup_local_branch = False
        if not artifact_confirmed:
            raise
    finally:
        if current_git_branch(cwd=cwd) != original_branch:
            checkout_git_branch(original_branch, cwd=cwd)
        if cleanup_local_branch:
            try:
                _run(["git", "branch", "-D", plan.branch], cwd=cwd)
            except (DriftlessError, OSError):
                pass
    actions.append("PR created")
    return actions
