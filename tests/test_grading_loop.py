"""End-to-end engine test for customer-supplied grading (score mode).

Proves the *whole* loop is task-agnostic: with no gold labels and no
classification, a workflow that emits its own per-record `score` is optimized by
the same clustering + candidate-selection + holdout machinery used for
classification. The "grader" lives entirely in the customer's command.
"""

from pathlib import Path

from driftless.engine import MigrationStatus, cluster_failures, run_migration
from driftless.evaluation import RecordRow
from scenarios import ScoreRepair, build_score_scenario


def test_clusters_surface_low_score_rows():
    rows = [
        RecordRow(0, True, True, 0.2, None, False, False, None, score=0.2, is_low_score=True),
        RecordRow(1, True, True, 1.0, None, False, False, None, score=1.0, is_low_score=False),
    ]
    clusters = cluster_failures(rows)
    assert any(c.kind == "low_score" and c.count == 1 for c in clusters)


def test_score_graded_workflow_is_optimized_to_pass(tmp_path: Path):
    wf = build_score_scenario(tmp_path)
    result = run_migration(
        "qa", wf, "new-model", generator=ScoreRepair(), cwd=tmp_path, seed=1
    )
    assert result.status == MigrationStatus.PASS, result.message
    assert (result.final.score or 0.0) >= 0.9
    assert result.final.f1 is None  # never did classification
    assert result.edited_files == ["prompts/system.txt"]
    assert "be strict" in (tmp_path / "prompts" / "system.txt").read_text().lower()


def test_score_graded_workflow_blocks_without_repair(tmp_path: Path):
    wf = build_score_scenario(tmp_path)
    result = run_migration("qa", wf, "new-model", cwd=tmp_path, seed=1)
    assert result.status == MigrationStatus.BLOCKED
