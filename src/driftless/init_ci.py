"""Scaffold GitHub Actions workflows for driftless (`init-ci`)."""

from __future__ import annotations

from pathlib import Path

from . import __version__
from .contract import Contract, Workflow, find_contract, load_contract
from .errors import DriftlessError

DEFAULT_ACTION_REF = f"driftless-dev/driftless@v{__version__}"


def default_action_ref() -> str:
    return DEFAULT_ACTION_REF


def _sanitize_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-").lower()


def dataset_paths(workflow: Workflow) -> list[str]:
    """Paths that should trigger an in-repo refine workflow."""
    paths: list[str] = []
    for path in (workflow.eval.labels_path, workflow.run.input_path):
        if path and path not in paths:
            paths.append(path)
    return paths


def _path_filter_block(paths: list[str], indent: str = "      ") -> str:
    if not paths:
        return f"{indent}# Add eval.labels_path / run.input_path paths from driftless.yml\n"
    lines = [f"{indent}- \"{p}\"" for p in paths]
    return "\n".join(lines) + "\n"


def _provider_env_block(indent: str = "          ") -> str:
    return (
        f"{indent}OPENAI_API_KEY: ${{{{ secrets.OPENAI_API_KEY }}}}\n"
        f"{indent}ANTHROPIC_API_KEY: ${{{{ secrets.ANTHROPIC_API_KEY }}}}\n"
    )


def render_scan_workflow(action_ref: str) -> str:
    return f"""\
name: driftless model scan

# Weekly deprecation scan: surfaces deprecated/retired model dependencies.
on:
  schedule:
    - cron: "0 9 * * 1"
  workflow_dispatch:

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Scan for at-risk model dependencies
        uses: {action_ref}
        with:
          command: scan
"""


def render_migrate_workflow(action_ref: str) -> str:
    return f"""\
name: driftless model migrate

# Manually triggered migration: compare + repair + validate, then open a PR
# (or an issue when blocked).
on:
  workflow_dispatch:
    inputs:
      workflow:
        description: "Workflow name from driftless.yml"
        required: true
      to:
        description: "Target model"
        required: true

permissions:
  contents: write
  pull-requests: write
  issues: write

jobs:
  migrate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Attempt migration
        uses: {action_ref}
        with:
          command: migrate
          workflow: ${{{{ github.event.inputs.workflow }}}}
          to: ${{{{ github.event.inputs.to }}}}
        env:
{_provider_env_block()}\
      - name: Open migration PR (or issue)
        uses: {action_ref}
        with:
          command: open-pr
          workflow: ${{{{ github.event.inputs.workflow }}}}
          args: "--create"
"""


def render_refine_workflow(
    action_ref: str,
    workflow_name: str,
    paths: list[str],
) -> str:
    safe = _sanitize_filename(workflow_name)
    return f"""\
name: driftless prompt refine ({workflow_name})

# Re-optimize the prompt when this workflow's eval dataset changes in git.
# Model stays pinned; only editable files may change.
on:
  push:
    branches: [main]
    paths:
{_path_filter_block(paths)}\
  workflow_dispatch:
    inputs:
      workflow:
        description: "Workflow name from driftless.yml"
        required: false
        default: "{workflow_name}"

permissions:
  contents: write
  pull-requests: write

env:
  WORKFLOW: ${{{{ github.event.inputs.workflow || '{workflow_name}' }}}}

jobs:
  refine:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Refine prompt toward the updated dataset
        uses: {action_ref}
        with:
          command: refine
          workflow: ${{{{ env.WORKFLOW }}}}
        env:
{_provider_env_block()}\
      - name: Open refine PR
        uses: {action_ref}
        with:
          command: open-pr
          workflow: ${{{{ env.WORKFLOW }}}}
          args: "--create"
"""


