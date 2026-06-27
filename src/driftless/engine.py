"""The migration engine: iterate, select the best candidate, validate on holdout.

This is the core value of the product. The engine:

1. Runs the current and target models through the *real* workflow on a tuning
   split.
2. If the naive swap already passes thresholds, it's a model-ID change only.
3. Otherwise it clusters failures, asks a :class:`PatchGenerator` for candidate
   edits to the **editable files only**, evaluates them on the tuning split,
   keeps the best, and repeats up to ``max_iterations``.
4. The winning candidate must pass thresholds on a holdout split it never tuned
   against before any files are committed.

The patch-*generation* step is intentionally pluggable. Drop your validated
repair logic in by implementing :class:`PatchGenerator`; everything around it
(orchestration, edit-scope enforcement, holdout gating) lives here.
"""

from __future__ import annotations

import difflib
from collections import Counter
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Protocol

from .calibrate import suggest_thresholds
from .compare import ThresholdCheck, check_thresholds
from .contract import ThresholdsSpec, Workflow
from .errors import DriftlessError
from .evaluation import Metrics, RecordRow, RunAnalysis, analyze
from .harness import run_workflow
from .progress import log as progress_log
from .splits import make_splits, materialize_inputs


# --------------------------------------------------------------------------- #
# Failure clustering
# --------------------------------------------------------------------------- #
@dataclass
class FailureCluster:
    kind: str  # "schema_error" | "refusal" | "misclassification"
    key: str  # human-readable label, e.g. "billing -> technical"
    count: int
    example_indices: list[int] = field(default_factory=list)


def cluster_failures(rows: list[RecordRow], *, max_examples: int = 5) -> list[FailureCluster]:
    """Group failing records into actionable clusters.

    Handles all three grading modes: classification (gold -> pred), customer
    pass/fail checks, and customer numeric scores (the relatively-worst rows).
    """
    schema: list[int] = []
    refusals: list[int] = []
    misclass: dict[tuple[Any, Any], list[int]] = {}
    field_errs: dict[str, list[int]] = {}
    low_score: list[int] = []
    failed_checks: list[int] = []

    for row in rows:
        if row.is_schema_error:
            schema.append(row.index)
        elif row.is_refusal:
            refusals.append(row.index)
        elif row.field_errors:
            # Extraction: the row may have several wrong fields; key on each.
            for f in row.field_errors:
                field_errs.setdefault(f, []).append(row.index)
        elif row.is_low_score:
            low_score.append(row.index)
        elif row.is_correct is False:
            if row.gold is not None:
                misclass.setdefault((row.gold, row.predicted), []).append(row.index)
            else:
                failed_checks.append(row.index)  # customer pass/fail mode

    clusters: list[FailureCluster] = []
    if schema:
        clusters.append(FailureCluster("schema_error", "invalid output schema", len(schema), schema[:max_examples]))
    if refusals:
        clusters.append(FailureCluster("refusal", "model refused / empty label", len(refusals), refusals[:max_examples]))
    for (gold, pred), idx in sorted(misclass.items(), key=lambda kv: -len(kv[1])):
        clusters.append(
            FailureCluster("misclassification", f"{gold} -> {pred}", len(idx), idx[:max_examples])
        )
    for field_name, idx in sorted(field_errs.items(), key=lambda kv: -len(kv[1])):
        clusters.append(
            FailureCluster("field_error", f"wrong field: {field_name}", len(idx), idx[:max_examples])
        )
    if low_score:
        # Surface the lowest-scoring rows first -- the most useful to repair.
        score_by_index = {r.index: (r.score if r.score is not None else 0.0) for r in rows}
        examples = sorted(low_score, key=lambda i: score_by_index[i])[:max_examples]
        clusters.append(
            FailureCluster("low_score", "below-average score", len(low_score), examples)
        )
    if failed_checks:
        clusters.append(
            FailureCluster("failed_check", "failed pass/fail check", len(failed_checks), failed_checks[:max_examples])
        )
    return clusters


# Below these sizes, a single split is too noisy to trust on its own.
MIN_TOTAL_EXAMPLES = 30
MIN_HOLDOUT_EXAMPLES = 15


