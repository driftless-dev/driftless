import json
from pathlib import Path

import pytest

from driftless.contract import Workflow
from driftless.evaluation import evaluate, load_labels
from driftless.harness import RunResult


def _workflow(tmp_path: Path, **eval_extra) -> Workflow:
    eval_block = {"labels_path": "labels.jsonl"}
    eval_block.update(eval_extra)
    return Workflow.model_validate(
        {
            "run": {
                "command": "true",
                "input_path": "in.jsonl",
                "output_path": "out.jsonl",
            },
            "model": {"current": "m", "env_var": "M"},
            "eval": eval_block,
        }
    )


def _run(tmp_path: Path, lines: list[dict], duration: float = 2.0) -> RunResult:
    out = tmp_path / "out.jsonl"
    out.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return RunResult(model="m", output_path=out, returncode=0, duration_seconds=duration)


def _workflow_no_labels(tmp_path: Path, **eval_extra) -> Workflow:
    return Workflow.model_validate(
        {
            "run": {"command": "true", "input_path": "in.jsonl", "output_path": "out.jsonl"},
            "model": {"current": "m", "env_var": "M"},
            "eval": eval_extra,
        }
    )


def test_score_field_aggregates_mean(tmp_path: Path):
    wf = _workflow_no_labels(tmp_path, score_field="quality")
    run = _run(tmp_path, [{"quality": 0.9}, {"quality": 0.5}, {"quality": 1.0}])
    m = evaluate(wf, run, cwd=tmp_path)
    assert m.score == pytest.approx((0.9 + 0.5 + 1.0) / 3)
    assert m.scored == 3
    # No classification metrics in score mode, and empty labels aren't refusals.
    assert m.f1 is None and m.accuracy is None
    assert m.refusal_rate == 0.0


def test_pass_field_is_pass_rate(tmp_path: Path):
    wf = _workflow_no_labels(tmp_path, pass_field="passed")
    run = _run(tmp_path, [{"passed": True}, {"passed": False}, {"passed": True}, {"passed": True}])
    m = evaluate(wf, run, cwd=tmp_path)
    assert m.score == pytest.approx(0.75)
    assert m.scored == 4
    assert m.f1 is None


def test_score_mode_marks_below_mean_rows_low(tmp_path: Path):
    from driftless.evaluation import analyze

    wf = _workflow_no_labels(tmp_path, score_field="quality")
    run = _run(tmp_path, [{"quality": 0.2}, {"quality": 0.9}, {"quality": 1.0}])
    rows = analyze(wf, run, cwd=tmp_path).rows
    # mean = 0.7; only the 0.2 row is below it.
    low = [r for r in rows if r.is_low_score]
    assert len(low) == 1 and low[0].score == pytest.approx(0.2)


def test_score_and_pass_field_mutually_exclusive(tmp_path: Path):
    with pytest.raises(Exception):
        _workflow_no_labels(tmp_path, score_field="q", pass_field="p")


def test_score_mode_still_counts_schema_errors(tmp_path: Path):
    schema = {
        "type": "object",
        "required": ["quality"],
        "properties": {"quality": {"type": "number"}},
        "additionalProperties": False,
    }
    (tmp_path / "schema.json").write_text(json.dumps(schema))
    wf = _workflow_no_labels(tmp_path, score_field="quality", schema_path="schema.json")
    run = _run(tmp_path, [{"quality": 0.9}, {"quality": 0.8, "extra": 1}])
    m = evaluate(wf, run, cwd=tmp_path)
    assert m.schema_errors == 1  # second row violates additionalProperties


def test_perfect_classification(tmp_path: Path):
    (tmp_path / "labels.jsonl").write_text(
        '{"label":"billing"}\n{"label":"technical"}\n'
    )
    wf = _workflow(tmp_path)
    run = _run(tmp_path, [{"label": "billing"}, {"label": "technical"}], duration=2.0)

    m = evaluate(wf, run, cwd=tmp_path)
    assert m.n == 2
    assert m.accuracy == pytest.approx(1.0)
    assert m.f1 == pytest.approx(1.0)
    assert m.precision == pytest.approx(1.0)
    assert m.refusal_rate == 0.0
    assert m.avg_latency_ms == pytest.approx(1000.0)  # 2s / 2 records