def render_poll_workflow(action_ref: str) -> str:
    return f"""\
name: driftless external dataset poll

# Poll external eval datasets (eval.data_source) and refine on meaningful change.
on:
  schedule:
    - cron: "0 6 * * 1"
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

jobs:
  poll:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Poll datasets and refine on meaningful change
        uses: {action_ref}
        with:
          command: poll
          args: "--act --create"
        env:
{_provider_env_block()}\
          DRIFTLESS_DATASOURCE_TOKEN: ${{{{ secrets.DRIFTLESS_DATASOURCE_TOKEN }}}}
          GH_TOKEN: ${{{{ github.token }}}}

      - name: Persist updated dataset state
        run: |
          if [ -n "$(git status --porcelain .driftless/state.json)" ]; then
            git config user.name "github-actions[bot]"
            git config user.email "github-actions[bot]@users.noreply.github.com"
            git add .driftless/state.json
            git commit -m "chore: update dataset poll state"
            git push
          fi
"""


def render_plan_workflow(action_ref: str) -> str:
    return f"""\
name: driftless plan (deprecation triage)

# Scheduled policy triage: migrate + open PRs/issues for actionable triggers.
on:
  schedule:
    - cron: "0 7 * * 1"
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write
  issues: write

jobs:
  plan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Plan and act on migration triggers
        uses: {action_ref}
        with:
          command: plan
          args: "--act"
        env:
{_provider_env_block()}\
          GH_TOKEN: ${{{{ github.token }}}}
"""


def _has_external_data_source(workflow: Workflow) -> bool:
    ds = workflow.eval.data_source
    return ds is not None and bool(ds.command or ds.inputs_url or ds.labels_url)


def scaffold_ci(
    contract: Contract,
    *,
    out_dir: Path,
    action_ref: str | None = None,
    force: bool = False,
    include_scan: bool = True,
    include_migrate: bool = True,
    include_refine: bool = True,
    include_poll: bool | None = None,
    include_plan: bool = False,
) -> list[Path]:
    """Write GitHub workflow YAML files under ``out_dir``."""
    action_ref = action_ref or default_action_ref()
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def write(path: Path, content: str) -> None:
        if path.exists() and not force:
            raise DriftlessError(
                f"workflow already exists: {path}",
                hint="pass --force to overwrite",
            )
        path.write_text(content, encoding="utf-8")
        written.append(path)

    if include_scan:
        write(out_dir / "driftless-model-scan.yml", render_scan_workflow(action_ref))

    if include_migrate:
        write(out_dir / "driftless-model-migrate.yml", render_migrate_workflow(action_ref))

    if include_refine:
        for name, wf in contract.workflows.items():
            paths = dataset_paths(wf)
            if not paths:
                continue
            fname = (
                "driftless-prompt-refine.yml"
                if len(contract.workflows) == 1
                else f"driftless-prompt-refine-{_sanitize_filename(name)}.yml"
            )
            write(out_dir / fname, render_refine_workflow(action_ref, name, paths))

    poll_needed = include_poll
    if poll_needed is None:
        poll_needed = any(_has_external_data_source(wf) for wf in contract.workflows.values())
    if poll_needed:
        write(out_dir / "driftless-prompt-refine-poll.yml", render_poll_workflow(action_ref))

    if include_plan:
        write(out_dir / "driftless-plan-act.yml", render_plan_workflow(action_ref))

    if not written:
        raise DriftlessError(
            "nothing to scaffold",
            hint="enable at least one of scan, migrate, refine, poll, or plan",
        )
    return written


def scaffold_ci_from_path(
    contract_path: Path | None = None,
    **kwargs,
) -> list[Path]:
    path = contract_path or find_contract(Path.cwd())
    if path is None:
        raise DriftlessError(
            "no driftless.yml found",
            hint="run `driftless init` first or pass --contract",
        )
    contract = load_contract(path)
    return scaffold_ci(contract, **kwargs)


CHECKLIST = """\
Next steps:
  1. Add repository secrets: OPENAI_API_KEY (and/or ANTHROPIC_API_KEY).
  2. For poll workflows: DRIFTLESS_DATASOURCE_TOKEN if eval.data_source URLs need auth.
  3. Confirm workflow path filters match your eval dataset paths in driftless.yml.
  4. Run driftless validate -w <workflow> locally before enabling scheduled jobs.
  5. Pin the Action ref when upgrading: uses: driftless-dev/driftless@vX.Y.Z
"""
