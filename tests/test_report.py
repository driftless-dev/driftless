import json
from pathlib import Path

from driftless.compare import ThresholdCheck
from driftless.contract import Workflow
from driftless.engine import (
    AttemptRecord,
    FailureCluster,
    MigrationResult,
    MigrationStatus,
)
from driftless.evaluation import Metrics
from driftless.judges import JudgeAgreement
from driftless.report import render_markdown, result_to_dict, save_report


def _metrics(**kw) -> Metrics:
    base = dict(n=10, schema_error_rate=0.0, refusal_rate=0.0)
    base.update(kw)
    return Metrics(**base)


def _result(status: MigrationStatus, **kw) -> MigrationResult:
    base = dict(
        workflow="support_classifier",
        current_model="gpt-4o-mini",
        target_model="gpt-5-mini",
        status=status,
        iterations=2,
        baseline=_metrics(f1=0.914, precision=0.948),
        naive_target=_metrics(f1=0.873, precision=0.912, schema_error_rate=0.038),
        final=_metrics(f1=0.921, precision=0.951, schema_error_rate=0.006),
    )
    base.update(kw)
    return MigrationResult(**base)


def test_render_pass_report_contains_key_sections():
    result = _result(
        MigrationStatus.PASS,
        edited_files=["prompts/support_classifier.md"],
        holdout_checks=[ThresholdCheck("min_f1", True, "0.921 >= 0.9")],
    )
    md = render_markdown(result)
    assert "# Model Migration: `support_classifier`" in md
    assert "**Status:** `pass`" in md
    assert "| F1 | 0.914 | 0.873 | 0.921 |" in md
    assert "Edited `prompts/support_classifier.md`" in md
    assert "Holdout Validation" in md
    assert "Approve migration." in md


def test_render_partial_marks_uncommitted_and_suggests_fallback():
    wf = Workflow.model_validate(
        {
            "run": {"command": "true", "input_path": "i", "output_path": "o"},
            "model": {
                "current": "gpt-4o-mini",
                "env_var": "M",
                "target_candidates": ["gpt-5-mini", "gpt-5-nano"],
            },
        }
    )
    result = _result(
        MigrationStatus.PARTIAL,
        tuning_checks=[ThresholdCheck("min_f1", False, "0.88 >= 0.9")],
        remaining_clusters=[FailureCluster("misclassification", "refund -> billing", 7, [3, 9])],
    )
    md = render_markdown(result, wf)
    assert "NOT committed" in md
    assert "No changes were committed." in md
    assert "Unmet Thresholds" in md
    assert "7 misclassification: refund -> billing" in md
    assert "Suggested Fallback Candidates" in md
    assert "`gpt-5-nano`" in md  # excludes current target gpt-5-mini


def test_model_change_only_message():
    md = render_markdown(_result(MigrationStatus.MODEL_CHANGE_ONLY))
    assert "Updated model ID only" in md
    assert "Model ID change only" in md


def test_result_to_dict_is_json_serializable():
    result = _result(MigrationStatus.PASS, edited_files=["a.md"])
    payload = result_to_dict(result)
    text = json.dumps(payload)  # must not raise
    assert json.loads(text)["status"] == "pass"
    assert payload["succeeded"] is True


def test_trajectory_section_shows_clusters_and_attempts():
    result = _result(
        MigrationStatus.PASS,
        edited_files=["prompts/p.md"],
        cluster_history=[
            [FailureCluster("schema_error", "invalid output schema", 6, [])],
            [FailureCluster("schema_error", "invalid output schema", 0, [])],
        ],
        experiment_log=[
            AttemptRecord(0, "llm", "add raw-json rule", ["prompts/p.md"], 0.80, 0.0, 0.0, False, True),
            AttemptRecord(1, "llm", "tighten refund rule", ["prompts/p.md"], 0.92, 0.0, 0.0, True, True),
        ],
    )
    md = render_markdown(result)
    assert "Optimization Trajectory" in md
    assert "schema_error:invalid output schema`: 6 -> 0" in md
    assert "tighten refund rule" in md
    # And it survives JSON serialization.
    payload = result_to_dict(result)
    json.dumps(payload)
    assert len(payload["experiment_log"]) == 2
    assert "original_editable_files" in payload


def test_confidence_caveats_render_and_serialize():
    result = _result(
        MigrationStatus.PASS,
        edited_files=["p.md"],
        warnings=["Small dataset: 6 labeled examples (< 30)."],
    )
    md = render_markdown(result)
    assert "Confidence Caveats" in md
    assert "Small dataset" in md
    assert result_to_dict(result)["warnings"] == result.warnings