def test_misclassification_and_macro_f1(tmp_path: Path):
    (tmp_path / "labels.jsonl").write_text(
        '"billing"\n"technical"\n"billing"\n"technical"\n'
    )
    wf = _workflow(tmp_path)
    # 1 of 2 billing wrong, technical perfect.
    run = _run(
        tmp_path,
        [
            {"label": "billing"},
            {"label": "technical"},
            {"label": "technical"},  # wrong: should be billing
            {"label": "technical"},
        ],
    )
    m = evaluate(wf, run, cwd=tmp_path)
    assert m.accuracy == pytest.approx(0.75)
    # billing: tp=1 fp=0 fn=1 -> p=1.0 r=0.5 f1=0.667
    # technical: tp=2 fp=1 fn=0 -> p=0.667 r=1.0 f1=0.8
    assert m.per_class["billing"].recall == pytest.approx(0.5)
    assert m.per_class["technical"].precision == pytest.approx(2 / 3)
    assert m.f1 == pytest.approx((0.6667 + 0.8) / 2, abs=1e-3)


def test_refusal_and_schema_error(tmp_path: Path):
    (tmp_path / "labels.jsonl").write_text('"billing"\n"billing"\n"billing"\n')
    wf = _workflow(tmp_path)
    out = tmp_path / "out.jsonl"
    # one good, one refusal (null label), one invalid JSON.
    out.write_text('{"label":"billing"}\n{"label":null}\nNOT JSON\n')
    run = RunResult(model="m", output_path=out, returncode=0, duration_seconds=3.0)

    m = evaluate(wf, run, cwd=tmp_path)
    assert m.n == 3
    assert m.refusals == 1
    assert m.refusal_rate == pytest.approx(1 / 3)
    assert m.schema_errors == 1  # the NOT JSON line
    assert m.schema_error_rate == pytest.approx(1 / 3)


def test_jsonschema_validation(tmp_path: Path):
    schema = {
        "type": "object",
        "properties": {"label": {"enum": ["billing", "technical"]}},
        "required": ["label"],
    }
    (tmp_path / "schema.json").write_text(json.dumps(schema))
    (tmp_path / "labels.jsonl").write_text('"billing"\n"billing"\n')
    wf = _workflow(tmp_path, schema_path="schema.json")
    run = _run(tmp_path, [{"label": "billing"}, {"label": "nonsense"}])

    m = evaluate(wf, run, cwd=tmp_path)
    assert m.schema_errors == 1  # "nonsense" not in enum
    assert m.schema_error_rate == pytest.approx(0.5)


def test_label_count_mismatch_raises(tmp_path: Path):
    (tmp_path / "labels.jsonl").write_text('"billing"\n')
    wf = _workflow(tmp_path)
    run = _run(tmp_path, [{"label": "billing"}, {"label": "billing"}])
    with pytest.raises(Exception):
        evaluate(wf, run, cwd=tmp_path)


def test_cost_field(tmp_path: Path):
    (tmp_path / "labels.jsonl").write_text('"billing"\n"billing"\n')
    wf = _workflow(tmp_path, cost_field="cost")
    run = _run(
        tmp_path,
        [{"label": "billing", "cost": 0.01}, {"label": "billing", "cost": 0.02}],
    )
    m = evaluate(wf, run, cwd=tmp_path)
    assert m.total_cost == pytest.approx(0.03)


def test_load_labels_scalar_and_dict(tmp_path: Path):
    p = tmp_path / "l.jsonl"
    p.write_text('"a"\n{"label":"b"}\n')
    assert load_labels(p, "label") == ["a", "b"]


def test_cost_derived_from_tokens_and_catalog_pricing(tmp_path: Path):
    # gpt-4o pricing: $2.5/1M input, $10/1M output.
    (tmp_path / "labels.jsonl").write_text('"billing"\n"billing"\n')
    wf = _workflow(
        tmp_path,
        prompt_tokens_field="prompt_tokens",
        completion_tokens_field="completion_tokens",
    )
    out = tmp_path / "out.jsonl"
    out.write_text(
        '{"label":"billing","prompt_tokens":1000,"completion_tokens":500}\n'
        '{"label":"billing","prompt_tokens":2000,"completion_tokens":0}\n'
    )
    run = RunResult(model="gpt-4o", output_path=out, returncode=0, duration_seconds=1.0)
    m = evaluate(wf, run, cwd=tmp_path)
    expected = (1000 * 2.5 + 500 * 10.0) / 1e6 + (2000 * 2.5) / 1e6
    assert m.total_cost == pytest.approx(expected)


