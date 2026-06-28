"""Render migration results as evidence-rich markdown reports.

The markdown produced here doubles as the body of the migration PR (Milestone
6). Every outcome -- pass, model-change-only, partial, blocked -- produces a
useful artifact, because "useful but not guaranteed" means the failure path
must carry its weight too.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import asdict
from pathlib import Path

from .contract import Workflow
from .engine import AttemptRecord, MigrationResult, MigrationStatus, cluster_trajectories
from .evaluation import Metrics

_MAX_DIFF_LINES = 180
_MAX_ALTERNATE_ATTEMPTS = 2

_STATUS_HEADLINE = {
    MigrationStatus.PASS: "Migration passed configured thresholds.",
    MigrationStatus.MODEL_CHANGE_ONLY: "Naive model swap passes thresholds; only the model ID changes.",
    MigrationStatus.PARTIAL: "Migration improved results but did not meet thresholds on holdout. Changes were NOT committed.",
    MigrationStatus.BLOCKED: "Could not recover acceptable quality on the target model.",
    MigrationStatus.NO_CHANGE: "No candidate beat the current prompt on the updated dataset; the current prompt was kept.",
}

_RECOMMENDATION = {
    MigrationStatus.PASS: "Approve migration. Human review recommended before merge.",
    MigrationStatus.MODEL_CHANGE_ONLY: "Approve. Model ID change only; no behavioral repair was needed.",
    MigrationStatus.PARTIAL: "Do not merge as-is. Consider a different target model, relaxed thresholds, or manual repair using the remaining clusters below.",
    MigrationStatus.BLOCKED: "Do not migrate to this model yet. See remaining clusters and consider a fallback candidate.",
    MigrationStatus.NO_CHANGE: "No action needed. The current prompt is still the best on the updated dataset.",
}

# refine reframes the same result: model is pinned, the *dataset* changed.
_REFINE_HEADLINE = {
    MigrationStatus.PASS: "Refined the prompt for the updated dataset and validated it on holdout.",
    MigrationStatus.NO_CHANGE: "Current prompt is already the best on the updated dataset; no changes were made.",
}


def _is_refine(result: MigrationResult) -> bool:
    """Refine pins the model, so a same-model run is a dataset-change refinement."""
    return result.current_model == result.target_model


def _num(value: float | None, *, pct: bool = False, ndigits: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%" if pct else f"{value:.{ndigits}f}"


def _metric_rows(result: MigrationResult) -> list[tuple[str, bool]]:
    """(attr, is_pct) pairs to render, dropping rows that are entirely n/a."""
    candidates = [
        ("F1", "f1", False),
        ("Precision", "precision", False),
        ("Recall", "recall", False),
        ("Accuracy", "accuracy", False),
        ("Score / pass-rate", "score", False),
        ("Schema error rate", "schema_error_rate", True),
        ("Refusal rate", "refusal_rate", True),
        ("Avg latency (ms)", "avg_latency_ms", False),
        ("Total cost", "total_cost", False),
    ]
    rows = []
    for label, attr, pct in candidates:
        values = [
            getattr(result.baseline, attr),
            getattr(result.naive_target, attr),
            getattr(result.final, attr),
        ]
        if all(v is None for v in values):
            continue
        rows.append((label, attr, pct))
    return rows


def _metrics_table(result: MigrationResult) -> str:
    # In refine the model is pinned, so "Target (orig files)" == "Current"; show a
    # two-column current-vs-refined scorecard on the new dataset instead.
    if _is_refine(result):
        header = "| Metric | Current prompt | Refined prompt |\n"
        header += "|---|---:|---:|\n"
        lines = []
        for label, attr, pct in _metric_rows(result):
            nd = 0 if attr == "avg_latency_ms" else 3
            b = _num(getattr(result.baseline, attr), pct=pct, ndigits=nd)
            fn = _num(getattr(result.final, attr), pct=pct, ndigits=nd)
            lines.append(f"| {label} | {b} | {fn} |")
        return header + "\n".join(lines)

    header = "| Metric | Current | Target (orig files) | Target (migrated) |\n"
    header += "|---|---:|---:|---:|\n"
    lines = []
    for label, attr, pct in _metric_rows(result):
        nd = 0 if attr == "avg_latency_ms" else 3
        b = _num(getattr(result.baseline, attr), pct=pct, ndigits=nd)
        nv = _num(getattr(result.naive_target, attr), pct=pct, ndigits=nd)
        fn = _num(getattr(result.final, attr), pct=pct, ndigits=nd)
        lines.append(f"| {label} | {b} | {nv} | {fn} |")
    return header + "\n".join(lines)


def _per_field_section(result: MigrationResult) -> list[str]:
    """Extraction grading: per-field precision/recall/F1 of the final prompt."""
    pf = result.final.per_field
    if not pf:
        return []
    parts = [
        "## Per-field Extraction Metrics\n",
        "| Field | Precision | Recall | F1 | Support |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, m in pf.items():
        parts.append(
            f"| `{name}` | {m.precision:.3f} | {m.recall:.3f} | {m.f1:.3f} | {m.support} |"
        )
    parts.append("")
    return parts


def _primary_metric(metrics: Metrics | None) -> float | None:
    if metrics is None:
        return None
    if metrics.f1 is not None:
        return metrics.f1
    if metrics.score is not None:
        return metrics.score
    return metrics.accuracy


def _metric_name(metrics: Metrics | None) -> str:
    if metrics is None:
        return "score"
    if metrics.f1 is not None:
        return "F1"
    if metrics.score is not None:
        return "score"
    return "accuracy"


def _summary_section(result: MigrationResult) -> list[str]:
    """Executive summary for PR/issue reviewers."""
    metric = _metric_name(result.baseline)
    base = _primary_metric(result.baseline)
    final = _primary_metric(result.final)
    hold = _primary_metric(result.holdout) if result.holdout else None
    delta = (final - base) if base is not None and final is not None else None

    attempts = len(result.experiment_log)
    accepted = sum(1 for a in result.experiment_log if a.accepted)

    parts = ["## Summary\n"]
    parts.append(
        f"- **Status:** `{result.status.value}` · **Iterations:** {result.iterations} · "
        f"**Attempts:** {attempts} ({accepted} accepted)"
    )
    if base is not None and final is not None:
        delta_s = f"{delta:+.3f}" if delta is not None else "n/a"
        parts.append(f"- **Tuning {metric}:** {_num(base)} → {_num(final)} ({delta_s})")
    if hold is not None:
        parts.append(f"- **Holdout {metric}:** {_num(hold)}")
    if result.edited_files:
        files = ", ".join(f"`{f}`" for f in result.edited_files)
        parts.append(f"- **Files changed:** {files}")
    elif result.status == MigrationStatus.MODEL_CHANGE_ONLY:
        parts.append(f"- **Model:** `{result.current_model}` → `{result.target_model}` (config only)")
    parts.append("")
    return parts


def _unified_diff_text(path: str, original: str, proposed: str) -> str:
    lines = list(
        difflib.unified_diff(
            original.splitlines(),
            proposed.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
            n=3,
        )
    )
    if not lines:
        return "(no textual changes)\n"
    if len(lines) > _MAX_DIFF_LINES:
        kept = lines[:_MAX_DIFF_LINES]
        kept.append(f"... diff truncated ({len(lines) - _MAX_DIFF_LINES} more lines)")
        return "\n".join(kept) + "\n"
    return "\n".join(lines) + "\n"


def _diff_file_block(path: str, original: str, proposed: str) -> list[str]:
    changed = _patch_line_delta(original, proposed)
    summary = f"`{path}`"
    if changed is not None:
        summary += f" ({changed} changed line(s))"
    parts = [f"<details><summary>{summary}</summary>\n", "```diff"]
    parts.append(_unified_diff_text(path, original, proposed).rstrip())
    parts.append("```")
    parts.append("\n</details>\n")
    return parts


def _patch_line_delta(original: str, proposed: str) -> int | None:
    total = 0
    for line in difflib.unified_diff(
        original.splitlines(), proposed.splitlines(), lineterm="", n=0
    ):
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            total += 1
    return total


def _attempt_with_contents(attempt: AttemptRecord) -> bool:
    return bool(attempt.file_contents)


def _winning_attempt(result: MigrationResult) -> AttemptRecord | None:
    accepted = [a for a in result.experiment_log if a.accepted and _attempt_with_contents(a)]
    return accepted[-1] if accepted else None


def _best_scoring_attempt(result: MigrationResult) -> AttemptRecord | None:
    scored = [a for a in result.experiment_log if _attempt_with_contents(a) and not a.error]
    if not scored:
        return None
    return max(scored, key=lambda a: a.primary)


def _proposed_diffs_section(result: MigrationResult) -> list[str]:
    """Unified diffs for the committed patch (or best attempt when blocked)."""
    original = result.original_editable_files
    if not original:
        return []

    attempt = _winning_attempt(result)
    committed = bool(result.edited_files)
    if attempt is None and not committed:
        attempt = _best_scoring_attempt(result)
        if attempt is None:
            return []
        heading = "## Best Attempt (not committed)\n"
        intro = (
            "No patch was committed, but this candidate scored highest on the tuning "
            "split — useful context for a manual fix:\n"
        )
    else:
        if attempt is None:
            return []
        heading = "## Proposed Diffs\n"
        intro = "Unified diff vs. the pre-migration editable files:\n"

    parts = [heading, intro]
    for path in sorted(attempt.file_contents):
        if path not in original and path not in attempt.files:
            continue
        old = original.get(path, "")
        new = attempt.file_contents.get(path, old)
        if old == new:
            continue
        parts.extend(_diff_file_block(path, old, new))
    if len(parts) <= 2:
        return []
    return parts


def _alternates_section(result: MigrationResult) -> list[str]:
    """Top rejected candidates for auditability (collapsible)."""
    winner = _winning_attempt(result)
    rejected = [
        a
        for a in result.experiment_log
        if _attempt_with_contents(a) and not a.error and a is not winner
    ]
    if not rejected:
        return []
    rejected.sort(key=lambda a: a.primary, reverse=True)
    picked = rejected[:_MAX_ALTERNATE_ATTEMPTS]
    if not picked:
        return []

    parts = ["## Other Attempts Considered\n"]
    for idx, attempt in enumerate(picked, start=1):
        label = (
            f"Iter {attempt.iteration}, {metric_short(attempt.primary)} — "
            f"{attempt.rationale or attempt.kind}"
        )
        parts.append(f"<details><summary>{label}</summary>\n")
        parts.append(
            f"- Accepted: {'yes' if attempt.accepted else 'no'} · "
            f"Passed tuning: {'yes' if attempt.passed_tuning else 'no'} · "
            f"Diff ±: {attempt.diff_size if attempt.diff_size is not None else 'n/a'}"
        )
        for path in sorted(attempt.file_contents):
            old = result.original_editable_files.get(path, "")
            new = attempt.file_contents[path]
            if old != new:
                parts.extend(_diff_file_block(path, old, new))
        parts.append("</details>\n")
    return parts


def metric_short(value: float) -> str:
    return f"F1 {_num(value)}"


def _metric_progression_line(result: MigrationResult) -> str | None:
    """Best accepted primary metric after each iteration."""
    by_iter: dict[int, float] = {}
    for a in result.experiment_log:
        if a.accepted and not a.error:
            by_iter[a.iteration] = max(by_iter.get(a.iteration, a.primary), a.primary)
    if not by_iter:
        return None
    keys = sorted(by_iter)
    values = [_num(by_iter[k]) for k in keys]
    metric = _metric_name(result.baseline)
    return f"Best tuning {metric} by iteration: " + " → ".join(values)


def _run_data_footer(result: MigrationResult) -> list[str]:
    parts = ["## Full Run Data\n"]
    parts.append(
        f"- Machine-readable trace: `.driftless/migrations/{result.workflow}.json`"
    )
    parts.append(f"- Markdown report: `.driftless/reports/{result.workflow}.md`")
    parts.append(
        f"- Inspect locally: `driftless view -w {result.workflow}` or "
        f"`driftless report -w {result.workflow}`"
    )
    parts.append("")
    return parts


def _fallback_candidates(result: MigrationResult, workflow: Workflow | None) -> list[str]:
    if workflow is None:
        return []
    return [
        m
        for m in workflow.model.target_candidates
        if m not in (result.target_model, result.current_model)
    ]


def _trajectory_section(result: MigrationResult) -> list[str]:
    """Show how the optimizer searched: cluster trends + each attempt's score.

    This is the evidence a reviewer needs to trust an automated edit -- it makes
    the search auditable instead of a black box.
    """
    if not result.experiment_log and not result.cluster_history:
        return []

    parts: list[str] = ["## Optimization Trajectory\n"]

    progression = _metric_progression_line(result)
    if progression:
        parts.append(progression + "\n")

    traj = cluster_trajectories(result.cluster_history)
    if traj:
        parts.append("Failure clusters across iterations (count per iteration):\n")
        for key, counts in traj.items():
            arrow = " -> ".join(str(c) for c in counts)
            parts.append(f"- `{key}`: {arrow}")
        parts.append("")

    if result.experiment_log:
        parts.append("<details><summary>Attempts tried</summary>\n")
        parts.append("| Iter | Accepted | Passed | Primary | Schema err | Diff ± | Rationale |")
        parts.append("|---:|:--:|:--:|---:|---:|---:|---|")
        for a in result.experiment_log:
            acc = "yes" if a.accepted else "no"
            passed = "yes" if a.passed_tuning else "no"
            ser = _num(a.schema_error_rate, pct=True) if a.schema_error_rate is not None else "n/a"
            diff = f"{a.diff_size}" if a.diff_size is not None else "n/a"
            note = f"[error] {a.error}" if a.error else (a.rationale or "")
            rationale = note.replace("|", "\\|").replace("\n", " ")
            if len(rationale) > 120:
                rationale = rationale[:120] + "..."
            parts.append(
                f"| {a.iteration} | {acc} | {passed} | {a.primary:.3f} | {ser} | {diff} | {rationale} |"
            )
        parts.append("\n</details>")
        parts.append("")
    return parts


def _suggested_thresholds_section(result: MigrationResult) -> list[str]:
    """Emit a ready-to-paste ``thresholds:`` block derived from holdout metrics.

    On a changed dataset the old thresholds are stale; establishing the new
    baseline is the tool's job, but *setting the bar* stays the customer's call --
    so we propose, they accept/edit.
    """
    if not result.suggested_thresholds:
        return []
    parts = ["## Suggested Thresholds\n"]
    parts.append(
        "The previous dataset's thresholds are stale. These are derived from the "
        "refined prompt's holdout metrics (achieved minus a safety margin) -- "
        "review and paste into `driftless.yml`:\n"
    )
    parts.append("```yaml")
    parts.append("thresholds:")
    for key, value in result.suggested_thresholds.items():
        parts.append(f"  {key}: {value}")
    parts.append("```")
    parts.append("")
    return parts


def render_markdown(result: MigrationResult, workflow: Workflow | None = None) -> str:
    refine = _is_refine(result)
    parts: list[str] = []
    if refine:
        parts.append(f"# Prompt Refinement: `{result.workflow}`\n")
        parts.append(
            f"Re-optimizes `{result.workflow}` for the updated eval dataset "
            f"(model pinned to `{result.current_model}`).\n"
        )
    else:
        parts.append(f"# Model Migration: `{result.workflow}`\n")
        parts.append(
            f"Migrates `{result.workflow}` from `{result.current_model}` to "
            f"`{result.target_model}`.\n"
        )
    parts.append(f"**Status:** `{result.status.value}`  \n")
    parts.append(f"**Iterations:** {result.iterations}\n")

    parts.extend(_summary_section(result))

    parts.append("## Result\n")
    headline = (
        _REFINE_HEADLINE.get(result.status) if refine else _STATUS_HEADLINE.get(result.status)
    )
    parts.append((headline or result.message) + "\n")
    parts.append(_metrics_table(result) + "\n")

    parts.extend(_per_field_section(result))

    parts.extend(_suggested_thresholds_section(result))

    if result.warnings:
        parts.append("## Confidence Caveats\n")
        for w in result.warnings:
            parts.append(f"- {w}")
        parts.append("")

    parts.extend(_proposed_diffs_section(result))

    parts.append("## Changes Made\n")
    if result.edited_files:
        accepted = [a for a in result.experiment_log if a.accepted and a.diff_size is not None]
        committed_diff = accepted[-1].diff_size if accepted else None
        for f in result.edited_files:
            parts.append(f"- Edited `{f}`")
        if committed_diff is not None:
            parts.append(f"- Edit size: {committed_diff} changed line(s) vs. the original.")
        parts.append("- Output schema and read-only files were preserved.")
    elif result.status == MigrationStatus.MODEL_CHANGE_ONLY:
        parts.append("- Updated model ID only. No prompt/config changes were required.")
    elif result.status == MigrationStatus.NO_CHANGE:
        parts.append("- Kept the current prompt; no candidate improved on the updated dataset.")
    else:
        parts.append("- No changes were committed.")
    parts.append("")

    if result.holdout_checks:
        parts.append("## Holdout Validation\n")
        for c in result.holdout_checks:
            mark = "PASS" if c.passed else "FAIL"
            parts.append(f"- {mark} `{c.name}`: {c.detail}")
        parts.append("")

    if result.tuning_checks:
        failed = [c for c in result.tuning_checks if not c.passed]
        if failed:
            parts.append("## Unmet Thresholds\n")
            for c in failed:
                parts.append(f"- FAIL `{c.name}`: {c.detail}")
            parts.append("")

    parts.append("## Remaining Risks\n")
    if result.remaining_clusters:
        for cl in result.remaining_clusters:
            examples = ", ".join(str(i) for i in cl.example_indices)
            suffix = f" (e.g. indices {examples})" if examples else ""
            parts.append(f"- {cl.count} {cl.kind}: {cl.key}{suffix}")
    else:
        parts.append("- No residual failure clusters detected.")
    if result.succeeded:
        parts.append("- Human review recommended before merge.")
    parts.append("")

    parts.extend(_trajectory_section(result))

    parts.extend(_alternates_section(result))

    fallbacks = _fallback_candidates(result, workflow)
    if not result.succeeded and fallbacks:
        parts.append("## Suggested Fallback Candidates\n")
        for m in fallbacks:
            parts.append(f"- `{m}`")
        parts.append("")

    parts.append("## Recommendation\n")
    parts.append(_RECOMMENDATION.get(result.status, result.message))
    parts.append("")

    parts.extend(_run_data_footer(result))

    return "\n".join(parts)


def _metrics_dict(m: Metrics) -> dict:
    return asdict(m)


def result_to_dict(result: MigrationResult) -> dict:
    return {
        "workflow": result.workflow,
        "current_model": result.current_model,
        "target_model": result.target_model,
        "status": result.status.value,
        "iterations": result.iterations,
        "succeeded": result.succeeded,
        "baseline": _metrics_dict(result.baseline),
        "naive_target": _metrics_dict(result.naive_target),
        "final": _metrics_dict(result.final),
        "holdout": _metrics_dict(result.holdout) if result.holdout else None,
        "holdout_checks": [asdict(c) for c in result.holdout_checks],
        "tuning_checks": [asdict(c) for c in result.tuning_checks],
        "remaining_clusters": [asdict(c) for c in result.remaining_clusters],
        "edited_files": result.edited_files,
        "experiment_log": [asdict(a) for a in result.experiment_log],
        "cluster_trajectory": cluster_trajectories(result.cluster_history),
        "warnings": result.warnings,
        "suggested_thresholds": result.suggested_thresholds,
        "original_editable_files": result.original_editable_files,
        "message": result.message,
    }


def save_report(
    result: MigrationResult,
    *,
    workflow: Workflow | None = None,
    cwd: Path | None = None,
) -> tuple[Path, Path]:
    """Write the markdown report and the machine-readable JSON result."""
    cwd = (cwd or Path.cwd()).resolve()
    reports_dir = cwd / ".driftless" / "reports"
    migrations_dir = cwd / ".driftless" / "migrations"
    reports_dir.mkdir(parents=True, exist_ok=True)
    migrations_dir.mkdir(parents=True, exist_ok=True)

    md_path = reports_dir / f"{result.workflow}.md"
    json_path = migrations_dir / f"{result.workflow}.json"

    md_path.write_text(render_markdown(result, workflow), encoding="utf-8")
    json_path.write_text(json.dumps(result_to_dict(result), indent=2), encoding="utf-8")
    return md_path, json_path
