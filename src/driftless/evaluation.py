"""Turn raw workflow outputs into a scorecard.

This module loads the production-shaped outputs a workflow wrote to disk,
aligns them with gold labels, validates them against the output schema, and
computes the metrics the migration thresholds are expressed in
(accuracy / precision / recall / F1 / schema-error rate / refusal rate /
latency / cost).

Design notes:
* Outputs are JSONL, one record per input line.
* A line that is not valid JSON, or that fails schema validation, counts as a
  schema error (the model produced an unusable output).
* Cost is best-effort: we only report it when the workflow emits a per-record
  cost field. We never fabricate token-based estimates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .contract import EvalSpec, Workflow
from .errors import DriftlessError
from .harness import RunResult


@dataclass
class OutputRecord:
    line_no: int
    raw: str
    parsed: dict[str, Any] | None
    parse_ok: bool
    schema_ok: bool | None = None  # None when no schema configured


@dataclass
class RecordRow:
    """Per-record analysis used for metrics and failure clustering."""

    index: int
    parse_ok: bool
    schema_ok: bool | None
    predicted: Any
    gold: Any
    is_refusal: bool
    is_schema_error: bool
    is_correct: bool | None  # None when no labels are available
    # Real data, surfaced to the optimizer so it can see *why* rows fail.
    raw: str | None = None  # the raw output line the workflow wrote
    input_text: str | None = None  # the input line that produced this output
    # Customer-supplied grading (score/pass mode): the per-record grade, and
    # whether it scored below the run mean (the score-mode "failure" signal).
    score: float | None = None
    is_low_score: bool = False
    # Extraction mode: the configured fields whose extracted value != gold.
    field_errors: list[str] = field(default_factory=list)
    # Judge mode: the judge's rationale for this record's score (evidence).
    rationale: str | None = None


@dataclass
class RunAnalysis:
    metrics: "Metrics"
    rows: list[RecordRow] = field(default_factory=list)


@dataclass
class ClassMetrics:
    support: int
    precision: float
    recall: float
    f1: float


@dataclass
class Metrics:
    n: int
    schema_error_rate: float | None
    refusal_rate: float
    accuracy: float | None = None
    precision: float | None = None  # macro
    recall: float | None = None  # macro
    f1: float | None = None  # macro
    avg_latency_ms: float | None = None
    total_cost: float | None = None
    # Customer-supplied grading: mean numeric score, or pass-rate (0..1).
    score: float | None = None
    per_class: dict[str, ClassMetrics] = field(default_factory=dict)
    # Extraction grading: per-field precision/recall/F1 (slot filling).
    per_field: dict[str, ClassMetrics] = field(default_factory=dict)
    schema_errors: int = 0
    refusals: int = 0
    labeled: int = 0
    scored: int = 0


def load_jsonl(path: Path) -> list[OutputRecord]:
    records: list[OutputRecord] = []
    with path.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
                if not isinstance(parsed, dict):
                    parsed, parse_ok = None, False
                else:
                    parse_ok = True
            except json.JSONDecodeError:
                parsed, parse_ok = None, False
            records.append(OutputRecord(i, stripped, parsed, parse_ok))
    return records


def _load_raw(path: Path) -> list[OutputRecord]:
    """Load outputs for judge mode: keep the raw line; parse JSON when possible.

    Free-form outputs may be plain text, so a non-JSON line is fine here (the
    judge scores the text). When a line *is* a JSON object we still parse it, so
    ``judge.output_field`` can pull a field out of structured output.
    """
    records: list[OutputRecord] = []
    with path.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
                if not isinstance(parsed, dict):
                    parsed = None
            except json.JSONDecodeError:
                parsed = None
            records.append(OutputRecord(i, stripped, parsed, parse_ok=parsed is not None))
    return records


def load_labels(path: Path, label_field: str) -> list[Any]:
    """Load gold labels. Each line may be a bare scalar or a ``{label_field: ...}``."""
    labels: list[Any] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError:
                value = stripped  # treat as a plain string label
            if isinstance(value, dict):
                value = value.get(label_field)
            labels.append(value)
    return labels


def load_labels_by_id(
    path: Path, id_field: str, label_field: str
) -> dict[Any, Any]:
    """Load gold labels keyed by ``id_field`` for id-based alignment.

    Every line must be a JSON object carrying ``id_field``; the value is taken
    from ``label_field``. Duplicate ids are rejected so a typo can't silently
    shadow a real label.
    """
    mapping: dict[Any, Any] = {}
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise DriftlessError(
                    f"labels line {line_no} is not valid JSON",
                    hint=f"id-based alignment needs JSON objects with an '{id_field}' field",
                ) from exc
            if not isinstance(value, dict) or id_field not in value:
                raise DriftlessError(
                    f"labels line {line_no} is missing id field '{id_field}'",
                    hint="every label record must carry the configured eval.id_field",
                )
            key = value[id_field]
            if key in mapping:
                raise DriftlessError(f"duplicate label id: {key!r}")
            mapping[key] = value.get(label_field)
    return mapping


def load_gold_records_by_id(path: Path, id_field: str) -> dict[Any, dict]:
    """Load *full* gold records keyed by id (for extraction's per-field scoring).

    Unlike :func:`load_labels_by_id` (which extracts one label field), extraction
    needs every gold field, so we keep the whole object.
    """
    mapping: dict[Any, dict] = {}
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise DriftlessError(
                    f"labels line {line_no} is not valid JSON",
                    hint="extraction grading needs JSON gold objects with the scored fields",
                ) from exc
            if not isinstance(value, dict) or id_field not in value:
                raise DriftlessError(
                    f"labels line {line_no} is missing id field '{id_field}'",
                    hint="every gold record must carry the configured eval.id_field",
                )
            key = value[id_field]
            if key in mapping:
                raise DriftlessError(f"duplicate label id: {key!r}")
            mapping[key] = value
    return mapping


def _derive_cost_from_tokens(
    records: list[OutputRecord], model: str, spec: EvalSpec
) -> float | None:
    """Sum per-record cost from token usage x the catalog price for ``model``.

    Returns ``None`` when the model has no known pricing or no record carried
    usable token counts -- we never fabricate a cost estimate.
    """
    from .lifecycle import load_lifecycle

    pricing = load_lifecycle().pricing_for(model)
    if pricing is None:
        return None

    total = 0.0
    saw_tokens = False
    for r in records:
        if not r.parsed:
            continue
        pt = r.parsed.get(spec.prompt_tokens_field)
        ct = r.parsed.get(spec.completion_tokens_field)
        if isinstance(pt, (int, float)) and isinstance(ct, (int, float)):
            total += pricing.cost_for(pt, ct)
            saw_tokens = True
    return total if saw_tokens else None


def _validate_schema(records: list[OutputRecord], schema_path: Path) -> None:
    import jsonschema

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for rec in records:
        if not rec.parse_ok or rec.parsed is None:
            rec.schema_ok = False
            continue
        rec.schema_ok = next(validator.iter_errors(rec.parsed), None) is None


def _is_refusal(rec: OutputRecord, spec: EvalSpec, grading: str = "label") -> bool:
    if not rec.parse_ok or rec.parsed is None:
        return False  # unparseable counts as a schema error, not a refusal
    if rec.parsed.get("refused") in (True, "true", "True"):
        return True
    # The "empty label == refusal" rule only makes sense for label-based grading;
    # in score/pass mode the workflow may not emit a label at all.
    if grading != "label":
        return False
    value = rec.parsed.get(spec.label_field)
    if value in (None, ""):
        return True
    if spec.refusal_values and value in spec.refusal_values:
        return True
    return False


def _predicted_label(rec: OutputRecord, spec: EvalSpec) -> Any:
    if not rec.parse_ok or rec.parsed is None:
        return None
    return rec.parsed.get(spec.label_field)


def _record_grade(rec: OutputRecord, spec: EvalSpec, grading: str) -> float | None:
    """The per-record grade in score/pass mode: numeric score, or pass -> 1/0."""
    if rec.parsed is None:
        return None
    if grading == "score":
        v = rec.parsed.get(spec.score_field)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    # pass mode
    v = rec.parsed.get(spec.pass_field)
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if v in ("true", "True", 1):
        return 1.0
    if v in ("false", "False", 0):
        return 0.0
    return None


def _macro_prf(
    pairs: list[tuple[Any, Any]],
) -> tuple[float, float, float, float, dict[str, ClassMetrics]]:
    """Compute accuracy and macro precision/recall/F1 from (gold, pred) pairs."""
    classes = {g for g, _ in pairs} | {p for _, p in pairs if p is not None}
    per_class: dict[str, ClassMetrics] = {}
    precisions, recalls, f1s = [], [], []
    correct = sum(1 for g, p in pairs if g == p)
    accuracy = correct / len(pairs) if pairs else 0.0

    for cls in sorted(classes, key=str):
        tp = sum(1 for g, p in pairs if p == cls and g == cls)
        fp = sum(1 for g, p in pairs if p == cls and g != cls)
        fn = sum(1 for g, p in pairs if g == cls and p != cls)
        support = sum(1 for g, _ in pairs if g == cls)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_class[str(cls)] = ClassMetrics(support, precision, recall, f1)
        # Macro average over classes present in the gold labels.
        if support:
            precisions.append(precision)
            recalls.append(recall)
            f1s.append(f1)

    macro_p = sum(precisions) / len(precisions) if precisions else 0.0
    macro_r = sum(recalls) / len(recalls) if recalls else 0.0
    macro_f1 = sum(f1s) / len(f1s) if f1s else 0.0
    return accuracy, macro_p, macro_r, macro_f1, per_class


def _resolve_gold(
    workflow: Workflow, n: int, gold_labels: list[Any] | None, cwd: Path
) -> list[Any] | None:
    """Use an explicit gold override (e.g. a split subset) or load from disk."""
    spec = workflow.eval
    if gold_labels is not None:
        gold = gold_labels
    elif spec.labels_path:
        labels_path = (cwd / spec.labels_path).resolve()
        if not labels_path.is_file():
            raise DriftlessError(f"labels file not found: {spec.labels_path}")
        gold = load_labels(labels_path, spec.label_field)
    else:
        return None
    if len(gold) != n:
        raise DriftlessError(
            f"label count ({len(gold)}) != output count ({n})",
            hint="outputs and labels are aligned by line; counts must match",
        )
    return gold


def _resolve_gold_by_id(
    workflow: Workflow, gold_by_id: dict[Any, Any] | None, cwd: Path
) -> dict[Any, Any] | None:
    """Use an explicit id->label override (a split subset) or load from disk."""
    spec = workflow.eval
    if gold_by_id is not None:
        return gold_by_id
    if spec.labels_path:
        labels_path = (cwd / spec.labels_path).resolve()
        if not labels_path.is_file():
            raise DriftlessError(f"labels file not found: {spec.labels_path}")
        return load_labels_by_id(labels_path, spec.id_field, spec.label_field)  # type: ignore[arg-type]
    return None


def _validate_id_coverage(
    records: list[OutputRecord], gold_map: dict[Any, Any], spec: EvalSpec
) -> None:
    """Guard against the silent-misalignment foot-guns id matching is meant to fix."""
    id_field = spec.id_field
    out_ids = [
        rec.parsed[id_field]
        for rec in records
        if rec.parsed is not None and id_field in rec.parsed
    ]

    seen: set[Any] = set()
    dups: set[Any] = set()
    for oid in out_ids:
        if oid in seen:
            dups.add(oid)
        seen.add(oid)
    if dups:
        raise DriftlessError(
            f"duplicate output id(s): {sorted(map(str, dups))[:5]}",
            hint="each input id must produce exactly one output record",
        )

    unknown = [oid for oid in out_ids if oid not in gold_map]
    if unknown:
        raise DriftlessError(
            f"output id(s) not found in labels: {sorted(map(str, unknown))[:5]}",
            hint=f"outputs are aligned to labels by eval.id_field ('{id_field}')",
        )

    if len(records) != len(gold_map):
        raise DriftlessError(
            f"output count ({len(records)}) != label count ({len(gold_map)})",
            hint="every labeled id must have exactly one output record",
        )


def _index_inputs(
    inputs: list[str] | None, spec: EvalSpec
) -> tuple[dict[Any, str] | None, list[str] | None]:
    """Prepare an input lookup: by id when configured, else positional."""
    if inputs is None:
        return None, None
    if spec.id_field:
        by_id: dict[Any, str] = {}
        for line in inputs:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and spec.id_field in obj:
                by_id[obj[spec.id_field]] = line
        return by_id, None
    return None, list(inputs)


def _present(value: Any) -> bool:
    """A field counts as 'extracted'/'expected' when it's not null/empty."""
    return value not in (None, "")


def _resolve_gold_records(spec: EvalSpec, cwd: Path) -> dict[Any, dict]:
    labels_path = (cwd / spec.labels_path).resolve()  # type: ignore[arg-type]
    if not labels_path.is_file():
        raise DriftlessError(f"labels file not found: {spec.labels_path}")
    return load_gold_records_by_id(labels_path, spec.id_field)  # type: ignore[arg-type]


def _analyze_extraction(
    workflow: Workflow,
    records: list[OutputRecord],
    metrics: "Metrics",
    input_for,
    cwd: Path,
) -> RunAnalysis:
    """Per-field precision/recall/F1 over structured output (slot filling).

    Each configured field is scored independently against the gold record:
    precision = correct / extracted, recall = correct / expected. Macro averages
    populate ``metrics.f1/precision/recall`` so extraction reuses the same
    ``min_f1`` thresholds and ``_primary`` as classification.
    """
    spec = workflow.eval
    fields = spec.fields
    gold_map = _resolve_gold_records(spec, cwd)

    # Guard against silent misalignment: any parseable output id must be known.
    unknown = [
        rec.parsed[spec.id_field]
        for rec in records
        if rec.parsed is not None
        and spec.id_field in rec.parsed
        and rec.parsed[spec.id_field] not in gold_map
    ]
    if unknown:
        raise DriftlessError(
            f"output id(s) not found in labels: {sorted(map(str, unknown))[:5]}",
            hint=f"extraction aligns outputs to gold by eval.id_field ('{spec.id_field}')",
        )

    counts = {f: {"pred": 0, "gold": 0, "correct": 0} for f in fields}
    rows: list[RecordRow] = []
    matched_n = 0
    for i, rec in enumerate(records):
        rec_id = rec.parsed.get(spec.id_field) if rec.parsed else None
        gold = gold_map.get(rec_id)
        matched = gold is not None
        if matched:
            matched_n += 1
        field_errors: list[str] = []
        for f in fields:
            pred_v = rec.parsed.get(f) if rec.parsed else None
            gold_v = gold.get(f) if gold else None
            pred_present = _present(pred_v)
            gold_present = _present(gold_v)
            correct = gold_present and pred_v == gold_v
            c = counts[f]
            if pred_present:
                c["pred"] += 1
            if gold_present:
                c["gold"] += 1
            if correct:
                c["correct"] += 1
            if matched and (pred_present or gold_present) and pred_v != gold_v:
                field_errors.append(f)
        rows.append(
            RecordRow(
                index=i,
                parse_ok=rec.parse_ok,
                schema_ok=rec.schema_ok,
                predicted=None,
                gold=None,
                is_refusal=False,
                is_schema_error=rec.schema_ok is False,
                is_correct=(not field_errors) if matched else None,
                raw=rec.raw,
                input_text=input_for(i, rec),
                field_errors=field_errors,
            )
        )

    per_field: dict[str, ClassMetrics] = {}
    ps, rs, fs = [], [], []
    for f in fields:
        c = counts[f]
        p = c["correct"] / c["pred"] if c["pred"] else 0.0
        r = c["correct"] / c["gold"] if c["gold"] else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) else 0.0
        per_field[f] = ClassMetrics(support=c["gold"], precision=p, recall=r, f1=f1)
        ps.append(p)
        rs.append(r)
        fs.append(f1)
    if fields:
        metrics.precision = sum(ps) / len(ps)
        metrics.recall = sum(rs) / len(rs)
        metrics.f1 = sum(fs) / len(fs)
    metrics.per_field = per_field
    metrics.labeled = matched_n
    exact = sum(1 for row in rows if row.is_correct is True)
    metrics.accuracy = (exact / matched_n) if matched_n else None
    return RunAnalysis(metrics=metrics, rows=rows)