def assess_split_sizes(
    n_total: int, n_holdout: int, *, holdout_required: bool
) -> list[str]:
    """Low-confidence warnings for small datasets/holdouts.

    Small evals make thresholds noisy and a passing holdout potentially lucky.
    We surface this rather than silently presenting a confident-looking verdict.
    """
    warnings: list[str] = []
    if n_total < MIN_TOTAL_EXAMPLES:
        warnings.append(
            f"Small dataset: {n_total} labeled examples (< {MIN_TOTAL_EXAMPLES}). "
            "Metrics and thresholds are low-confidence; add more labeled rows for a "
            "reliable migration decision."
        )
    if holdout_required and 0 < n_holdout < MIN_HOLDOUT_EXAMPLES:
        granularity = 100.0 / n_holdout
        warnings.append(
            f"Small holdout: {n_holdout} examples, so each one shifts a metric by "
            f"~{granularity:.0f}%. A passing holdout may not generalize."
        )
    return warnings


def cluster_trajectories(
    history: list[list[FailureCluster]],
) -> dict[str, list[int]]:
    """Per-cluster counts across iterations, e.g. ``{"schema_error:...": [6,2,0]}``.

    Shows which failure modes are shrinking, stuck, or newly introduced, so both
    the optimizer and the report can reason about the search trajectory.
    """
    keys: list[str] = []
    seen: set[str] = set()
    for snapshot in history:
        for c in snapshot:
            key = f"{c.kind}:{c.key}"
            if key not in seen:
                seen.add(key)
                keys.append(key)
    traj: dict[str, list[int]] = {k: [] for k in keys}
    for snapshot in history:
        counts = {f"{c.kind}:{c.key}": c.count for c in snapshot}
        for k in keys:
            traj[k].append(counts.get(k, 0))
    return traj


# --------------------------------------------------------------------------- #
# Patch generation seam
# --------------------------------------------------------------------------- #
@dataclass
class Patch:
    """A candidate edit. ``files`` maps editable file paths -> new content."""

    files: dict[str, str]
    rationale: str = ""
    kind: str = "prompt"


@dataclass
class AttemptRecord:
    """One candidate patch that was tried, and how it scored on tuning.

    Accumulated across iterations so the optimizer can see what it already tried
    (and avoid repeating unproductive edits), and so the report can show the
    search trajectory as evidence.
    """

    iteration: int
    kind: str
    rationale: str
    files: list[str]
    primary: float
    schema_error_rate: float | None
    refusal_rate: float | None
    passed_tuning: bool
    accepted: bool  # became the new best candidate
    error: str | None = None  # set if the candidate failed to evaluate (e.g. broke the workflow)
    diff_size: int | None = None  # changed lines (added + removed) vs the original editable files
    file_contents: dict[str, str] = field(default_factory=dict)  # proposed file bodies for this candidate


@dataclass
class PatchContext:
    """Everything a generator needs to propose edits for one iteration."""

    workflow: Workflow
    workflow_name: str
    target_model: str
    iteration: int
    editable_files: dict[str, str]
    baseline: Metrics
    current: Metrics
    clusters: list[FailureCluster]
    rows: list[RecordRow]
    cwd: Path = field(default_factory=Path.cwd)
    experiment_log: list[AttemptRecord] = field(default_factory=list)
    # Cluster snapshots of the running best, one per iteration so far.
    cluster_history: list[list[FailureCluster]] = field(default_factory=list)
    # Read-only surrounding code (files.context): {path: content}. For the
    # optimizer to understand output parsing / pre/post-processing; never edited.
    context_files: dict[str, str] = field(default_factory=dict)


class PatchGenerator(Protocol):
    """Implement this to plug in your validated prompt/config repair logic."""

    def generate(self, context: PatchContext) -> list[Patch]:
        ...


class NoOpPatchGenerator:
    """Default generator that proposes nothing (loop becomes a no-op).

    Replace with your validated generator to actually repair workflows.
    """

    def generate(self, context: PatchContext) -> list[Patch]:  # noqa: D401
        return []


