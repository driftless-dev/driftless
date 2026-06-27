"""Render migration results as evidence-rich markdown reports.

The markdown produced here doubles as the body of the migration PR (Milestone
6). Every outcome -- pass, model-change-only, partial, blocked -- produces a
useful artifact, because "useful but not guaranteed" means the failure path
must carry its weight too.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .contract import Workflow
from .engine import MigrationResult, MigrationStatus, cluster_trajectories
from .evaluation import Metrics

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

    fallbacks = _fallback_candidates(result, workflow)
    if not result.succeeded and fallbacks:
        parts.append("## Suggested Fallback Candidates\n")
        for m in fallbacks:
            parts.append(f"- `{m}`")
        parts.append("")

    parts.append("## Recommendation\n")
    parts.append(_RECOMMENDATION.get(result.status, result.message))
    parts.append("")

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