def _analyze_judge(
    spec: EvalSpec,
    records: list[OutputRecord],
    metrics: "Metrics",
    judge: Any | None,
    input_for,
) -> RunAnalysis:
    """Score each record with an LLM judge; aggregate the mean as ``score``."""
    if judge is None:
        raise DriftlessError(
            "judge grading requires a judge instance",
            hint="internal: build_judge() should have been called before analyze()",
        )
    jspec = spec.judge
    rows: list[RecordRow] = []
    scores: list[float] = []
    for i, rec in enumerate(records):
        input_text = input_for(i, rec)
        if jspec.output_field and rec.parsed is not None:
            ov = rec.parsed.get(jspec.output_field)
            output_text = ov if isinstance(ov, str) else json.dumps(ov)
        else:
            output_text = rec.raw
        judge_input = input_text
        if jspec.input_field and input_text:
            try:
                obj = json.loads(input_text)
            except json.JSONDecodeError:
                obj = None
            if isinstance(obj, dict) and jspec.input_field in obj:
                iv = obj[jspec.input_field]
                judge_input = iv if isinstance(iv, str) else json.dumps(iv)

        result = judge.score(input_text=judge_input, output_text=output_text)
        scores.append(result.score)
        is_correct = (
            (result.score >= jspec.pass_threshold)
            if jspec.pass_threshold is not None
            else None
        )
        rows.append(
            RecordRow(
                index=i,
                parse_ok=rec.parse_ok,
                schema_ok=rec.schema_ok,
                predicted=round(result.score, 4),
                gold=None,
                is_refusal=False,
                is_schema_error=rec.schema_ok is False,
                is_correct=is_correct,
                raw=rec.raw,
                input_text=input_text,
                score=result.score,
                rationale=result.rationale,
            )
        )
    mean = sum(scores) / len(scores) if scores else None
    for row in rows:
        row.is_low_score = (
            row.score is not None and mean is not None and row.score < mean
        )
    if scores:
        metrics.score = mean
        metrics.scored = len(scores)
    return RunAnalysis(metrics=metrics, rows=rows)


