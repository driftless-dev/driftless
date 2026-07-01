"""Scaffold GitHub Actions workflows for driftless (`init-ci`)."""

from __future__ import annotations

from dataclasses import dataclass
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


def label_audit_workflows(contract: Contract) -> list[str]:
    """Workflow names eligible for gold-label auditing (classification + labels_path)."""
    names: list[str] = []
    for name, wf in contract.workflows.items():
        if wf.eval.grading != "label":
            continue
        if not wf.eval.labels_path:
            continue
        names.append(name)
    return names


def label_audit_paths(contract: Contract) -> list[str]:
    """Union of dataset paths for workflows included in label audit."""
    paths: list[str] = []
    for name in label_audit_workflows(contract):
        for path in dataset_paths(contract.workflows[name]):
            if path not in paths:
                paths.append(path)
    return paths


def render_audit_labels_workflow(
    action_ref: str,
    workflow_names: list[str],
    paths: list[str],
) -> str:
    if not workflow_names:
        raise ValueError("workflow_names must not be empty")
    title = (
        f"driftless label audit ({workflow_names[0]})"
        if len(workflow_names) == 1
        else "driftless label audit"
    )
    if len(workflow_names) == 1:
        matrix_block = ""
        workflow_arg = workflow_names[0]
        workflow_step = f"""\
      - name: Audit gold labels ({workflow_names[0]})
        uses: {action_ref}
        with:
          command: audit-labels
          workflow: {workflow_arg}
          args: "--fail"
"""
    else:
        matrix_yaml = "\n".join(f"          - {name!r}" for name in workflow_names)
        matrix_block = f"""\
    strategy:
      fail-fast: false
      matrix:
        workflow:
{matrix_yaml}

"""
        workflow_step = f"""\
      - name: Audit gold labels (${{{{ matrix.workflow }}}})
        uses: {action_ref}
        with:
          command: audit-labels
          workflow: ${{{{ matrix.workflow }}}}
          args: "--fail"
"""
    return f"""\
name: {title}

# Fail CI when duplicate/near-duplicate inputs carry disagreeing gold labels.
on:
  pull_request:
    paths:
{_path_filter_block(paths)}\
  push:
    branches: [main]
    paths:
{_path_filter_block(paths)}\
  workflow_dispatch:

jobs:
  audit:
    runs-on: ubuntu-latest
{matrix_block}\
    steps:
      - uses: actions/checkout@v4
{workflow_step}\
"""


@dataclass(frozen=True)
class JudgeCheckTarget:
    name: str
    calibration_path: str
    enforce: bool


def judge_check_targets(contract: Contract) -> list[JudgeCheckTarget]:
    """Judge-graded workflows with a human calibration set configured."""
    targets: list[JudgeCheckTarget] = []
    for name, wf in contract.workflows.items():
        if wf.eval.grading != "judge" or wf.eval.judge is None:
            continue
        spec = wf.eval.judge
        if not spec.calibration_path:
            continue
        enforce = spec.max_mae is not None or spec.min_correlation is not None
        targets.append(
            JudgeCheckTarget(
                name=name,
                calibration_path=spec.calibration_path,
                enforce=enforce,
            )
        )
    return targets


def judge_check_paths(contract: Contract) -> list[str]:
    paths: list[str] = []
    for target in judge_check_targets(contract):
        if target.calibration_path not in paths:
            paths.append(target.calibration_path)
    return paths


def render_judge_check_workflow(
    action_ref: str,
    targets: list[JudgeCheckTarget],
    paths: list[str],
) -> str:
    if not targets:
        raise ValueError("targets must not be empty")
    title = (
        f"driftless judge check ({targets[0].name})"
        if len(targets) == 1
        else "driftless judge check"
    )
    if len(targets) == 1:
        target = targets[0]
        matrix_block = ""
        args = '"--enforce"' if target.enforce else '""'
        workflow_step = f"""\
      - name: Judge calibration check ({target.name})
        uses: {action_ref}
        with:
          command: judge-check
          workflow: {target.name}
          args: {args}
        env:
{_provider_env_block()}\
"""
    else:
        include_lines: list[str] = []
        for target in targets:
            args = '"--enforce"' if target.enforce else '""'
            include_lines.append(
                f"          - workflow: {target.name!r}\n"
                f"            args: {args}"
            )
        matrix_block = (
            "    strategy:\n"
            "      fail-fast: false\n"
            "      matrix:\n"
            "        include:\n"
            + "\n".join(include_lines)
            + "\n\n"
        )
        workflow_step = f"""\
      - name: Judge calibration check (${{{{ matrix.workflow }}}})
        uses: {action_ref}
        with:
          command: judge-check
          workflow: ${{{{ matrix.workflow }}}}
          args: ${{{{ matrix.args }}}}
        env:
{_provider_env_block()}\
"""
    return f"""\
name: {title}

# Measure LLM-judge agreement against human-scored calibration records.
on:
  pull_request:
    paths:
{_path_filter_block(paths)}\
  push:
    branches: [main]
    paths:
{_path_filter_block(paths)}\
  workflow_dispatch:

jobs:
  judge-check:
    runs-on: ubuntu-latest
{matrix_block}\
    steps:
      - uses: actions/checkout@v4
{workflow_step}\
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
    include_audit_labels: bool | None = None,
    include_judge_check: bool | None = None,
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

    audit_names = label_audit_workflows(contract)
    audit_needed = include_audit_labels
    if audit_needed is None:
        audit_needed = bool(audit_names)
    if audit_needed:
        if not audit_names:
            raise DriftlessError(
                "label audit workflow requires a classification workflow with eval.labels_path",
                hint="add labels_path to a workflow or pass --no-audit-labels",
            )
        audit_paths = label_audit_paths(contract)
        fname = (
            "driftless-label-audit.yml"
            if len(audit_names) == 1
            else "driftless-label-audit-all.yml"
        )
        write(
            out_dir / fname,
            render_audit_labels_workflow(action_ref, audit_names, audit_paths),
        )

    judge_targets = judge_check_targets(contract)
    judge_needed = include_judge_check
    if judge_needed is None:
        judge_needed = bool(judge_targets)
    if judge_needed:
        if not judge_targets:
            raise DriftlessError(
                "judge-check workflow requires eval.judge.calibration_path",
                hint="add a human-scored calibration set or pass --no-judge-check",
            )
        judge_paths = judge_check_paths(contract)
        fname = (
            "driftless-judge-check.yml"
            if len(judge_targets) == 1
            else "driftless-judge-check-all.yml"
        )
        write(
            out_dir / fname,
            render_judge_check_workflow(action_ref, judge_targets, judge_paths),
        )

    if not written:
        raise DriftlessError(
            "nothing to scaffold",
            hint="enable at least one of scan, migrate, refine, poll, plan, audit-labels, or judge-check",
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
  5. Run driftless audit-labels -w <workflow> locally; CI uses --fail on label conflicts.
  6. For judge-graded workflows: driftless judge-check -w <workflow> --enforce when gates are set.
  7. Pin the Action ref when upgrading: uses: driftless-dev/driftless@vX.Y.Z
"""
