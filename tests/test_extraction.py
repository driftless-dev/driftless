"""P3.2(c): structured-extraction grading (per-field precision/recall/F1)."""

import json
from pathlib import Path

import pytest

from driftless.contract import Workflow
from driftless.engine import cluster_failures
from driftless.evaluation import analyze, evaluate
from driftless.harness import RunResult


def _workflow(fields, **eval_extra) -> Workflow:
    eval_block = {
        "labels_path": "labels.jsonl",
        "id_field": "id",
        "fields": fields,
    }
    eval_block.update(eval_extra)
    return Workflow.model_validate(
        {
            "run": {"command": "true", "input_path": "in.jsonl", "output_path": "out.jsonl"},
            "model": {"current": "m", "env_var": "M"},
            "eval": eval_block,
        }
    )


def _write(tmp_path: Path, name: str, rows: list[dict]) -> None:
    (tmp_path / name).write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _run(tmp_path: Path, rows: list[dict]) -> RunResult:
    _write(tmp_path, "out.jsonl", rows)
    return RunResult(model="m", output_path=tmp_path / "out.jsonl", returncode=0, duration_seconds=1.0)


def test_perfect_extraction_scores_one(tmp_path: Path):
    _write(tmp_path, "labels.jsonl", [
        {"id": "a", "name": "Ada", "amount": "10"},
        {"id": "b", "name": "Bo", "amount": "20"},
    ])
    run = _run(tmp_path, [
        {"id": "a", "name": "Ada", "amount": "10"},
        {"id": "b", "name": "Bo", "amount": "20"},
    ])
    m = evaluate(_workflow(["name", "amount"]), run, cwd=tmp_path)
    assert m.f1 == pytest.approx(1.0)
    assert m.precision == pytest.approx(1.0)
    assert m.recall == pytest.approx(1.0)
    assert m.accuracy == pytest.approx(1.0)
    assert m.per_field["name"].f1 == pytest.approx(1.0)


def test_wrong_field_lowers_that_fields_metrics(tmp_path: Path):
    _write(tmp_path, "labels.jsonl", [
        {"id": "a", "name": "Ada", "amount": "10"},
        {"id": "b", "name": "Bo", "amount": "20"},
    ])
    # name is perfect; amount is wrong on record b.
    run = _run(tmp_path, [
        {"id": "a", "name": "Ada", "amount": "10"},
        {"id": "b", "name": "Bo", "amount": "99"},
    ])
    analysis = analyze(_workflow(["name", "amount"]), run, cwd=tmp_path)
    m = analysis.metrics
    assert m.per_field["name"].f1 == pytest.approx(1.0)
    # amount: 1 correct of 2 predicted/gold -> p=r=0.5 -> f1=0.5
    assert m.per_field["amount"].precision == pytest.approx(0.5)
    assert m.per_field["amount"].recall == pytest.approx(0.5)
    # macro F1 = mean(1.0, 0.5) = 0.75
    assert m.f1 == pytest.approx(0.75)
    # exact-match accuracy: only record a is fully correct -> 0.5
    assert m.accuracy == pytest.approx(0.5)
    # the wrong row carries the field error
    wrong = [r for r in analysis.rows if r.field_errors]
    assert len(wrong) == 1 and wrong[0].field_errors == ["amount"]


def test_missing_extraction_hurts_recall_not_precision(tmp_path: Path):
    _write(tmp_path, "labels.jsonl", [
        {"id": "a", "amount": "10"},
        {"id": "b", "amount": "20"},
    ])
    # record b omits amount entirely (not extracted).
    run = _run(tmp_path, [{"id": "a", "amount": "10"}, {"id": "b"}])
    m = evaluate(_workflow(["amount"]), run, cwd=tmp_path)
    # precision = 1/1 (only one predicted, correct); recall = 1/2.
    assert m.per_field["amount"].precision == pytest.approx(1.0)
    assert m.per_field["amount"].recall == pytest.approx(0.5)


def test_extraction_field_errors_cluster_by_field(tmp_path: Path):
    _write(tmp_path, "labels.jsonl", [
        {"id": "a", "name": "Ada", "amount": "10"},
        {"id": "b", "name": "Bo", "amount": "20"},
        {"id": "c", "name": "Cy", "amount": "30"},
    ])
    run = _run(tmp_path, [
        {"id": "a", "name": "WRONG", "amount": "10"},
        {"id": "b", "name": "WRONG", "amount": "20"},
        {"id": "c", "name": "Cy", "amount": "30"},
    ])
    analysis = analyze(_workflow(["name", "amount"]), run, cwd=tmp_path)
    clusters = cluster_failures(analysis.rows)
    field_clusters = [c for c in clusters if c.kind == "field_error"]
    assert len(field_clusters) == 1
    assert field_clusters[0].key == "wrong field: name"
    assert field_clusters[0].count == 2


def test_unparseable_output_counts_as_schema_error_in_extraction(tmp_path: Path):
    _write(tmp_path, "labels.jsonl", [{"id": "a", "name": "Ada"}, {"id": "b", "name": "Bo"}])
    out = tmp_path / "out.jsonl"
    out.write_text('{"id": "a", "name": "Ada"}\nnot json\n')
    run = RunResult(model="m", output_path=out, returncode=0, duration_seconds=1.0)
    analysis = analyze(_workflow(["name"]), run, cwd=tmp_path)
    assert analysis.metrics.schema_error_rate == pytest.approx(0.5)
    clusters = cluster_failures(analysis.rows)
    assert any(c.kind == "schema_error" for c in clusters)


def test_unknown_output_id_is_rejected(tmp_path: Path):
    from driftless.errors import DriftlessError

    _write(tmp_path, "labels.jsonl", [{"id": "a", "name": "Ada"}])
    run = _run(tmp_path, [{"id": "zzz", "name": "Ada"}])
    with pytest.raises(DriftlessError, match="not found in labels"):
        analyze(_workflow(["name"]), run, cwd=tmp_path)


def test_extraction_requires_id_field():
    with pytest.raises(ValueError, match="requires eval.id_field"):
        Workflow.model_validate(
            {
                "run": {"command": "true", "input_path": "i", "output_path": "o"},
                "model": {"current": "m", "env_var": "M"},
                "eval": {"labels_path": "l.jsonl", "fields": ["name"]},
            }
        )
