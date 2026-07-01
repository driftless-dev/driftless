"""P3.2(d): the engine optimizes a judge-graded free-form workflow end-to-end.

Proves the whole loop (no gold labels, free-form text outputs, a second model
inside the loop) works with an injected deterministic judge -- so judge grading
needs no network for the regression harness.
"""

from pathlib import Path

from driftless.engine import MigrationStatus, Objective, run_migration
from driftless.judges import JudgeResult


class KeywordJudge:
    def score(self, *, input_text, output_text):
        hit = "good" in (output_text or "")
        return JudgeResult(1.0 if hit else 0.2, "ok" if hit else "no keyword")


def test_engine_optimizes_judge_graded_workflow(tmp_path: Path):
    from scenarios import JudgeKeywordRepair, build_judge_scenario

    wf = build_judge_scenario(tmp_path)
    result = run_migration(
        "summarizer", wf, "new-model", generator=JudgeKeywordRepair(), judge=KeywordJudge(),
        cwd=tmp_path, seed=1,
    )
    assert result.status == MigrationStatus.PASS, result.message
    assert result.final.score is not None and result.final.score >= 0.9
    assert result.edited_files == ["prompts/sys.txt"]
    committed = (tmp_path / "prompts/sys.txt").read_text().lower()
    assert "say good" in committed


def test_refine_maximizes_judge_score(tmp_path: Path):
    from scenarios import JudgeKeywordRepair, build_judge_scenario

    # Same engine, MAXIMIZE objective (refine): model pinned, judge-graded.
    wf = build_judge_scenario(tmp_path)
    result = run_migration(
        "summarizer", wf, "old-model", generator=JudgeKeywordRepair(), judge=KeywordJudge(),
        cwd=tmp_path, seed=1, objective=Objective.MAXIMIZE,
    )
    assert result.status == MigrationStatus.PASS, result.message
    assert result.suggested_thresholds.get("min_score") is not None


def test_migration_blocks_when_judge_agreement_gate_fails(tmp_path: Path):
    from driftless.contract import JudgeSpec
    from scenarios import JudgeKeywordRepair, build_judge_scenario

    wf = build_judge_scenario(tmp_path)
    judge_block = wf.eval.judge.model_dump()
    judge_block.update(
        {
            "calibration_path": "calib.jsonl",
            "max_mae": 0.01,
        }
    )
    wf = wf.model_copy(update={"eval": wf.eval.model_copy(update={"judge": JudgeSpec.model_validate(judge_block)})})
    (tmp_path / "calib.jsonl").write_text(
        '{"input": "t0", "output": "summary here", "score": 1.0}\n'
    )
    result = run_migration(
        "summarizer", wf, "new-model", generator=JudgeKeywordRepair(), judge=KeywordJudge(),
        cwd=tmp_path, seed=1,
    )
    assert result.status == MigrationStatus.BLOCKED
    assert "mean absolute error" in result.message.lower()