# --------------------------------------------------------------------------- #
# Edit-scope enforcement + file sandbox
# --------------------------------------------------------------------------- #
def _editable_set(workflow: Workflow, cwd: Path) -> set[Path]:
    return {(cwd / p).resolve() for p in workflow.files.editable}


def validate_patch_scope(patch: Patch, workflow: Workflow, cwd: Path) -> None:
    """Reject any patch that touches a file outside ``files.editable``."""
    allowed = _editable_set(workflow, cwd)
    for rel in patch.files:
        resolved = (cwd / rel).resolve()
        if resolved not in allowed:
            raise DriftlessError(
                f"patch tried to edit non-editable file: {rel}",
                hint="the migration engine may only edit files listed in files.editable",
            )


@contextmanager
def apply_files(file_map: dict[str, str], *, cwd: Path) -> Iterator[None]:
    """Apply file contents temporarily, restoring originals on exit."""
    cwd = cwd.resolve()
    backups: dict[Path, bytes | None] = {}
    try:
        for rel, content in file_map.items():
            path = (cwd / rel).resolve()
            backups[path] = path.read_bytes() if path.exists() else None
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        yield
    finally:
        for path, original in backups.items():
            if original is None:
                if path.exists():
                    path.unlink()
            else:
                path.write_bytes(original)


def commit_files(file_map: dict[str, str], *, cwd: Path) -> list[str]:
    cwd = cwd.resolve()
    written: list[str] = []
    for rel, content in file_map.items():
        path = (cwd / rel).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(rel)
    return sorted(written)


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #
class MigrationStatus(str, Enum):
    MODEL_CHANGE_ONLY = "model_change_only"
    PASS = "pass"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    # refine-only: nothing beat the current prompt within budget, so we keep it.
    NO_CHANGE = "no_change"


class Objective(str, Enum):
    """What the loop optimizes for.

    ``MEET_THRESHOLDS`` (default, used by ``migrate``): stop as soon as a candidate
    clears the contract thresholds on tuning *and* holdout. ``MAXIMIZE`` (used by
    ``refine``): the model is pinned and the dataset changed, so stale thresholds
    don't apply -- instead push the primary metric as high as possible within
    ``max_iterations``, validate the winner on a never-tuned holdout, and propose a
    fresh threshold set from what was achieved.
    """

    MEET_THRESHOLDS = "meet_thresholds"
    MAXIMIZE = "maximize"