def test_explicit_cost_field_wins_over_token_derivation(tmp_path: Path):
    (tmp_path / "labels.jsonl").write_text('"billing"\n')
    wf = _workflow(
        tmp_path,
        cost_field="cost",
        prompt_tokens_field="prompt_tokens",
        completion_tokens_field="completion_tokens",
    )
    out = tmp_path / "out.jsonl"
    out.write_text('{"label":"billing","cost":0.99,"prompt_tokens":1000,"completion_tokens":500}\n')
    run = RunResult(model="gpt-4o", output_path=out, returncode=0, duration_seconds=1.0)
    m = evaluate(wf, run, cwd=tmp_path)
    assert m.total_cost == pytest.approx(0.99)


def test_no_cost_without_pricing(tmp_path: Path):
    (tmp_path / "labels.jsonl").write_text('"billing"\n')
    wf = _workflow(
        tmp_path,
        prompt_tokens_field="prompt_tokens",
        completion_tokens_field="completion_tokens",
    )
    out = tmp_path / "out.jsonl"
    out.write_text('{"label":"billing","prompt_tokens":1000,"completion_tokens":500}\n')
    run = RunResult(model="no-pricing-model", output_path=out, returncode=0, duration_seconds=1.0)
    m = evaluate(wf, run, cwd=tmp_path)
    assert m.total_cost is None


# --------------------------------------------------------------------------- #
# P0.4: id-based output<->label alignment
# --------------------------------------------------------------------------- #
def test_id_alignment_tolerates_reordered_outputs(tmp_path: Path):
    # Labels in id order a, b, c -- but outputs come back shuffled. Positional
    # alignment would score this as wrong; id alignment must score it perfect.
    (tmp_path / "labels.jsonl").write_text(
        '{"id":"a","label":"billing"}\n'
        '{"id":"b","label":"technical"}\n'
        '{"id":"c","label":"account"}\n'
    )
    wf = _workflow(tmp_path, id_field="id")
    run = _run(
        tmp_path,
        [
            {"id": "c", "label": "account"},
            {"id": "a", "label": "billing"},
            {"id": "b", "label": "technical"},
        ],
    )
    m = evaluate(wf, run, cwd=tmp_path)
    assert m.n == 3
    assert m.accuracy == pytest.approx(1.0)
    assert m.f1 == pytest.approx(1.0)


def test_id_alignment_detects_misclassification_regardless_of_order(tmp_path: Path):
    (tmp_path / "labels.jsonl").write_text(
        '{"id":"a","label":"billing"}\n'
        '{"id":"b","label":"technical"}\n'
    )
    wf = _workflow(tmp_path, id_field="id")
    run = _run(
        tmp_path,
        [
            {"id": "b", "label": "technical"},  # correct
            {"id": "a", "label": "technical"},  # wrong: should be billing
        ],
    )
    m = evaluate(wf, run, cwd=tmp_path)
    assert m.accuracy == pytest.approx(0.5)


def test_id_alignment_unknown_output_id_raises(tmp_path: Path):
    (tmp_path / "labels.jsonl").write_text('{"id":"a","label":"billing"}\n')
    wf = _workflow(tmp_path, id_field="id")
    run = _run(tmp_path, [{"id": "zzz", "label": "billing"}])
    with pytest.raises(Exception):
        evaluate(wf, run, cwd=tmp_path)


def test_id_alignment_missing_output_raises(tmp_path: Path):
    (tmp_path / "labels.jsonl").write_text(
        '{"id":"a","label":"billing"}\n{"id":"b","label":"technical"}\n'
    )
    wf = _workflow(tmp_path, id_field="id")
    run = _run(tmp_path, [{"id": "a", "label": "billing"}])  # dropped "b"
    with pytest.raises(Exception):
        evaluate(wf, run, cwd=tmp_path)


def test_id_alignment_duplicate_output_id_raises(tmp_path: Path):
    (tmp_path / "labels.jsonl").write_text(
        '{"id":"a","label":"billing"}\n{"id":"b","label":"technical"}\n'
    )
    wf = _workflow(tmp_path, id_field="id")
    run = _run(
        tmp_path,
        [{"id": "a", "label": "billing"}, {"id": "a", "label": "technical"}],
    )
    with pytest.raises(Exception):
        evaluate(wf, run, cwd=tmp_path)


def test_load_labels_by_id_rejects_duplicates(tmp_path: Path):
    from driftless.evaluation import load_labels_by_id

    p = tmp_path / "l.jsonl"
    p.write_text('{"id":"a","label":"x"}\n{"id":"a","label":"y"}\n')
    with pytest.raises(Exception):
        load_labels_by_id(p, "id", "label")
