"""driftless command-line interface.

The CLI is the engine. The GitHub Action and App invoke these same commands.
Milestone 1 implements `init` and `validate`; the remaining commands are
declared so the surface is stable and discoverable.
"""

from __future__ import annotations

import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .compare import Comparison, compare_models, save_comparison
from .contract import CONTRACT_FILENAMES, Workflow, find_contract, load_contract
from .errors import HarnessError, DriftlessError
from .harness import check_inputs, run_workflow
from .progress import log as progress_log
from .templates import CONTRACT_TEMPLATE, POLICY_TEMPLATE

_CI_PROGRESS = (
    os.environ.get("GITHUB_ACTIONS") == "true"
    or os.environ.get("CI") == "true"
    or os.environ.get("DRIFTLESS_PROGRESS", "").strip().lower() in ("1", "true", "yes", "on")
)
app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Dependabot for LLM models: detect risky model dependencies, test "
    "replacements through your real workflow, repair prompts/configs, and open "
    "migration PRs with evidence.",
)
console = Console(force_terminal=_CI_PROGRESS)
err_console = Console(stderr=True, force_terminal=True)


def _fail(exc: DriftlessError) -> None:
    err_console.print(f"[bold red]error:[/] {exc.message}")
    if exc.hint:
        err_console.print(f"[dim]hint: {exc.hint}[/]")
    raise typer.Exit(code=1)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"driftless {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    _version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """driftless"""


@app.command()
def init(
    path: Path = typer.Option(
        Path(CONTRACT_FILENAMES[0]), "--path", help="Where to write the contract."
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing file."),
) -> None:
    """Scaffold a driftless.yml contract."""
    if path.exists() and not force:
        err_console.print(
            f"[bold red]error:[/] {path} already exists (use --force to overwrite)"
        )
        raise typer.Exit(code=1)
    path.write_text(CONTRACT_TEMPLATE, encoding="utf-8")
    console.print(f"[green]created[/] {path}")
    console.print(
        "Edit it to describe your workflow, then run "
        "[bold]driftless validate -w <workflow>[/]."
    )


@app.command(name="init-policy")
def init_policy(
    path: Path = typer.Option(
        Path(".driftless") / "policy.yml",
        "--path",
        help="Where to write the policy file.",
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing file."),
) -> None:
    """Scaffold a `.driftless/policy.yml` (the 'when to migrate' config)."""
    if path.exists() and not force:
        err_console.print(
            f"[bold red]error:[/] {path} already exists (use --force to overwrite)"
        )
        raise typer.Exit(code=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(POLICY_TEMPLATE, encoding="utf-8")
    console.print(f"[green]created[/] {path}")
    console.print(
        "Tune triggers/thresholds, then run [bold]driftless plan[/] to see decisions."
    )


@app.command(name="init-ci")
def init_ci(
    contract_path: Path = typer.Option(
        None, "--contract", help="Path to driftless.yml."
    ),
    out_dir: Path = typer.Option(
        Path(".github/workflows"),
        "--out-dir",
        help="Directory for generated workflow YAML files.",
    ),
    action_ref: str = typer.Option(
        None,
        "--action-ref",
        help="Composite Action ref (default: driftless-dev/driftless@v<version>).",
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite existing workflows."),
    scan: bool = typer.Option(True, "--scan/--no-scan", help="Scaffold model scan workflow."),
    migrate: bool = typer.Option(
        True, "--migrate/--no-migrate", help="Scaffold model migrate workflow."
    ),
    refine: bool = typer.Option(
        True, "--refine/--no-refine", help="Scaffold dataset refine workflow(s)."
    ),
    poll: bool | None = typer.Option(
        None,
        "--poll/--no-poll",
        help="Scaffold external poll workflow (default: on if data_source is set).",
    ),
    plan: bool = typer.Option(
        False, "--plan/--no-plan", help="Scaffold scheduled plan --act workflow."
    ),
) -> None:
    """Scaffold GitHub Actions workflows wired to the driftless composite Action."""
    from .init_ci import CHECKLIST, scaffold_ci_from_path

    try:
        written = scaffold_ci_from_path(
            contract_path,
            out_dir=out_dir,
            action_ref=action_ref,
            force=force,
            include_scan=scan,
            include_migrate=migrate,
            include_refine=refine,
            include_poll=poll,
            include_plan=plan,
        )
    except DriftlessError as exc:
        _fail(exc)
        return

    for path in written:
        console.print(f"[green]created[/] {path}")
    console.print(CHECKLIST)


@app.command()
def validate(
    workflow: str = typer.Option(
        None, "--workflow", "-w", help="Workflow to validate (default: all)."
    ),
    contract_path: Path = typer.Option(
        None, "--contract", help="Path to driftless.yml."
    ),
    run: bool = typer.Option(
        True, "--run/--no-run",
        help="Actually run the harness with the current model.",
    ),
) -> None:
    """Check that the contract parses and the harness runs with the current model."""
    try:
        contract = load_contract(contract_path)
    except DriftlessError as exc:
        _fail(exc)
        return

    found = find_contract() if contract_path is None else contract_path
    console.print(f"[green]contract ok[/] ({found})")

    names = [workflow] if workflow else list(contract.workflows)
    failures = 0
    for name in names:
        try:
            wf = contract.workflow(name)
            _validate_workflow(name, wf, run=run)
        except DriftlessError as exc:
            failures += 1
            err_console.print(f"[bold red]{name}: {exc.message}[/]")
            if exc.hint:
                err_console.print(f"[dim]  hint: {exc.hint}[/]")

    if failures:
        raise typer.Exit(code=1)


def _validate_workflow(name: str, wf: Workflow, *, run: bool) -> None:
    console.print(f"\n[bold]{name}[/] — {wf.description or '(no description)'}")

    is_endpoint = bool(wf.run.endpoint)
    if is_endpoint:
        override = f"endpoint body: {wf.run.model_param or 'model'}"
    elif wf.model.env_var:
        override = wf.model.env_var
    elif wf.model.config_file:
        override = f"{wf.model.config_file}:{wf.model.config_path}"
    else:
        override = "[red]none[/]"

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_row("current model", wf.model.current)
    table.add_row("runner", wf.run.endpoint if is_endpoint else "command")
    table.add_row("override", override)
    table.add_row("editable files", str(len(wf.files.editable)))
    console.print(table)

    check_inputs(wf)
    console.print("  [green]+[/] input dataset found")

    # Endpoint workflows select the model via the request body, not env/config.
    if not is_endpoint and not wf.model.has_override():
        raise HarnessError(
            "no model override configured",
            hint="set model.env_var so the workflow can run under different models",
        )

    if not run:
        console.print("  [yellow]~[/] skipping harness run (--no-run)")
        return

    result = run_workflow(wf, wf.model.current)
    console.print(
        f"  [green]+[/] harness ran in {result.duration_seconds:.1f}s "
        f"-> {result.output_path.name}"
    )


def _not_implemented(command: str) -> None:
    err_console.print(
        f"[yellow]{command} is not implemented yet[/] — see IMPLEMENTATION_PLAN.md"
    )
    raise typer.Exit(code=2)


@app.command()
def scan(
    path: Path = typer.Argument(Path("."), help="Directory to scan."),
    show_files: bool = typer.Option(
        True, "--files/--no-files", help="List probable LLM workflow files."
    ),
) -> None:
    """Find probable LLM usage and at-risk model dependencies."""
    from .lifecycle import ModelInfo, load_lifecycle
    from .scanner import scan_repo

    lifecycle = load_lifecycle()
    result = scan_repo(path.resolve(), lifecycle=lifecycle)

    if not result.findings:
        console.print("[yellow]No probable LLM usage found.[/]")
        console.print("[dim]Static discovery is best-effort; models may be hidden behind env vars or gateways.[/]")
        raise typer.Exit(code=0)

    grouped = result.files()
    if show_files:
        console.print("[bold]Probable LLM workflows[/]")
        for fpath, finds in grouped.items():
            providers = sorted({f.provider for f in finds if f.provider})
            env_vars = sorted({f.env_var for f in finds if f.env_var})
            models = sorted({f.model for f in finds if f.model})
            bits = []
            if providers:
                bits.append("SDK: " + ", ".join(providers))
            if env_vars:
                bits.append("env: " + ", ".join(env_vars))
            if models:
                bits.append("models: " + ", ".join(models))
            console.print(f"  [cyan]{fpath}[/] — {'; '.join(bits) or 'model config'}")

    risks = result.model_risks(lifecycle)
    if risks:
        table = Table(title="Detected models", show_lines=False)
        table.add_column("Model")
        table.add_column("Provider")
        table.add_column("Status")
        table.add_column("Tier")
        table.add_column("$/1M (in/out)", justify="right")
        table.add_column("Retires")
        table.add_column("Replacement")
        table.add_column("#", justify="right")
        at_risk = 0
        for info, count in risks:
            if isinstance(info, ModelInfo):
                style = {"deprecated": "yellow", "retired": "red", "active": "green"}.get(info.status, "white")
                if info.at_risk:
                    at_risk += 1
                price = (
                    f"{info.pricing.input_per_1m:g}/{info.pricing.output_per_1m:g}"
                    if info.pricing
                    else "-"
                )
                table.add_row(
                    info.model, info.provider, f"[{style}]{info.status}[/]",
                    info.capability_tier or "-", price,
                    info.retirement_date or "-", info.recommended_replacement or "-", str(count),
                )
            else:
                table.add_row(str(info), "-", "[dim]unknown[/]", "-", "-", "-", "-", str(count))
        console.print(table)
        if at_risk:
            console.print(
                f"\n[bold red]{at_risk} at-risk model(s) detected.[/] "
                "Run [bold]driftless configure <name>[/] to make a workflow migration-ready."
            )
        else:
            console.print("\n[green]No deprecated or retired models detected.[/]")


@app.command()
def configure(
    workflow: str = typer.Argument(..., help="Name for the workflow to scaffold."),
    path: Path = typer.Argument(Path("."), help="Directory to scan for prefill."),
) -> None:
    """Scaffold a migration-ready workflow contract from scan detections."""
    from .configure import build_workflow_scaffold, save_scaffold

    snippet, primary = build_workflow_scaffold(workflow, path.resolve())
    out_path = save_scaffold(workflow, snippet, cwd=Path.cwd())

    if primary:
        console.print(
            f"Prefilled from detected model [bold]{primary}[/] "
            f"(env var, provider, and replacement candidate where known)."
        )
    else:
        console.print("[yellow]No model auto-detected[/]; generated a generic skeleton.")

    console.print(f"\n[dim]saved scaffold: {out_path}[/]")
    console.print("Add this workflow to your [bold]driftless.yml[/]:\n")
    console.print(snippet)


def _preflight(wf: Workflow, target_model: str) -> None:
    """Warn (non-fatally) about cross-provider swaps before a slow run."""
    from .preflight import provider_preflight

    pf = provider_preflight(wf, target_model, cwd=Path.cwd())
    if pf.warning:
        err_console.print(f"[yellow]warning:[/] {pf.warning}")


def _fmt(value: float | None, *, pct: bool = False) -> str:
    if value is None:
        return "[dim]n/a[/]"
    return f"{value:.1%}" if pct else f"{value:.3f}"


def _scorecard(comparison: Comparison) -> Table:
    table = Table(title=f"{comparison.workflow}: {comparison.current_model} -> {comparison.target_model}")
    table.add_column("Metric")
    table.add_column("Current", justify="right")
    table.add_column("Target (orig files)", justify="right")

    b, t = comparison.baseline, comparison.target

    def row(label: str, bf: float | None, tf: float | None, *, pct: bool = False, higher_better: bool = True) -> None:
        cell = _fmt(tf, pct=pct)
        if bf is not None and tf is not None:
            improved = (tf >= bf) if higher_better else (tf <= bf)
            color = "green" if improved else "red"
            cell = f"[{color}]{cell}[/]"
        table.add_row(label, _fmt(bf, pct=pct), cell)

    row("F1", b.f1, t.f1)
    row("Precision", b.precision, t.precision)
    row("Recall", b.recall, t.recall)
    row("Accuracy", b.accuracy, t.accuracy)
    row("Score / pass-rate", b.score, t.score)
    row("Schema error rate", b.schema_error_rate, t.schema_error_rate, pct=True, higher_better=False)
    row("Refusal rate", b.refusal_rate, t.refusal_rate, pct=True, higher_better=False)
    row("Avg latency (ms)", b.avg_latency_ms, t.avg_latency_ms, higher_better=False)
    if b.total_cost is not None or t.total_cost is not None:
        row("Total cost", b.total_cost, t.total_cost, higher_better=False)
    return table


@app.command()
def compare(
    workflow: str = typer.Option(..., "--workflow", "-w"),
    to: str = typer.Option(..., "--to", help="Target model."),
    contract_path: Path = typer.Option(None, "--contract", help="Path to driftless.yml."),
) -> None:
    """Run baseline vs target through the real workflow and score both."""
    try:
        contract = load_contract(contract_path)
        wf = contract.workflow(workflow)
        _preflight(wf, to)
        progress_log(f"compare: {workflow} {wf.model.current} -> {to}")
        console.print(f"Running [bold]{wf.model.current}[/] (baseline) and [bold]{to}[/] (target)...")
        comparison = compare_models(workflow, wf, to, cwd=Path.cwd())
    except DriftlessError as exc:
        _fail(exc)
        return

    console.print(_scorecard(comparison))

    console.print("\n[bold]Thresholds[/] (target vs contract):")
    if not comparison.checks:
        console.print("  [dim]no thresholds configured[/]")
    for check in comparison.checks:
        mark = "[green]PASS[/]" if check.passed else "[red]FAIL[/]"
        console.print(f"  {mark} {check.name}: {check.detail}")

    saved = save_comparison(comparison, cwd=Path.cwd())
    console.print(f"\n[dim]saved {saved}[/]")

    if comparison.passed:
        console.print(
            "\n[green]Naive target passes all thresholds[/] - migration may be a model-ID change only."
        )
    else:
        console.print(
            "\n[yellow]Naive target does not pass[/] - run "
            f"[bold]driftless migrate -w {workflow} --to {to}[/] to attempt prompt/config repair."
        )


@app.command()
def calibrate(
    workflow: str = typer.Option(..., "--workflow", "-w"),
    contract_path: Path = typer.Option(None, "--contract", help="Path to driftless.yml."),
    margin: float = typer.Option(
        0.03, "--margin", help="Safety margin below achieved metrics for suggestions."
    ),
) -> None:
    """Measure the current baseline and suggest a starting `thresholds:` block.

    Solves the threshold cold-start: instead of guessing, run the workflow on the
    current model and propose absolute thresholds (achieved minus a margin) to
    paste into the contract. Leaving `thresholds:` empty is also valid — the bar
    then defaults to no-regression vs. the baseline.
    """
    import yaml

    from .calibrate import suggest_thresholds
    from .evaluation import evaluate

    try:
        contract = load_contract(contract_path)
        wf = contract.workflow(workflow)
        console.print(f"Measuring baseline [bold]{wf.model.current}[/] for {workflow}...")
        judge = None
        if wf.eval.grading == "judge":
            from .judges import build_judge

            judge_spec = wf.eval.judge
            if judge_spec is None:
                raise DriftlessError(
                    "judge grading requires eval.judge in the contract",
                    hint="add a judge block to driftless.yml",
                )
            judge = build_judge(judge_spec)
        run = run_workflow(wf, wf.model.current, cwd=Path.cwd())
        metrics = evaluate(wf, run, judge=judge, cwd=Path.cwd())
    except DriftlessError as exc:
        _fail(exc)
        return

    table = Table(title=f"{workflow}: baseline metrics ({wf.model.current})")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    for label, attr, pct in (
        ("F1", "f1", False),
        ("Precision", "precision", False),
        ("Recall", "recall", False),
        ("Accuracy", "accuracy", False),
        ("Score / pass-rate", "score", False),
        ("Schema error rate", "schema_error_rate", True),
        ("Refusal rate", "refusal_rate", True),
    ):
        table.add_row(label, _fmt(getattr(metrics, attr), pct=pct))
    console.print(table)

    suggested = suggest_thresholds(metrics, margin=margin)
    if not suggested:
        console.print(
            "\n[yellow]No labeled metrics available[/] — add eval.labels_path to "
            "calibrate quality thresholds, or leave thresholds empty for the "
            "no-regression default."
        )
        return

    snippet = yaml.safe_dump({"thresholds": suggested}, sort_keys=False, default_flow_style=False)
    console.print(
        f"\n[bold]Suggested thresholds[/] (achieved minus {margin:g} margin) — "
        f"paste into workflow [bold]{workflow}[/]:\n"
    )
    console.print(snippet, markup=False)
    console.print(
        "[dim]Tip: tighten these for hard SLAs, or delete them to use the "
        "no-regression default.[/]"
    )


_URGENCY_STYLE = {
    "critical": "bold red",
    "high": "red",
    "medium": "yellow",
    "low": "cyan",
    "none": "dim",
}

_ACTION_STYLE = {"pr": "green", "issue": "yellow", "notify": "cyan", "skip": "dim"}


def _act_on_trigger(
    name: str,
    wf,
    candidate_model: str,
    *,
    generator_name: str,
    create: bool,
    seed: int,
    cwd: Path,
) -> tuple[bool, str]:
    """Run the full migration for one trigger and open (or preview) its PR/issue.

    This is `migrate` + `open-pr` fused so `plan --act` can close the loop. Returns
    ``(ok, summary)``; ``ok`` is False only on a hard error -- a blocked/partial
    migration still "succeeds" at producing an actionable issue. Dedupe in
    ``execute_plan`` keeps re-runs from piling up duplicate PRs/issues.
    """
    from .engine import run_migration
    from .generators import build_generator
    from .github import apply_model_change, build_pr_plan, execute_plan
    from .report import render_markdown, result_to_dict, save_report

    try:
        gen = build_generator(generator_name)
        result = run_migration(name, wf, candidate_model, generator=gen, cwd=cwd, seed=seed)
        save_report(result, workflow=wf, cwd=cwd)
        result_dict = result_to_dict(result)
        report_md = render_markdown(result, wf)
        committed = list(result_dict.get("edited_files", []))
        if result_dict.get("succeeded") and committed:
            changed = apply_model_change(wf, result_dict["target_model"], cwd=cwd)
            if changed and changed not in committed:
                committed.append(changed)
        plan_obj = build_pr_plan(result_dict, report_md, committed_files=committed)
        actions = execute_plan(plan_obj, cwd=cwd, create=create, push=True, dedupe=True)
    except DriftlessError as exc:
        return False, f"{name} -> {candidate_model}: error: {exc.message}"

    verb = "opened" if create else "would open"
    tail = f" [{actions[-1]}]" if actions else ""
    return True, (
        f"{name} -> {candidate_model}: {result.status.value} -> "
        f"{verb} {plan_obj.kind}{tail}"
    )


def _act_on_data_change(
    name: str,
    wf,
    *,
    generator_name: str,
    create: bool,
    seed: int,
    cwd: Path,
) -> tuple[bool, str]:
    """Run `refine` for one data-change trigger and open (or preview) its PR.

    The `refine` analog of :func:`_act_on_trigger`: same engine in MAXIMIZE mode
    (model pinned), then a PR/issue. Records the processed dataset signature so a
    re-poll won't re-fire on the same data. ``ok`` is False only on a hard error.
    """
    from .datastate import dataset_signature, record_dataset_state
    from .engine import Objective, run_migration
    from .generators import build_generator
    from .github import build_pr_plan, execute_plan
    from .report import render_markdown, result_to_dict, save_report

    try:
        gen = build_generator(generator_name)
        result = run_migration(
            name, wf, wf.model.current, generator=gen, cwd=cwd, seed=seed,
            objective=Objective.MAXIMIZE,
        )
        save_report(result, workflow=wf, cwd=cwd)
        report_md = render_markdown(result, wf)
        committed = list(result_to_dict(result).get("edited_files", []))
        plan_obj = build_pr_plan(result_to_dict(result), report_md, committed_files=committed)
        actions = execute_plan(plan_obj, cwd=cwd, create=create, push=True, dedupe=True)
        # Only mark the dataset processed once we've actually acted on it.
        if create:
            record_dataset_state(name, dataset_signature(wf, cwd=cwd), cwd=cwd)
    except DriftlessError as exc:
        return False, f"{name} (refine): error: {exc.message}"

    verb = "opened" if create else "would open"
    tail = f" [{actions[-1]}]" if actions else ""
    return True, f"{name} (refine): {result.status.value} -> {verb} {plan_obj.kind}{tail}"


@app.command()
def plan(
    contract_path: Path = typer.Option(None, "--contract", help="Path to driftless.yml."),
    as_of: str = typer.Option(
        None, "--as-of", help="Evaluate retirement dates as of this ISO date (default: today)."
    ),
    opportunistic: bool = typer.Option(
        True,
        "--opportunistic/--no-opportunistic",
        help="Also propose cost/quality/new-model candidates (policy-gated).",
    ),
    act: bool = typer.Option(
        False,
        "--act",
        help="Run the full migration + open a PR/issue for each actionable trigger.",
    ),
    create: bool = typer.Option(
        False,
        "--create",
        help="With --act, actually run git/gh (default: dry run / preview).",
    ),
    generator: str = typer.Option(
        "llm", "--generator", "-g", help="Repair engine for --act: 'llm' or 'none'."
    ),
) -> None:
    """Discover at-risk workflows and apply the migration policy (CI triage).

    For each trigger (a deprecation, or a policy-enabled cost/quality/new-model
    opportunity), run a quick baseline-vs-candidate comparison and let the policy
    decide whether to open a PR, an issue, or do nothing. Exits non-zero if any
    workflow needs action (so it gates CI).
    """
    from datetime import date

    from .compare import compare_models
    from .discovery import (
        discover_deprecation_triggers,
        discover_opportunistic_triggers,
        estimate_cost_change_pct,
        group_triggers,
    )
    from .policy import EvalOutcome, load_policy, should_migrate

    try:
        contract = load_contract(contract_path)
        policy = load_policy()
        as_of_date = date.fromisoformat(as_of) if as_of else None
        triggers = discover_deprecation_triggers(contract, as_of=as_of_date)
        if opportunistic:
            triggers = triggers + discover_opportunistic_triggers(
                contract, policy=policy, as_of=as_of_date
            )
    except DriftlessError as exc:
        _fail(exc)
        return
    except ValueError:
        err_console.print(f"[bold red]error:[/] invalid --as-of date: {as_of!r}")
        raise typer.Exit(code=1)

    if not triggers:
        console.print("[green]No actionable triggers in any workflow.[/] Nothing to plan.")
        raise typer.Exit(code=0)

    table = Table(title="Migration plan")
    table.add_column("Workflow")
    table.add_column("Trigger")
    table.add_column("Migrate")
    table.add_column("Retires")
    table.add_column("Naive")
    table.add_column("Decision")

    decisions = []
    reasons: list[str] = []
    actionable_triggers = []
    for dt in triggers:
        trig = dt.trigger
        wf = contract.workflow(dt.workflow)
        retires = f"{trig.days_until_retirement}d" if trig.days_until_retirement is not None else "-"
        try:
            comparison = compare_models(dt.workflow, wf, trig.candidate_model, cwd=Path.cwd())
            passed = comparison.passed
            f1_delta = (
                comparison.target.f1 - comparison.baseline.f1
                if comparison.target.f1 is not None and comparison.baseline.f1 is not None
                else None
            )
            # Prefer measured cost; fall back to a catalog-pricing estimate so
            # cost decisions are actionable even without per-record cost data.
            bc, tc = comparison.baseline.total_cost, comparison.target.total_cost
            cost_change: float | None
            if bc and tc and bc > 0:
                cost_change = (tc - bc) / bc
            else:
                cost_change = estimate_cost_change_pct(trig.current_model, trig.candidate_model)
            outcome = EvalOutcome(
                passed_thresholds=passed,
                migration_status="model_change_only" if passed else "blocked",
                f1_delta=f1_delta,
                cost_change_pct=cost_change,
            )
            naive = "[green]passes[/]" if passed else "[red]regresses[/]"
        except DriftlessError as exc:
            outcome = EvalOutcome(passed_thresholds=False, migration_status="blocked")
            naive = f"[red]error[/] ({exc.message})"

        decision = should_migrate(trig, outcome, policy)
        decisions.append(decision)
        if decision.should_act:
            actionable_triggers.append(dt)
        astyle = _ACTION_STYLE.get(decision.action.value, "white")
        ustyle = _URGENCY_STYLE.get(decision.urgency.value, "white")
        table.add_row(
            dt.workflow,
            trig.kind.value,
            f"{trig.current_model} -> {trig.candidate_model}",
            retires,
            naive,
            f"[{astyle}]{decision.action.value.upper()}[/] [{ustyle}]({decision.urgency.value})[/]",
        )
        reasons.append(f"{dt.workflow} ({trig.kind.value}): {decision.reason}")

    console.print(table)
    console.print("\n[bold]Why[/]:")
    for r in reasons:
        console.print(f"  - {r}", markup=False)

    actionable = [d for d in decisions if d.should_act]
    if actionable:
        groups = group_triggers(actionable_triggers)
        console.print(
            f"\n[yellow]{len(actionable)} workflow(s) need action[/] "
            f"across {len(groups)} model move(s):"
        )
        for g in groups:
            wfs = ", ".join(g.workflows)
            console.print(
                f"  - [bold]{g.current_model} -> {g.candidate_model}[/] "
                f"({g.kind.value}): {wfs}",
                markup=False,
            )

        if act:
            console.print(
                f"\n[bold]{'Acting' if create else 'Dry run (--act)'}[/] on "
                f"{len(actionable_triggers)} trigger(s)..."
            )
            any_fail = False
            for dt in actionable_triggers:
                wf = contract.workflow(dt.workflow)
                ok, summary = _act_on_trigger(
                    dt.workflow,
                    wf,
                    dt.trigger.candidate_model,
                    generator_name=generator,
                    create=create,
                    seed=0,
                    cwd=Path.cwd(),
                )
                console.print(f"  [{'green' if ok else 'red'}]•[/] {summary}", markup=True)
                any_fail = any_fail or not ok
            if not create:
                console.print(
                    "\n[dim]re-run with --act --create to apply "
                    "(requires git + gh authenticated).[/]"
                )
            raise typer.Exit(code=1 if any_fail else 0)

        console.print(
            "Run [bold]driftless plan --act[/] to migrate + open PRs automatically, or do it "
            "manually: [bold]driftless migrate -w <workflow> --to <model>[/] then "
            "[bold]driftless open-pr -w <workflow>[/]."
        )
        raise typer.Exit(code=1)
    console.print("\n[green]No action required by policy.[/]")


_STATUS_STYLE = {
    "model_change_only": "green",
    "pass": "green",
    "partial": "yellow",
    "blocked": "red",
    "no_change": "cyan",
}


@app.command()
def migrate(
    workflow: str = typer.Option(..., "--workflow", "-w"),
    to: str = typer.Option(..., "--to", help="Target model."),
    contract_path: Path = typer.Option(None, "--contract", help="Path to driftless.yml."),
    seed: int = typer.Option(0, "--seed", help="Split seed for reproducibility."),
    generator: str = typer.Option(
        "llm", "--generator", "-g", help="Repair engine: 'llm' or 'none'."
    ),
    generator_provider: str = typer.Option(
        None, "--generator-provider", help="Override LLM provider (openai|anthropic)."
    ),
    generator_model: str = typer.Option(
        None, "--generator-model", help="Override the model used to propose repairs."
    ),
    candidates: int = typer.Option(
        2, "--candidates", help="Candidate patches to propose per iteration "
        "(widened automatically when an iteration stalls).",
    ),
) -> None:
    """Attempt a migration: repair editable files, validate on holdout, report."""
    from .engine import MigrationStatus, run_migration
    from .generators import build_generator

    try:
        contract = load_contract(contract_path)
        wf = contract.workflow(workflow)
        _preflight(wf, to)
        gen = build_generator(
            generator,
            provider=generator_provider,
            model=generator_model,
            num_candidates=candidates,
        )
        gen_desc = (
            "no-op"
            if gen is None
            else f"llm ({getattr(gen, 'provider', 'unknown')}:{getattr(gen, 'model', 'unknown')})"
        )
        progress_log(
            f"migrate: {workflow} {wf.model.current} -> {to} "
            f"(max {wf.migration.max_iterations} iterations, repair={gen_desc})"
        )
        console.print(
            f"Migrating [bold]{workflow}[/]: {wf.model.current} -> {to} "
            f"(max {wf.migration.max_iterations} iterations, repair={gen_desc})..."
        )
        result = run_migration(workflow, wf, to, generator=gen, cwd=Path.cwd(), seed=seed)
    except DriftlessError as exc:
        _fail(exc)
        return

    style = _STATUS_STYLE.get(result.status.value, "white")
    console.print(f"\n[bold {style}]{result.status.value.upper()}[/] — {result.message}")

    table = Table(show_header=True)
    table.add_column("Metric")
    table.add_column("Baseline", justify="right")
    table.add_column("Naive target", justify="right")
    table.add_column("Final", justify="right")
    for label, attr, pct in (
        ("F1", "f1", False),
        ("Precision", "precision", False),
        ("Accuracy", "accuracy", False),
        ("Score / pass-rate", "score", False),
        ("Schema error rate", "schema_error_rate", True),
        ("Refusal rate", "refusal_rate", True),
    ):
        table.add_row(
            label,
            _fmt(getattr(result.baseline, attr), pct=pct),
            _fmt(getattr(result.naive_target, attr), pct=pct),
            _fmt(getattr(result.final, attr), pct=pct),
        )
    console.print(table)

    if result.holdout is not None:
        console.print("\n[bold]Holdout validation[/]:")
        for c in result.holdout_checks:
            mark = "[green]PASS[/]" if c.passed else "[red]FAIL[/]"
            console.print(f"  {mark} {c.name}: {c.detail}")

    if result.edited_files:
        console.print("\n[bold]Edited files[/]:")
        for f in result.edited_files:
            console.print(f"  [green]M[/] {f}")

    if result.remaining_clusters:
        console.print("\n[bold]Remaining failure clusters[/]:")
        for cl in result.remaining_clusters:
            console.print(f"  [{cl.count:>3}] {cl.kind}: {cl.key}")

    if result.status == MigrationStatus.PARTIAL:
        console.print(
            "\n[yellow]Changes were not committed.[/] Review remaining clusters above."
        )

    from .report import save_report

    md_path, json_path = save_report(result, workflow=wf, cwd=Path.cwd())
    console.print(f"\n[dim]report: {md_path}[/]")
    console.print(f"[dim]result: {json_path}[/]")
    raise typer.Exit(code=0 if result.succeeded else 1)


@app.command()
def refine(
    workflow: str = typer.Option(..., "--workflow", "-w"),
    contract_path: Path = typer.Option(None, "--contract", help="Path to driftless.yml."),
    seed: int = typer.Option(0, "--seed", help="Split seed for reproducibility."),
    generator: str = typer.Option(
        "llm", "--generator", "-g", help="Repair engine: 'llm' or 'none'."
    ),
    generator_provider: str = typer.Option(
        None, "--generator-provider", help="Override LLM provider (openai|anthropic)."
    ),
    generator_model: str = typer.Option(
        None, "--generator-model", help="Override the model used to propose repairs."
    ),
    candidates: int = typer.Option(
        2, "--candidates", help="Candidate patches to propose per iteration "
        "(widened automatically when an iteration stalls).",
    ),
) -> None:
    """Re-optimize a prompt for a changed eval dataset (model stays pinned).

    The same engine as `migrate`, but triggered by *dataset* drift instead of a
    model swap: the model is held at `model.current`, the old thresholds are
    treated as stale, and the loop maximizes the primary metric within
    `max_iterations`. It validates the winner on a never-tuned holdout and
    proposes a fresh `thresholds:` block for you to accept.
    """
    import yaml

    from .engine import MigrationStatus, Objective, run_migration
    from .generators import build_generator

    try:
        contract = load_contract(contract_path)
        wf = contract.workflow(workflow)
        gen = build_generator(
            generator,
            provider=generator_provider,
            model=generator_model,
            num_candidates=candidates,
        )
        gen_desc = (
            "no-op"
            if gen is None
            else f"llm ({getattr(gen, 'provider', 'unknown')}:{getattr(gen, 'model', 'unknown')})"
        )
        progress_log(
            f"refine: {workflow} (model pinned to {wf.model.current}, "
            f"max {wf.migration.max_iterations} iterations, repair={gen_desc})"
        )
        console.print(
            f"Refining [bold]{workflow}[/] for the updated dataset "
            f"(model pinned to {wf.model.current}, max {wf.migration.max_iterations} "
            f"iterations, repair={gen_desc})..."
        )
        result = run_migration(
            workflow,
            wf,
            wf.model.current,
            generator=gen,
            cwd=Path.cwd(),
            seed=seed,
            objective=Objective.MAXIMIZE,
        )
    except DriftlessError as exc:
        _fail(exc)
        return

    style = _STATUS_STYLE.get(result.status.value, "white")
    console.print(f"\n[bold {style}]{result.status.value.upper()}[/] — {result.message}")

    table = Table(show_header=True, title="Scorecard on the updated dataset")
    table.add_column("Metric")
    table.add_column("Current prompt", justify="right")
    table.add_column("Refined prompt", justify="right")
    for label, attr, pct in (
        ("F1", "f1", False),
        ("Precision", "precision", False),
        ("Accuracy", "accuracy", False),
        ("Score / pass-rate", "score", False),
        ("Schema error rate", "schema_error_rate", True),
        ("Refusal rate", "refusal_rate", True),
    ):
        table.add_row(
            label,
            _fmt(getattr(result.baseline, attr), pct=pct),
            _fmt(getattr(result.final, attr), pct=pct),
        )
    console.print(table)

    if result.holdout is not None:
        console.print("\n[bold]Holdout validation[/] (refined vs current, no-regression):")
        for c in result.holdout_checks:
            mark = "[green]PASS[/]" if c.passed else "[red]FAIL[/]"
            console.print(f"  {mark} {c.name}: {c.detail}")

    if result.edited_files:
        console.print("\n[bold]Edited files[/]:")
        for f in result.edited_files:
            console.print(f"  [green]M[/] {f}")

    if result.suggested_thresholds:
        snippet = yaml.safe_dump(
            {"thresholds": result.suggested_thresholds},
            sort_keys=False,
            default_flow_style=False,
        )
        console.print(
            "\n[bold]Suggested thresholds[/] (from refined holdout metrics) — "
            f"the old dataset's bar is stale; paste into [bold]{workflow}[/]:\n"
        )
        console.print(snippet, markup=False)

    from .datastate import dataset_signature, record_dataset_state
    from .report import save_report

    md_path, json_path = save_report(result, workflow=wf, cwd=Path.cwd())
    # Mark this dataset version as processed (full signature, so the poll's
    # meaningful-change delta works) and the poll won't re-fire on the same data.
    record_dataset_state(
        workflow, dataset_signature(wf, cwd=Path.cwd()), cwd=Path.cwd()
    )
    console.print(f"\n[dim]report: {md_path}[/]")
    console.print(f"[dim]result: {json_path}[/]")
    raise typer.Exit(code=0 if result.succeeded else 1)


@app.command()
def poll(
    contract_path: Path = typer.Option(None, "--contract", help="Path to driftless.yml."),
    fetch: bool = typer.Option(
        True, "--fetch/--no-fetch", help="Refresh external datasets (eval.data_source) first."
    ),
    act: bool = typer.Option(
        False, "--act", help="Run refine + open a PR for each meaningfully-changed dataset."
    ),
    create: bool = typer.Option(
        False, "--create", help="With --act, actually run git/gh (default: dry run / preview)."
    ),
    generator: str = typer.Option(
        "llm", "--generator", "-g", help="Repair engine for --act: 'llm' or 'none'."
    ),
    seed: int = typer.Option(0, "--seed", help="Split seed for reproducibility."),
) -> None:
    """Detect *external* eval-dataset changes and refine the prompt (scheduled job).

    For data that lives outside the repo (git can't see it), this fetches each
    workflow's dataset (`eval.data_source`), fingerprints it, and compares against
    the last-seen signature in `.driftless/state.json`. Only a *meaningful*
    change (per `policy.data_change`) triggers a refine, so whitespace/reordering/a
    row or two stay quiet. First-ever sightings are recorded as a baseline.

    Exits non-zero when a workflow needs a refine and `--act` wasn't given, so it
    gates CI. (For *in-repo* data, prefer the path-filtered refine Action.)
    """
    from datetime import date

    from .datasource import fetch_dataset
    from .datastate import dataset_signature, load_state, record_dataset_state
    from .discovery import discover_data_change_triggers
    from .policy import load_policy

    try:
        contract = load_contract(contract_path)
        policy = load_policy()
        cwd = Path.cwd()

        if fetch:
            for name, wf in contract.workflows.items():
                if wf.eval.data_source is None:
                    continue
                result = fetch_dataset(wf, cwd=cwd)
                for a in result.actions:
                    console.print(f"[dim]fetch {name}: {a}[/]", markup=False)

        state = load_state(cwd=cwd)
        triggers = discover_data_change_triggers(
            contract,
            cwd=cwd,
            state=state,
            policy=policy.data_change,
            as_of=date.today(),
        )

        # Record baselines for never-seen workflows so real changes are detected
        # next time (and they aren't perpetually "first seen").
        for name, wf in contract.workflows.items():
            if wf.eval.labels_path and name not in state:
                record_dataset_state(name, dataset_signature(wf, cwd=cwd), cwd=cwd)
                console.print(f"[dim]baseline recorded for {name}[/]")
    except DriftlessError as exc:
        _fail(exc)
        return

    if not triggers:
        console.print("[green]No meaningful dataset changes.[/] Nothing to refine.")
        raise typer.Exit(code=0)

    table = Table(title="Dataset changes")
    table.add_column("Workflow")
    table.add_column("Changed rows", justify="right")
    table.add_column("Detail")
    for dt in triggers:
        d = dt.delta
        detail = (
            f"+{d.added} / -{d.removed} / ~{d.changed} of {d.new_count}"
            if d
            else "changed"
        )
        table.add_row(dt.workflow, str(dt.changed_rows), detail)
    console.print(table)

    if act:
        console.print(
            f"\n[bold]{'Acting' if create else 'Dry run (--act)'}[/] on "
            f"{len(triggers)} dataset change(s)..."
        )
        any_fail = False
        for dt in triggers:
            wf = contract.workflow(dt.workflow)
            ok, summary = _act_on_data_change(
                dt.workflow, wf, generator_name=generator, create=create, seed=seed, cwd=Path.cwd()
            )
            console.print(f"  [{'green' if ok else 'red'}]•[/] {summary}", markup=True)
            any_fail = any_fail or not ok
        if not create:
            console.print(
                "\n[dim]re-run with --act --create to apply "
                "(requires git + gh authenticated).[/]"
            )
        raise typer.Exit(code=1 if any_fail else 0)

    console.print(
        "\nRun [bold]driftless poll --act[/] to refine + open PRs automatically, or "
        "[bold]driftless refine -w <workflow>[/] manually."
    )
    raise typer.Exit(code=1)


@app.command(name="open-pr")
def open_pr(
    workflow: str = typer.Option(..., "--workflow", "-w"),
    contract_path: Path = typer.Option(None, "--contract", help="Path to driftless.yml."),
    create: bool = typer.Option(
        False, "--create", help="Actually run git/gh (default: dry run)."
    ),
    push: bool = typer.Option(True, "--push/--no-push", help="Push the branch when creating."),
    dedupe: bool = typer.Option(
        True, "--dedupe/--no-dedupe",
        help="Skip creation if an open PR/issue for this move already exists.",
    ),
) -> None:
    """Open a PR (or issue) from the latest migration result for a workflow."""
    import json

    from .github import apply_model_change, build_pr_plan, execute_plan

    cwd = Path.cwd()
    result_path = cwd / ".driftless" / "migrations" / f"{workflow}.json"
    report_path = cwd / ".driftless" / "reports" / f"{workflow}.md"
    if not result_path.is_file() or not report_path.is_file():
        err_console.print(
            f"[yellow]no migration result for {workflow!r}[/] — run "
            f"[bold]driftless migrate -w {workflow} --to <model>[/] first"
        )
        raise typer.Exit(code=1)

    result = json.loads(result_path.read_text(encoding="utf-8"))
    report_md = report_path.read_text(encoding="utf-8")

    try:
        contract = load_contract(contract_path)
        wf = contract.workflow(workflow)
        committed = list(result.get("edited_files", []))
        if result.get("succeeded") and committed:
            changed = apply_model_change(wf, result["target_model"], cwd=cwd)
            if changed and changed not in committed:
                committed.append(changed)
        plan = build_pr_plan(result, report_md, committed_files=committed)
        actions = execute_plan(plan, cwd=cwd, create=create, push=push, dedupe=dedupe)
    except DriftlessError as exc:
        _fail(exc)
        return

    console.print(f"[bold]{'Creating' if create else 'Dry run'}[/] — {plan.kind.upper()}")
    for a in actions:
        console.print(f"  - {a}", markup=False)
    if not create:
        console.print(
            "\n[dim]re-run with --create to apply (requires git + gh authenticated).[/]"
        )


@app.command(name="judge-check")
def judge_check(
    workflow: str = typer.Option(..., "--workflow", "-w"),
    contract_path: Path = typer.Option(None, "--contract", help="Path to driftless.yml."),
    enforce: bool = typer.Option(
        False,
        "--enforce",
        help="Apply eval.judge max_mae/min_correlation gates (same as migrate/compare).",
    ),
) -> None:
    """Measure LLM-judge agreement against a human calibration set."""
    from .judges import build_judge, judge_agreement, require_judge_agreement

    try:
        contract = load_contract(contract_path)
        wf = contract.workflow(workflow)
    except DriftlessError as exc:
        _fail(exc)
        return

    if wf.eval.grading != "judge" or wf.eval.judge is None:
        _fail(
            DriftlessError(
                f"{workflow!r} is not judge-graded",
                hint="add eval.judge to the workflow in driftless.yml",
            )
        )
        return

    spec = wf.eval.judge
    if not spec.calibration_path:
        _fail(
            DriftlessError(
                "eval.judge.calibration_path is not set",
                hint="add a human-scored JSONL file for judge agreement",
            )
        )
        return

    judge = build_judge(spec)
    try:
        agreement = (
            require_judge_agreement(judge, spec)
            if enforce
            else judge_agreement(judge, spec)
        )
    except DriftlessError as exc:
        _fail(exc)
        return

    if agreement is None:
        _fail(DriftlessError("calibration set is empty or produced no scores"))
        return

    console.print(f"[bold]{workflow}[/] — judge calibration check\n")
    console.print(f"  records: {agreement.n}")
    console.print(f"  MAE: {agreement.mean_abs_error:.3f}")
    corr = f"{agreement.correlation:.3f}" if agreement.correlation is not None else "n/a"
    console.print(f"  correlation: {corr}")

    gate_bits: list[str] = []
    if spec.max_mae is not None:
        ok = agreement.mean_abs_error <= spec.max_mae
        gate_bits.append(f"max_mae={spec.max_mae:g} ({'ok' if ok else 'FAIL'})")
    if spec.min_correlation is not None:
        ok = agreement.correlation is not None and agreement.correlation >= spec.min_correlation
        gate_bits.append(f"min_correlation={spec.min_correlation:g} ({'ok' if ok else 'FAIL'})")
    if gate_bits:
        console.print("  gates: " + ", ".join(gate_bits))

    if enforce:
        console.print(f"\n[green]gates passed[/] — {agreement.summary}")
    else:
        console.print(f"\n[dim]{agreement.summary}[/]")
        if spec.max_mae is not None or spec.min_correlation is not None:
            console.print("[dim]re-run with --enforce to apply contract gates[/]")


@app.command()
def report(
    workflow: str = typer.Option(None, "--workflow", "-w", help="Workflow to show (default: all)."),
    raw: bool = typer.Option(False, "--raw", help="Print raw markdown instead of rendering."),
) -> None:
    """Render the latest migration report(s)."""
    from rich.markdown import Markdown

    reports_dir = Path.cwd() / ".driftless" / "reports"
    if not reports_dir.is_dir():
        err_console.print(
            "[yellow]no reports found[/] — run `driftless migrate` first"
        )
        raise typer.Exit(code=1)

    if workflow:
        paths = [reports_dir / f"{workflow}.md"]
        if not paths[0].is_file():
            err_console.print(f"[yellow]no report for workflow {workflow!r}[/]")
            raise typer.Exit(code=1)
    else:
        paths = sorted(reports_dir.glob("*.md"))
        if not paths:
            err_console.print("[yellow]no reports found[/]")
            raise typer.Exit(code=1)

    for i, path in enumerate(paths):
        if i:
            console.rule()
        text = path.read_text(encoding="utf-8")
        console.print(text if raw else Markdown(text))


@app.command()
def view(
    workflow: str | None = typer.Option(
        None, "--workflow", "-w", help="Open a specific workflow run."
    ),
    port: int = typer.Option(8777, "--port", help="Local port for the viewer."),
    no_open: bool = typer.Option(False, "--no-open", help="Do not launch a browser tab."),
) -> None:
    """Open the optimization run viewer (charts + attempt log)."""
    from .view import serve_runs

    try:
        serve_runs(
            cwd=Path.cwd(),
            port=port,
            open_browser=not no_open,
            workflow=workflow,
        )
    except DriftlessError as exc:
        _fail(exc)


if __name__ == "__main__":
    app()