@dataclass
class MigrationResult:
    workflow: str
    current_model: str
    target_model: str
    status: MigrationStatus
    iterations: int
    baseline: Metrics
    naive_target: Metrics
    final: Metrics
    holdout: Metrics | None = None
    holdout_checks: list[ThresholdCheck] = field(default_factory=list)
    tuning_checks: list[ThresholdCheck] = field(default_factory=list)
    remaining_clusters: list[FailureCluster] = field(default_factory=list)
    edited_files: list[str] = field(default_factory=list)
    experiment_log: list[AttemptRecord] = field(default_factory=list)
    cluster_history: list[list[FailureCluster]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # refine-only: thresholds derived from the achieved holdout metrics, for the
    # customer to accept/edit (the old dataset's thresholds are stale).
    suggested_thresholds: dict[str, float] = field(default_factory=dict)
    message: str = ""
    # Frozen editable files at loop start — baseline for per-candidate diffs in reports/UI.
    original_editable_files: dict[str, str] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status in (
            MigrationStatus.PASS,
            MigrationStatus.MODEL_CHANGE_ONLY,
            MigrationStatus.NO_CHANGE,
        )


# --------------------------------------------------------------------------- #
# Objective / selection
# --------------------------------------------------------------------------- #
def _primary(metrics: Metrics) -> float:
    if metrics.f1 is not None:
        return metrics.f1
    # Customer-supplied grading: mean score / pass-rate is the headline metric.
    if metrics.score is not None:
        return metrics.score
    if metrics.accuracy is not None:
        return metrics.accuracy
    return 1.0 - (metrics.schema_error_rate or 0.0)


def _score_key(
    metrics: Metrics, thresholds, baseline: Metrics
) -> tuple[bool, float, float, float]:
    passes = all(c.passed for c in check_thresholds(thresholds, baseline, metrics))
    return (
        passes,
        _primary(metrics),
        -(metrics.schema_error_rate or 0.0),
        -(metrics.refusal_rate or 0.0),
    )


def _maximize_key(metrics: Metrics) -> tuple[float, float, float]:
    """Selection key for ``MAXIMIZE``: push primary up, errors/refusals down.

    Ignores threshold pass/fail entirely -- on a changed dataset the contract's
    thresholds are stale, so we just chase the best achievable quality.
    """
    return (
        _primary(metrics),
        -(metrics.schema_error_rate or 0.0),
        -(metrics.refusal_rate or 0.0),
    )


def _patch_diff_size(files: dict[str, str], original: dict[str, str]) -> int:
    """Changed lines (added + removed) of a patch vs. the original editable files.

    Patches carry full file contents, so a "size" measured as raw length would
    punish big files regardless of how much actually changed. Diffing against the
    original instead measures the *edit*, which is what we want for the
    minimal-change tie-breaker and for the report.
    """
    total = 0
    for path, new in files.items():
        old = original.get(path, "")
        for line in difflib.unified_diff(
            old.splitlines(), new.splitlines(), lineterm="", n=0
        ):
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
                total += 1
    return total


def _patch_file_contents(patch: Patch) -> dict[str, str]:
    """Return a copy of the candidate's proposed editable file bodies."""
    return dict(patch.files)


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #
def _generate_candidates(
    generator: PatchGenerator, context: PatchContext, width: int | None
) -> list[Patch]:
    """Ask the generator for patches, optionally widening the candidate pool.

    ``width`` temporarily overrides the generator's ``num_candidates`` for one
    round (restored afterward) so the loop can broaden the search on a stall.
    Generators that don't expose ``num_candidates`` (e.g. scripted test doubles)
    ignore ``width`` and behave exactly as before.
    """
    if width is None or not isinstance(getattr(generator, "num_candidates", None), int):
        return generator.generate(context)
    prev = generator.num_candidates
    generator.num_candidates = width
    try:
        return generator.generate(context)
    finally:
        generator.num_candidates = prev


def _fmt_f1(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "n/a"


def run_migration(
    workflow_name: str,
    workflow: Workflow,
    target_model: str,
    *,
    generator: PatchGenerator | None = None,
    judge: Any | None = None,
    cwd: Path | None = None,
    seed: int = 0,
    objective: Objective = Objective.MEET_THRESHOLDS,
) -> MigrationResult:
    cwd = (cwd or Path.cwd()).resolve()
    generator = generator or NoOpPatchGenerator()
    thresholds = workflow.thresholds
    mig = workflow.migration
    current = workflow.model.current

    # LLM-as-judge grading: build the judge once (unless injected for tests) so
    # every evaluation in the loop grades consistently with the same judge.
    if judge is None and workflow.eval.grading == "judge":
        from .judges import build_judge

        judge = build_judge(workflow.eval.judge)

    if not workflow.model.has_override():
        return MigrationResult(
            workflow=workflow_name,
            current_model=current,
            target_model=target_model,
            status=MigrationStatus.BLOCKED,
            iterations=0,
            baseline=Metrics(n=0, schema_error_rate=None, refusal_rate=0.0),
            naive_target=Metrics(n=0, schema_error_rate=None, refusal_rate=0.0),
            final=Metrics(n=0, schema_error_rate=None, refusal_rate=0.0),
            message="no model override configured; run `driftless configure` first",
        )

    split = make_splits(workflow, cwd=cwd, seed=seed)
    size_warnings = assess_split_sizes(
        len(split.input_lines),
        len(split.holdout_idx),
        holdout_required=mig.holdout_required,
    )

    use_ids = bool(workflow.eval.id_field) and split.gold is not None

    def evaluate_on(
        model: str, idx: list[int], files: dict[str, str] | None = None
    ) -> RunAnalysis:
        file_ctx = apply_files(files, cwd=cwd) if files else nullcontext()
        idx_lines = split.lines_for(idx)
        with materialize_inputs(workflow, idx_lines, cwd=cwd):
            with file_ctx:
                run = run_workflow(workflow, model, cwd=cwd)
                if use_ids:
                    return analyze(
                        workflow,
                        run,
                        gold_by_id=split.gold_by_id_for(idx),
                        inputs=idx_lines,
                        judge=judge,
                        cwd=cwd,
                    )
                return analyze(
                    workflow,
                    run,
                    gold_labels=split.gold_for(idx),
                    inputs=idx_lines,
                    judge=judge,
                    cwd=cwd,
                )

    progress_log(
        f"migration: {len(split.tuning_idx)} tuning / "
        f"{len(split.holdout_idx)} holdout examples"
    )
    progress_log(f"migration: baseline eval ({current}) on tuning split...")
    baseline_tuning = evaluate_on(current, split.tuning_idx).metrics
    progress_log(f"migration: baseline F1={_fmt_f1(baseline_tuning.f1)}")
    progress_log(f"migration: target eval ({target_model}) on tuning split...")
    naive_analysis = evaluate_on(target_model, split.tuning_idx)
    naive_tuning = naive_analysis.metrics
    progress_log(f"migration: target F1={_fmt_f1(naive_tuning.f1)}")

    def holdout_ok(files: dict[str, str] | None) -> tuple[bool, Metrics | None, list[ThresholdCheck]]:
        if not mig.holdout_required:
            return True, None, []
        baseline_holdout = evaluate_on(current, split.holdout_idx).metrics
        holdout_metrics = evaluate_on(target_model, split.holdout_idx, files=files).metrics
        checks = check_thresholds(thresholds, baseline_holdout, holdout_metrics)
        return all(c.passed for c in checks), holdout_metrics, checks

    # Step: naive target already good? (migrate only -- in refine the model is
    # pinned, so the "naive target" is just the current prompt and there's no
    # model-only change to short-circuit on.)
    naive_checks = check_thresholds(thresholds, baseline_tuning, naive_tuning)
    if objective is Objective.MEET_THRESHOLDS and all(c.passed for c in naive_checks):
        ok, holdout_metrics, holdout_checks = holdout_ok(None)
        if ok:
            return MigrationResult(
                workflow=workflow_name,
                current_model=current,
                target_model=target_model,
                status=MigrationStatus.MODEL_CHANGE_ONLY,
                iterations=0,
                baseline=baseline_tuning,
                naive_target=naive_tuning,
                final=naive_tuning,
                holdout=holdout_metrics,
                holdout_checks=holdout_checks,
                tuning_checks=naive_checks,
                warnings=size_warnings,
                message="naive model swap passes thresholds; only the model ID changes",
            )

    # Iterate.
    editable_contents = {
        rel: ((cwd / rel).read_text(encoding="utf-8") if (cwd / rel).is_file() else "")
        for rel in workflow.files.editable
    }
    context_files = {
        rel: ((cwd / rel).read_text(encoding="utf-8") if (cwd / rel).is_file() else "")
        for rel in workflow.files.context
    }
    original_editable = dict(editable_contents)  # frozen baseline for diff sizing
    best_files: dict[str, str] = {}
    best_metrics = naive_tuning
    best_analysis = naive_analysis
    best_size = 0  # diff size of the current best edit (0 == no change yet)
    iterations_run = 0
    experiment_log: list[AttemptRecord] = []
    cluster_history: list[list[FailureCluster]] = []

    # Adaptive search width: a narrow round can miss a fix that needs a bolder
    # edit (e.g. a counterintuitive labeling rule a single example can't convey).
    # Stay cheap when progressing; widen the candidate pool once before giving up
    # on a stall. Only meaningful for generators that support multiple candidates.
    base_width = getattr(generator, "num_candidates", None)
    can_widen = isinstance(base_width, int) and base_width >= 1
    escalated_width = max(base_width * 3, 5) if can_widen else None
    widened = False

    for i in range(mig.max_iterations):
        iterations_run += 1
        clusters = cluster_failures(best_analysis.rows)
        cluster_history.append(clusters)
        progress_log(
            f"migration: iteration {i + 1}/{mig.max_iterations} — "
            f"{len(clusters)} failure cluster(s), best F1={_fmt_f1(best_metrics.f1)}"
        )
        context = PatchContext(
            workflow=workflow,
            workflow_name=workflow_name,
            target_model=target_model,
            iteration=i,
            editable_files=dict(editable_contents),
            baseline=baseline_tuning,
            current=best_metrics,
            clusters=clusters,
            rows=best_analysis.rows,
            cwd=cwd,
            experiment_log=list(experiment_log),
            cluster_history=list(cluster_history),
            context_files=context_files,
        )
        patches = _generate_candidates(
            generator, context, escalated_width if widened else None
        )
        if not patches:
            progress_log("migration: no repair candidates produced; stopping")
            break

        progress_log(f"migration: evaluating {len(patches)} candidate patch(es)...")
        improved = False
        for cand_idx, patch in enumerate(patches, start=1):
            progress_log(f"migration: candidate {cand_idx}/{len(patches)}...")
            # A single bad candidate (out-of-scope edit, or content that breaks the
            # workflow -- e.g. invalid YAML/JSON) must not abort the whole search.
            # Record it as a failed attempt and move on to the next candidate.
            cand_size = _patch_diff_size(patch.files, original_editable)
            try:
                validate_patch_scope(patch, workflow, cwd)
                analysis = evaluate_on(target_model, split.tuning_idx, files=patch.files)
            except DriftlessError as exc:
                experiment_log.append(
                    AttemptRecord(
                        iteration=i,
                        kind=patch.kind,
                        rationale=patch.rationale,
                        files=sorted(patch.files),
                        primary=_primary(best_metrics),
                        schema_error_rate=None,
                        refusal_rate=None,
                        passed_tuning=False,
                        accepted=False,
                        error=str(exc)[:300],
                        diff_size=cand_size,
                        file_contents=_patch_file_contents(patch),
                    )
                )
                continue
            if objective is Objective.MAXIMIZE:
                cand_key = _maximize_key(analysis.metrics)
                best_key = _maximize_key(best_metrics)
            else:
                cand_key = _score_key(analysis.metrics, thresholds, baseline_tuning)
                best_key = _score_key(best_metrics, thresholds, baseline_tuning)
            # Strictly better score wins; on a tie, prefer the smaller edit -- a
            # minimal change that does the same job is easier to review and lower
            # risk. (Against the no-op baseline, best_size is 0, so a same-scoring
            # patch is correctly rejected in favor of changing nothing.)
            accepted = cand_key > best_key or (cand_key == best_key and cand_size < best_size)
            passed_tuning = all(
                c.passed for c in check_thresholds(thresholds, baseline_tuning, analysis.metrics)
            )
            experiment_log.append(
                AttemptRecord(
                    iteration=i,
                    kind=patch.kind,
                    rationale=patch.rationale,
                    files=sorted(patch.files),
                    primary=_primary(analysis.metrics),
                    schema_error_rate=analysis.metrics.schema_error_rate,
                    refusal_rate=analysis.metrics.refusal_rate,
                    passed_tuning=passed_tuning,
                    accepted=accepted,
                    diff_size=cand_size,
                    file_contents=_patch_file_contents(patch),
                )
            )
            if accepted:
                best_files = patch.files
                best_metrics = analysis.metrics
                best_analysis = analysis
                best_size = cand_size
                editable_contents.update(patch.files)
                improved = True

        # Did the current best clear tuning thresholds? (migrate only -- refine
        # runs the full budget and validates the winner once at the end.)
        if objective is Objective.MEET_THRESHOLDS and all(
            c.passed for c in check_thresholds(thresholds, baseline_tuning, best_metrics)
        ):
            ok, holdout_metrics, holdout_checks = holdout_ok(best_files or None)
            if ok:
                edited = commit_files(best_files, cwd=cwd) if best_files else []
                return MigrationResult(
                    workflow=workflow_name,
                    current_model=current,
                    target_model=target_model,
                    status=MigrationStatus.PASS,
                    iterations=iterations_run,
                    baseline=baseline_tuning,
                    naive_target=naive_tuning,
                    final=best_metrics,
                    holdout=holdout_metrics,
                    holdout_checks=holdout_checks,
                    tuning_checks=check_thresholds(thresholds, baseline_tuning, best_metrics),
                    remaining_clusters=cluster_failures(best_analysis.rows),
                    edited_files=edited,
                    experiment_log=experiment_log,
                    cluster_history=cluster_history,
                    warnings=size_warnings,
                    original_editable_files=original_editable,
                    message="migration passed tuning and holdout thresholds",
                )
        if improved:
            widened = False  # made progress; next round can go back to cheap width
        else:
            # Nothing better this round. Widen the search once before giving up
            # (multi-candidate generators only); otherwise stop early.
            if can_widen and not widened:
                widened = True
                continue
            break

    # MAXIMIZE (refine): budget spent. Validate the winner on the never-tuned
    # holdout, propose fresh thresholds from what it actually achieved, and commit
    # the improved prompt (the refined prompt *is* the deliverable here).
    if objective is Objective.MAXIMIZE:
        holdout_metrics: Metrics | None = None
        holdout_checks: list[ThresholdCheck] = []
        if mig.holdout_required and split.holdout_idx:
            progress_log("migration: holdout validation on refined prompt...")
            baseline_holdout = evaluate_on(current, split.holdout_idx).metrics
            holdout_metrics = evaluate_on(
                current, split.holdout_idx, files=best_files or None
            ).metrics
            # No absolute bar: report whether the refined prompt at least held the
            # line vs. the current prompt on data it never tuned against.
            holdout_checks = check_thresholds(
                ThresholdsSpec(), baseline_holdout, holdout_metrics
            )
        basis = holdout_metrics if holdout_metrics is not None else best_metrics
        suggested = suggest_thresholds(basis)

        improved = bool(best_files) and _maximize_key(best_metrics) > _maximize_key(naive_tuning)
        edited = commit_files(best_files, cwd=cwd) if (best_files and improved) else []
        status = MigrationStatus.PASS if improved else MigrationStatus.NO_CHANGE
        message = (
            "refined the prompt toward the updated dataset; validated on holdout"
            if improved
            else "no candidate beat the current prompt on the updated dataset; "
            "kept the current prompt"
        )
        return MigrationResult(
            workflow=workflow_name,
            current_model=current,
            target_model=target_model,
            status=status,
            iterations=iterations_run,
            baseline=baseline_tuning,
            naive_target=naive_tuning,
            final=best_metrics,
            holdout=holdout_metrics,
            holdout_checks=holdout_checks,
            tuning_checks=[],
            remaining_clusters=cluster_failures(best_analysis.rows),
            edited_files=edited,
            experiment_log=experiment_log,
            cluster_history=cluster_history,
            warnings=size_warnings,
            suggested_thresholds=suggested,
            original_editable_files=original_editable,
            message=message,
        )

    # No passing candidate. Did we at least improve over the naive swap?
    improved_overall = _primary(best_metrics) > _primary(naive_tuning) or (
        (best_metrics.schema_error_rate or 0) < (naive_tuning.schema_error_rate or 0)
    )
    status = MigrationStatus.PARTIAL if (best_files and improved_overall) else MigrationStatus.BLOCKED
    message = (
        "improved over naive swap but did not pass thresholds within max_iterations; "
        "changes were NOT committed"
        if status == MigrationStatus.PARTIAL
        else "could not recover acceptable quality on the target model"
    )
    return MigrationResult(
        workflow=workflow_name,
        current_model=current,
        target_model=target_model,
        status=status,
        iterations=iterations_run,
        baseline=baseline_tuning,
        naive_target=naive_tuning,
        final=best_metrics,
        tuning_checks=check_thresholds(thresholds, baseline_tuning, best_metrics),
        remaining_clusters=cluster_failures(best_analysis.rows),
        experiment_log=experiment_log,
        cluster_history=cluster_history,
        warnings=size_warnings,
        original_editable_files=original_editable,
        message=message,
    )
