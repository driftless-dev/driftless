"""P3.2(d): LLM-as-judge grading (free-form tasks), tested deterministically."""

import json
from pathlib import Path

import pytest

from driftless.contract import JudgeSpec, Workflow
from driftless.engine import cluster_failures
from driftless.evaluation import analyze, evaluate
from driftless.harness import RunResult
from driftless.judges import JudgeResult, LLMJudge, judge_agreement


class KeywordJudge:
    """Deterministic stub judge: score = 1.0 if a keyword is present, else 0.2."""

    def __init__(self, keyword: str = "good"):
        self.keyword = keyword
        self.calls = 0

    def score(self, *, input_text, output_text):
        self.calls += 1
        hit = self.keyword in (output_text or "")
        return JudgeResult(1.0 if hit else 0.2, "matched" if hit else "missing keyword")


def _judge_workflow(**judge_extra) -> Workflow:
    judge = {"rubric": "Award full marks if the summary says 'good'."}
    judge.update(judge_extra)
    return Workflow.model_validate(
        {
            "run": {"command": "true", "input_path": "in.jsonl", "output_path": "out.jsonl"},
            "model": {"current": "m", "env_var": "M"},
            "eval": {"judge": judge},
        }
    )


def _run_text(tmp_path: Path, lines: list[str]) -> RunResult:
    out = tmp_path / "out.jsonl"
    out.write_text("\n".join(lines) + "\n")
    return RunResult(model="m", output_path=out, returncode=0, duration_seconds=1.0)


def test_judge_scores_free_form_text_outputs(tmp_path: Path):
    # Free-form (non-JSON) outputs: judge mode must not treat them as schema errors.
    run = _run_text(tmp_path, ["this is good", "this is bad", "very good indeed"])
    analysis = analyze(_judge_workflow(), run, judge=KeywordJudge(), cwd=tmp_path)
    m = analysis.metrics
    assert m.schema_error_rate == pytest.approx(0.0)
    assert m.score == pytest.approx((1.0 + 0.2 + 1.0) / 3)
    assert m.scored == 3
    # the low-scoring row is flagged for the optimizer
    low = [r for r in analysis.rows if r.is_low_score]
    assert len(low) == 1 and low[0].index == 1
    assert low[0].rationale == "missing keyword"


def test_judge_pass_threshold_marks_correctness(tmp_path: Path):
    run = _run_text(tmp_path, ["good", "bad"])
    analysis = analyze(_judge_workflow(pass_threshold=0.5), run, judge=KeywordJudge(), cwd=tmp_path)
    by_index = {r.index: r for r in analysis.rows}
    assert by_index[0].is_correct is True
    assert by_index[1].is_correct is False


def test_judge_low_scores_cluster(tmp_path: Path):
    run = _run_text(tmp_path, ["good", "bad", "bad"])
    analysis = analyze(_judge_workflow(), run, judge=KeywordJudge(), cwd=tmp_path)
    clusters = cluster_failures(analysis.rows)
    assert any(c.kind == "low_score" for c in clusters)


def test_judge_required_when_grading_is_judge(tmp_path: Path):
    from driftless.errors import DriftlessError

    run = _run_text(tmp_path, ["good"])
    with pytest.raises(DriftlessError, match="requires a judge"):
        evaluate(_judge_workflow(), run, cwd=tmp_path)


def test_judge_reads_output_field_when_structured(tmp_path: Path):
    # When outputs are JSON, judge.output_field selects the text to grade.
    out = tmp_path / "out.jsonl"
    out.write_text(json.dumps({"summary": "good one"}) + "\n" + json.dumps({"summary": "weak"}) + "\n")
    run = RunResult(model="m", output_path=out, returncode=0, duration_seconds=1.0)
    analysis = analyze(_judge_workflow(output_field="summary"), run, judge=KeywordJudge(), cwd=tmp_path)
    assert analysis.metrics.score == pytest.approx((1.0 + 0.2) / 2)


