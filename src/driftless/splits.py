"""Tuning/holdout splitting and input materialization.

The migration loop tunes on one slice of the data and validates the winner on a
held-out slice it never optimized against. Because the customer's command reads
its inputs from ``run.input_path``, we evaluate "on a split" by temporarily
writing that split's input lines to ``run.input_path`` (backing up and
restoring the original), then running the workflow as usual.
"""

from __future__ import annotations

import json
import random
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .contract import Workflow
from .errors import DriftlessError
from .evaluation import load_labels, load_labels_by_id


@dataclass
class Split:
    input_lines: list[str]
    gold: list[Any] | None
    tuning_idx: list[int]
    holdout_idx: list[int]
    # Per-input id, aligned to ``input_lines`` (only when eval.id_field is set).
    gold_ids: list[Any] | None = None

    def lines_for(self, idx: list[int]) -> list[str]:
        return [self.input_lines[i] for i in idx]

    def gold_for(self, idx: list[int]) -> list[Any] | None:
        if self.gold is None:
            return None
        return [self.gold[i] for i in idx]

    def gold_by_id_for(self, idx: list[int]) -> dict[Any, Any] | None:
        """The id->label map restricted to a split subset (for id alignment)."""
        if self.gold is None or self.gold_ids is None:
            return None
        return {self.gold_ids[i]: self.gold[i] for i in idx}


def _read_nonempty_lines(path: Path) -> list[str]:
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            lines.append(line)
    return lines


def make_splits(
    workflow: Workflow, *, cwd: Path | None = None, seed: int = 0
) -> Split:
    cwd = (cwd or Path.cwd()).resolve()
    input_path = (cwd / workflow.run.input_path).resolve()
    if not input_path.is_file():
        raise DriftlessError(f"input dataset not found: {workflow.run.input_path}")

    input_lines = _read_nonempty_lines(input_path)
    n = len(input_lines)
    if n < 2:
        raise DriftlessError(
            "need at least 2 examples to form a tuning/holdout split",
            hint="add more rows to run.input_path",
        )

    gold: list[Any] | None = None
    gold_ids: list[Any] | None = None
    if workflow.eval.labels_path:
        labels_path = (cwd / workflow.eval.labels_path).resolve()
        if not labels_path.is_file():
            raise DriftlessError(
                f"labels file not found: {workflow.eval.labels_path}"
            )
        if workflow.eval.id_field:
            gold, gold_ids = _gold_by_input_id(
                input_lines, labels_path, workflow.eval.id_field, workflow.eval.label_field
            )
        else:
            gold = load_labels(labels_path, workflow.eval.label_field)
            if len(gold) != n:
                raise DriftlessError(
                    f"label count ({len(gold)}) != input count ({n})"
                )

    indices = list(range(n))
    random.Random(seed).shuffle(indices)

    tuning_frac = workflow.eval.split.tuning
    tuning_count = max(1, min(n - 1, round(n * tuning_frac)))
    tuning_idx = sorted(indices[:tuning_count])
    holdout_idx = sorted(indices[tuning_count:])

    return Split(input_lines, gold, tuning_idx, holdout_idx, gold_ids=gold_ids)


def _gold_by_input_id(
    input_lines: list[str], labels_path: Path, id_field: str, label_field: str
) -> tuple[list[Any], list[Any]]:
    """Align gold to inputs by id (not position) when ``eval.id_field`` is set."""
    id_to_label = load_labels_by_id(labels_path, id_field, label_field)
    gold: list[Any] = []
    gold_ids: list[Any] = []
    for line_no, line in enumerate(input_lines, start=1):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DriftlessError(
                f"input line {line_no} is not valid JSON",
                hint=f"id-based alignment needs JSON inputs carrying '{id_field}'",
            ) from exc
        if not isinstance(obj, dict) or id_field not in obj:
            raise DriftlessError(
                f"input line {line_no} is missing id field '{id_field}'",
                hint="every input record must carry the configured eval.id_field",
            )
        iid = obj[id_field]
        if iid not in id_to_label:
            raise DriftlessError(
                f"input id {iid!r} has no matching label",
                hint="inputs and labels are aligned by eval.id_field",
            )
        gold.append(id_to_label[iid])
        gold_ids.append(iid)
    return gold, gold_ids


@contextmanager
def materialize_inputs(workflow: Workflow, lines: list[str], *, cwd: Path | None = None) -> Iterator[None]:
    """Temporarily write ``lines`` to ``run.input_path``; restore on exit."""
    cwd = (cwd or Path.cwd()).resolve()
    input_path = (cwd / workflow.run.input_path).resolve()
    original = input_path.read_bytes()
    try:
        input_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        yield
    finally:
        input_path.write_bytes(original)