def analyze(
    workflow: Workflow,
    run: RunResult,
    *,
    gold_labels: list[Any] | None = None,
    gold_by_id: dict[Any, Any] | None = None,
    inputs: list[str] | None = None,
    judge: Any | None = None,
    cwd: Path | None = None,
) -> RunAnalysis:
    """Evaluate a run into metrics plus per-record rows (for clustering)."""
    cwd = (cwd or Path.cwd()).resolve()
    spec = workflow.eval
    grading = spec.grading

    # Judge mode loads raw output as JSONL too, but free-form outputs need not be
    # JSON objects -- judging happens on the raw text, so don't penalize parsing.
    records = load_jsonl(run.output_path) if grading != "judge" else _load_raw(run.output_path)
    n = len(records)
    if n == 0:
        raise DriftlessError(
            "workflow produced no output records",
            hint="ensure the command writes one record per input line",
        )

    if spec.schema_path:
        schema_path = (cwd / spec.schema_path).resolve()
        if not schema_path.is_file():
            raise DriftlessError(f"schema file not found: {spec.schema_path}")
        _validate_schema(records, schema_path)
        schema_errors = sum(1 for r in records if r.schema_ok is False)
    elif grading == "judge":
        # Free-form outputs (text, prose) are not schema-checked.
        for r in records:
            r.schema_ok = True
        schema_errors = 0
    else:
        # Without a schema, an unparseable line is still an error.
        for r in records:
            r.schema_ok = r.parse_ok
        schema_errors = sum(1 for r in records if not r.parse_ok)
    schema_error_rate = schema_errors / n

    refusals = sum(1 for r in records if _is_refusal(r, spec, grading))
    refusal_rate = refusals / n

    metrics = Metrics(
        n=n,
        schema_error_rate=schema_error_rate,
        refusal_rate=refusal_rate,
        schema_errors=schema_errors,
        refusals=refusals,
        avg_latency_ms=(run.duration_seconds * 1000.0 / n) if n else None,
    )

    if spec.cost_field:
        costs = [
            r.parsed.get(spec.cost_field)
            for r in records
            if r.parsed and isinstance(r.parsed.get(spec.cost_field), (int, float))
        ]
        metrics.total_cost = float(sum(costs)) if costs else None

    # Fallback: derive cost from token usage x catalog pricing for the run model.
    if (
        metrics.total_cost is None
        and spec.prompt_tokens_field
        and spec.completion_tokens_field
    ):
        metrics.total_cost = _derive_cost_from_tokens(records, run.model, spec)

    inputs_by_id, inputs_by_pos = _index_inputs(inputs, spec)

    def input_for(i: int, rec: OutputRecord) -> str | None:
        if inputs_by_id is not None:
            rec_id = rec.parsed.get(spec.id_field) if rec.parsed else None
            return inputs_by_id.get(rec_id)
        if inputs_by_pos is not None:
            return inputs_by_pos[i] if i < len(inputs_by_pos) else None
        return None

    # LLM-as-judge: a second model scores each record against a rubric. We run the
    # judge (free-form tasks), normalize to 0..1, and aggregate the mean as score.
    if grading == "judge":
        return _analyze_judge(spec, records, metrics, judge, input_for)

    # Structured extraction: per-field precision/recall/F1 vs. the gold record.
    if grading == "extraction":
        return _analyze_extraction(workflow, records, metrics, input_for, cwd)

    # Customer-supplied grading: the workflow emitted its own per-record grade,
    # so we aggregate it instead of doing classification scoring. Task-agnostic.
    if grading in ("score", "pass"):
        grades = [_record_grade(r, spec, grading) for r in records]
        valid = [g for g in grades if g is not None]
        mean = sum(valid) / len(valid) if valid else None

        rows = []
        for i, (rec, g) in enumerate(zip(records, grades)):
            if inputs_by_id is not None:
                rec_id = rec.parsed.get(spec.id_field) if rec.parsed else None
                input_text = inputs_by_id.get(rec_id)
            elif inputs_by_pos is not None:
                input_text = inputs_by_pos[i] if i < len(inputs_by_pos) else None
            else:
                input_text = None
            # score mode: a row "fails" if it scored below the run mean (the
            # relatively-worst rows the optimizer should target). pass mode: a row
            # fails if it did not pass.
            is_low = grading == "score" and g is not None and mean is not None and g < mean
            is_correct = (g >= 1.0) if (grading == "pass" and g is not None) else None
            rows.append(
                RecordRow(
                    index=i,
                    parse_ok=rec.parse_ok,
                    schema_ok=rec.schema_ok,
                    predicted=g,
                    gold=None,
                    is_refusal=_is_refusal(rec, spec, grading),
                    is_schema_error=rec.schema_ok is False,
                    is_correct=is_correct,
                    raw=rec.raw,
                    input_text=input_text,
                    score=g,
                    is_low_score=is_low,
                )
            )
        if valid:
            metrics.score = mean
            metrics.scored = len(valid)
        return RunAnalysis(metrics=metrics, rows=rows)

    # Align outputs to gold either by an explicit id field (robust to
    # reordering / skipped rows) or positionally (line N <-> label N).
    gold_map: dict[Any, Any] | None = None
    gold_list: list[Any] | None = None
    if spec.id_field:
        gold_map = _resolve_gold_by_id(workflow, gold_by_id, cwd)
        if gold_map is not None:
            _validate_id_coverage(records, gold_map, spec)
        have_gold = gold_map is not None
    else:
        gold_list = _resolve_gold(workflow, n, gold_labels, cwd)
        have_gold = gold_list is not None

    rows: list[RecordRow] = []
    pairs: list[tuple[Any, Any]] = []
    for i, rec in enumerate(records):
        predicted = _predicted_label(rec, spec)
        is_refusal = _is_refusal(rec, spec)
        is_schema_error = rec.schema_ok is False
        rec_id = rec.parsed.get(spec.id_field) if (spec.id_field and rec.parsed) else None

        if gold_map is not None:
            matched = rec_id is not None and rec_id in gold_map
            gold_value = gold_map[rec_id] if matched else None
            is_correct = (predicted == gold_value) if matched else None
        elif gold_list is not None:
            matched = True
            gold_value = gold_list[i]
            is_correct = predicted == gold_value
        else:
            matched = False
            gold_value = None
            is_correct = None

        if inputs_by_id is not None:
            input_text = inputs_by_id.get(rec_id)
        elif inputs_by_pos is not None:
            input_text = inputs_by_pos[i] if i < len(inputs_by_pos) else None
        else:
            input_text = None

        rows.append(
            RecordRow(
                index=i,
                parse_ok=rec.parse_ok,
                schema_ok=rec.schema_ok,
                predicted=predicted,
                gold=gold_value,
                is_refusal=is_refusal,
                is_schema_error=is_schema_error,
                is_correct=is_correct,
                raw=rec.raw,
                input_text=input_text,
            )
        )
        if matched:
            pairs.append((gold_value, predicted))

    if have_gold:
        acc, p, r, f1, per_class = _macro_prf(pairs)
        metrics.accuracy = acc
        metrics.precision = p
        metrics.recall = r
        metrics.f1 = f1
        metrics.per_class = per_class
        metrics.labeled = len(pairs)

    return RunAnalysis(metrics=metrics, rows=rows)


def evaluate(
    workflow: Workflow,
    run: RunResult,
    *,
    gold_labels: list[Any] | None = None,
    gold_by_id: dict[Any, Any] | None = None,
    judge: Any | None = None,
    cwd: Path | None = None,
) -> Metrics:
    """Evaluate a single harness run into a :class:`Metrics` scorecard."""
    return analyze(
        workflow,
        run,
        gold_labels=gold_labels,
        gold_by_id=gold_by_id,
        judge=judge,
        cwd=cwd,
    ).metrics