def test_refine_report_uses_refine_framing_and_two_column_scorecard():
    # Same model on both sides signals a refine (dataset-change) result.
    result = _result(
        MigrationStatus.PASS,
        current_model="gpt-4o-mini",
        target_model="gpt-4o-mini",
        edited_files=["prompts/p.md"],
        suggested_thresholds={"min_f1": 0.89, "max_schema_error_rate": 0.04},
    )
    md = render_markdown(result)
    assert "# Prompt Refinement: `support_classifier`" in md
    assert "model pinned to `gpt-4o-mini`" in md
    # Two-column current-vs-refined scorecard (no redundant naive column).
    assert "| Metric | Current prompt | Refined prompt |" in md
    assert "| F1 | 0.914 | 0.921 |" in md
    # Suggested thresholds block is emitted as pasteable YAML.
    assert "## Suggested Thresholds" in md
    assert "min_f1: 0.89" in md
    assert result_to_dict(result)["suggested_thresholds"]["min_f1"] == 0.89


def test_refine_no_change_report_is_useful():
    result = _result(
        MigrationStatus.NO_CHANGE,
        current_model="gpt-4o-mini",
        target_model="gpt-4o-mini",
        suggested_thresholds={"min_f1": 0.95},
    )
    md = render_markdown(result)
    assert "Kept the current prompt" in md
    assert "No action needed" in md


def test_save_report_writes_both_files(tmp_path: Path):
    result = _result(MigrationStatus.PASS, edited_files=["a.md"])
    md_path, json_path = save_report(result, cwd=tmp_path)
    assert md_path.is_file() and json_path.is_file()
    assert md_path == tmp_path / ".driftless" / "reports" / "support_classifier.md"
    assert "Model Migration" in md_path.read_text()
    assert json.loads(json_path.read_text())["target_model"] == "gpt-5-mini"


def test_summary_and_diff_sections_in_pr_body():
    result = _result(
        MigrationStatus.PASS,
        edited_files=["prompts/system.md"],
        holdout=_metrics(f1=0.991),
        holdout_checks=[ThresholdCheck("min_f1", True, "0.991 >= 0.9")],
        original_editable_files={"prompts/system.md": "old line\nkeep\n"},
        experiment_log=[
            AttemptRecord(
                0,
                "llm",
                "tighten billing rule",
                ["prompts/system.md"],
                0.95,
                0.0,
                0.0,
                True,
                True,
                diff_size=2,
                file_contents={"prompts/system.md": "old line\nkeep\n+ billing rule\n"},
            ),
        ],
    )
    md = render_markdown(result)
    assert "## Summary" in md
    assert "**Tuning F1:**" in md
    assert "## Proposed Diffs" in md
    assert "```diff" in md
    assert "+ billing rule" in md
    assert "## Full Run Data" in md
    assert ".driftless/migrations/support_classifier.json" in md


def test_partial_report_shows_best_attempt_diff():
    result = _result(
        MigrationStatus.PARTIAL,
        edited_files=[],
        original_editable_files={"prompts/p.md": "before\n"},
        experiment_log=[
            AttemptRecord(
                0,
                "llm",
                "almost worked",
                ["prompts/p.md"],
                0.88,
                0.0,
                0.0,
                False,
                False,
                file_contents={"prompts/p.md": "before\nafter fix\n"},
            ),
        ],
    )
    md = render_markdown(result)
    assert "## Best Attempt (not committed)" in md
    assert "+after fix" in md or "+after fix\n" in md


def test_alternates_section_lists_rejected_candidates():
    result = _result(
        MigrationStatus.PASS,
        edited_files=["prompts/p.md"],
        original_editable_files={"prompts/p.md": "v0\n"},
        experiment_log=[
            AttemptRecord(
                0,
                "llm",
                "weak try",
                ["prompts/p.md"],
                0.85,
                0.0,
                0.0,
                False,
                False,
                file_contents={"prompts/p.md": "v0\nweak\n"},
            ),
            AttemptRecord(
                1,
                "llm",
                "winning try",
                ["prompts/p.md"],
                0.92,
                0.0,
                0.0,
                True,
                True,
                file_contents={"prompts/p.md": "v0\nwin\n"},
            ),
        ],
    )
    md = render_markdown(result)
    assert "## Other Attempts Considered" in md
    assert "weak try" in md
    assert "Best tuning F1 by iteration" in md


def test_render_includes_judge_reliability_and_evidence():
    agreement = JudgeAgreement(n=5, mean_abs_error=0.04, correlation=0.95)
    result = _result(
        MigrationStatus.PASS,
        final=_metrics(score=0.88, f1=None),
        judge_agreement=agreement,
        judge_evidence=[
            {"index": 2, "score": 0.2, "rationale": "missing keyword"},
            {"index": 5, "score": 0.2, "rationale": "no good token"},
        ],
    )
    md = render_markdown(result)
    assert "## Judge Reliability" in md
    assert "MAE=0.040" in md
    assert "## Judge Scoring Evidence" in md
    assert "missing keyword" in md

    payload = result_to_dict(result)
    assert payload["judge_agreement"]["n"] == 5
    assert len(payload["judge_evidence"]) == 2
