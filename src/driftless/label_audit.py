"""Pre-flight label quality checks (P6.1).

Surfaces duplicate (and near-duplicate) inputs with disagreeing gold labels —
a common silent ceiling on achievable accuracy during ``refine`` / ``migrate``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .contract import Workflow
from .errors import DriftlessError
from .evaluation import load_labels, load_labels_by_id

_TEXT_KEYS = ("text", "input", "ticket", "message", "query", "prompt", "content")


@dataclass(frozen=True)
class LabeledInput:
    record_id: Any | None
    line_no: int
    text: str
    label: Any
    norm: str


@dataclass
class LabelConflictGroup:
    kind: str  # exact_duplicate | near_duplicate
    labels: list[Any]
    count: int
    examples: list[tuple[Any | None, Any, str]]  # (id, label, text snippet)
    similarity: float | None = None


@dataclass
class LabelAuditReport:
    workflow: str
    n_records: int
    exact_conflicts: list[LabelConflictGroup] = field(default_factory=list)
    near_conflicts: list[LabelConflictGroup] = field(default_factory=list)
    missing_label_ids: list[Any] = field(default_factory=list)
    missing_input_ids: list[Any] = field(default_factory=list)

    @property
    def conflict_groups(self) -> list[LabelConflictGroup]:
        return self.exact_conflicts + self.near_conflicts

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflict_groups)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _token_jaccard(a: str, b: str) -> float:
    ta = set(_normalize_text(a).split())
    tb = set(_normalize_text(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _input_text(obj: dict[str, Any]) -> str:
    for key in _TEXT_KEYS:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return json.dumps(obj, sort_keys=True)


def _snippet(text: str, limit: int = 96) -> str:
    one_line = re.sub(r"\s+", " ", text.strip())
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 3] + "..."


def _load_labeled_inputs(workflow: Workflow, *, cwd: Path) -> list[LabeledInput]:
    spec = workflow.eval
    if spec.grading != "label":
        raise DriftlessError(
            f"label audit applies to classification workflows (eval.label_field), "
            f"not {spec.grading!r} grading",
        )
    if not spec.labels_path:
        raise DriftlessError(
            "eval.labels_path is required for label audit",
            hint="add a gold labels JSONL file to the workflow contract",
        )

    input_path = (cwd / workflow.run.input_path).resolve()
    labels_path = (cwd / spec.labels_path).resolve()
    if not input_path.is_file():
        raise DriftlessError(f"input file not found: {workflow.run.input_path}")
    if not labels_path.is_file():
        raise DriftlessError(f"labels file not found: {spec.labels_path}")

    input_lines = [
        line.strip()
        for line in input_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    if spec.id_field:
        id_to_label = load_labels_by_id(labels_path, spec.id_field, spec.label_field)
        rows: list[LabeledInput] = []
        for line_no, line in enumerate(input_lines, start=1):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DriftlessError(f"input line {line_no} is not valid JSON") from exc
            if not isinstance(obj, dict) or spec.id_field not in obj:
                raise DriftlessError(
                    f"input line {line_no} is missing id field {spec.id_field!r}"
                )
            rid = obj[spec.id_field]
            if rid not in id_to_label:
                raise DriftlessError(f"input id {rid!r} has no matching label")
            text = _input_text(obj)
            rows.append(
                LabeledInput(
                    record_id=rid,
                    line_no=line_no,
                    text=text,
                    label=id_to_label[rid],
                    norm=_normalize_text(text),
                )
            )
        return rows

    gold = load_labels(labels_path, spec.label_field)
    if len(gold) != len(input_lines):
        raise DriftlessError(
            f"input/label count mismatch: {len(input_lines)} inputs vs {len(gold)} labels",
            hint="set eval.id_field for id-based alignment when counts differ",
        )
    rows = []
    for line_no, (line, label) in enumerate(zip(input_lines, gold), start=1):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            obj = {"text": line}
        if not isinstance(obj, dict):
            obj = {"text": str(obj)}
        text = _input_text(obj)
        rows.append(
            LabeledInput(
                record_id=None,
                line_no=line_no,
                text=text,
                label=label,
                norm=_normalize_text(text),
            )
        )
    return rows


def _group_exact_duplicates(rows: list[LabeledInput]) -> list[LabelConflictGroup]:
    by_norm: dict[str, list[LabeledInput]] = {}
    for row in rows:
        by_norm.setdefault(row.norm, []).append(row)

    groups: list[LabelConflictGroup] = []
    for norm, members in sorted(by_norm.items(), key=lambda kv: -len(kv[1])):
        labels = sorted({m.label for m in members}, key=lambda x: str(x))
        if len(labels) <= 1:
            continue
        examples = [
            (m.record_id if m.record_id is not None else m.line_no, m.label, _snippet(m.text))
            for m in members[:4]
        ]
        groups.append(
            LabelConflictGroup(
                kind="exact_duplicate",
                labels=labels,
                count=len(members),
                examples=examples,
            )
        )
    return groups


def _group_near_duplicates(
    rows: list[LabeledInput], *, threshold: float
) -> list[LabelConflictGroup]:
    groups: list[LabelConflictGroup] = []
    seen_pairs: set[tuple[int, int]] = set()
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if rows[i].norm == rows[j].norm:
                continue
            sim = _token_jaccard(rows[i].text, rows[j].text)
            if sim < threshold:
                continue
            if rows[i].label == rows[j].label:
                continue
            key = (i, j)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            examples = [
                (
                    rows[i].record_id if rows[i].record_id is not None else rows[i].line_no,
                    rows[i].label,
                    _snippet(rows[i].text),
                ),
                (
                    rows[j].record_id if rows[j].record_id is not None else rows[j].line_no,
                    rows[j].label,
                    _snippet(rows[j].text),
                ),
            ]
            groups.append(
                LabelConflictGroup(
                    kind="near_duplicate",
                    labels=sorted({rows[i].label, rows[j].label}, key=str),
                    count=2,
                    examples=examples,
                    similarity=sim,
                )
            )
    groups.sort(key=lambda g: (-(g.similarity or 0.0), -g.count))
    return groups


def audit_labels(
    workflow_name: str,
    workflow: Workflow,
    *,
    cwd: Path | None = None,
    near_threshold: float = 0.85,
    max_near_groups: int = 20,
) -> LabelAuditReport:
    """Find duplicate/near-duplicate inputs with disagreeing gold labels."""
    cwd = (cwd or Path.cwd()).resolve()
    rows = _load_labeled_inputs(workflow, cwd=cwd)
    exact = _group_exact_duplicates(rows)
    near = _group_near_duplicates(rows, threshold=near_threshold)[:max_near_groups]
    return LabelAuditReport(
        workflow=workflow_name,
        n_records=len(rows),
        exact_conflicts=exact,
        near_conflicts=near,
    )


def format_audit_report(report: LabelAuditReport) -> str:
    lines = [
        f"Label audit: `{report.workflow}` ({report.n_records} labeled records)",
        "",
    ]
    if not report.has_conflicts:
        lines.append("No duplicate or near-duplicate inputs with disagreeing labels.")
        return "\n".join(lines)

    if report.exact_conflicts:
        lines.append(
            f"Exact duplicates with label disagreement ({len(report.exact_conflicts)} group(s)):"
        )
        for group in report.exact_conflicts:
            labels = ", ".join(repr(x) for x in group.labels)
            lines.append(f"  - {group.count} rows, labels: {labels}")
            for rid, label, text in group.examples[:2]:
                lines.append(f"      id={rid!r} label={label!r}: {text}")
        lines.append("")

    if report.near_conflicts:
        lines.append(
            f"Near-duplicates with label disagreement ({len(report.near_conflicts)} pair(s)):"
        )
        for group in report.near_conflicts:
            sim = f"{group.similarity:.2f}" if group.similarity is not None else "?"
            labels = ", ".join(repr(x) for x in group.labels)
            lines.append(f"  - similarity={sim}, labels: {labels}")
            for rid, label, text in group.examples:
                lines.append(f"      id={rid!r} label={label!r}: {text}")
        lines.append("")

    lines.append(
        "These disagreements cap achievable accuracy — fix labels or dedupe inputs "
        "before expecting ``refine`` / ``migrate`` to converge."
    )
    return "\n".join(lines)