# --- LLMJudge prompt/parse + normalization (with an injected completion fn) --- #
def test_llm_judge_normalizes_by_scale(tmp_path: Path):
    spec = JudgeSpec(rubric="score it", scale_max=5.0)

    def fake_complete(system, user, temperature):
        return json.dumps({"score": 4, "rationale": "solid"})

    judge = LLMJudge(spec, complete_fn=fake_complete)
    res = judge.score(input_text="q", output_text="a")
    assert res.score == pytest.approx(0.8)  # 4/5
    assert res.raw_score == 4.0
    assert res.rationale == "solid"


def test_llm_judge_handles_non_numeric_score(tmp_path: Path):
    spec = JudgeSpec(rubric="score it")
    judge = LLMJudge(spec, complete_fn=lambda s, u, t: "not json at all")
    res = judge.score(input_text="q", output_text="a")
    assert res.score == 0.0


def test_judge_agreement_against_calibration(tmp_path: Path):
    spec = JudgeSpec(
        rubric="award full marks for 'good'", calibration_path="calib.jsonl"
    )
    (tmp_path / "calib.jsonl").write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {"input": "q1", "output": "good", "score": 1.0},
                {"input": "q2", "output": "bad", "score": 0.0},
                {"input": "q3", "output": "good", "score": 1.0},
            ]
        )
        + "\n"
    )
    agreement = judge_agreement(KeywordJudge(), spec, cwd=tmp_path)
    assert agreement is not None
    assert agreement.n == 3
    # KeywordJudge gives 1.0/0.2/1.0 vs human 1.0/0.0/1.0 -> MAE = 0.2/3.
    assert agreement.mean_abs_error == pytest.approx(0.2 / 3)
    assert agreement.correlation == pytest.approx(1.0)


def test_judge_agreement_none_without_calibration(tmp_path: Path):
    spec = JudgeSpec(rubric="x")
    assert judge_agreement(KeywordJudge(), spec, cwd=tmp_path) is None


def test_require_judge_agreement_passes_when_within_gate(tmp_path: Path):
    from driftless.judges import require_judge_agreement

    spec = JudgeSpec(
        rubric="award full marks for 'good'",
        calibration_path="calib.jsonl",
        max_mae=0.2,
    )
    (tmp_path / "calib.jsonl").write_text(
        json.dumps({"input": "q1", "output": "good", "score": 1.0}) + "\n"
    )
    agreement = require_judge_agreement(KeywordJudge(), spec, cwd=tmp_path)
    assert agreement is not None
    assert agreement.mean_abs_error == 0.0


def test_require_judge_agreement_blocks_high_mae(tmp_path: Path):
    from driftless.errors import DriftlessError
    from driftless.judges import require_judge_agreement

    spec = JudgeSpec(
        rubric="award full marks for 'good'",
        calibration_path="calib.jsonl",
        max_mae=0.01,
    )
    (tmp_path / "calib.jsonl").write_text(
        json.dumps({"input": "q1", "output": "bad", "score": 1.0}) + "\n"
    )
    with pytest.raises(DriftlessError, match="mean absolute error"):
        require_judge_agreement(KeywordJudge(), spec, cwd=tmp_path)


def test_judge_gates_require_calibration_path():
    with pytest.raises(ValueError, match="calibration_path"):
        JudgeSpec(rubric="x", max_mae=0.1)


def test_judge_evidence_samples_prefers_lowest_scores():
    from driftless.evaluation import RecordRow
    from driftless.judges import judge_evidence_samples

    rows = [
        RecordRow(
            index=0, parse_ok=True, schema_ok=True, predicted=0.2, gold=None,
            is_refusal=False, is_schema_error=False, is_correct=None,
            is_low_score=True, score=0.2, rationale="low",
        ),
        RecordRow(
            index=1, parse_ok=True, schema_ok=True, predicted=0.5, gold=None,
            is_refusal=False, is_schema_error=False, is_correct=None,
            is_low_score=True, score=0.5, rationale="mid",
        ),
        RecordRow(
            index=2, parse_ok=True, schema_ok=True, predicted=1.0, gold=None,
            is_refusal=False, is_schema_error=False, is_correct=True,
            is_low_score=False, score=1.0, rationale="high",
        ),
    ]
    samples = judge_evidence_samples(rows, max_samples=2)
    assert [s["index"] for s in samples] == [0, 1]
    assert samples[0]["rationale"] == "low"
