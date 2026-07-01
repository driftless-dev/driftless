"""Tests for eval label auditing (P6.1)."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from driftless.cli import app
from driftless.contract import Workflow
from driftless.errors import DriftlessError
from driftless.label_audit import audit_labels, format_audit_report

runner = CliRunner()


def _write_classification_workflow(tmp_path: Path) -> None:
    inputs = [
        {"id": "a", "text": "Please refund my order"},
        {"id": "b", "text": "please refund my order"},
        {"id": "c", "text": "I forgot my password"},
        {"id": "d", "text": "I forgot my  password"},
    ]
    labels = [
        {"id": "a", "category": "refund"},
        {"id": "b", "category": "billing"},
        {"id": "c", "category": "account"},
        {"id": "d", "category": "technical"},
    ]
    (tmp_path / "inputs.jsonl").write_text(
        "\n".join(json.dumps(x) for x in inputs) + "\n", encoding="utf-8"
    )
    (tmp_path / "labels.jsonl").write_text(
        "\n".join(json.dumps(x) for x in labels) + "\n", encoding="utf-8"
    )
    (tmp_path / "driftless.yml").write_text(
        """
version: 1
workflows:
  ticket_classifier:
    run:
      command: "python -c pass"
      input_path: inputs.jsonl
      output_path: outputs.jsonl
    model:
      current: old
      env_var: MODEL
    eval:
      labels_path: labels.jsonl
      label_field: category
      id_field: id
""".lstrip(),
        encoding="utf-8",
    )


def _workflow(tmp_path: Path) -> Workflow:
    return Workflow.model_validate(
        {
            "run": {"command": "true", "input_path": "inputs.jsonl", "output_path": "o.jsonl"},
            "model": {"current": "m", "env_var": "M"},
            "eval": {
                "labels_path": "labels.jsonl",
                "label_field": "category",
                "id_field": "id",
            },
        }
    )


def test_audit_finds_exact_duplicate_label_conflicts(tmp_path: Path):
    _write_classification_workflow(tmp_path)
    report = audit_labels("ticket_classifier", _workflow(tmp_path), cwd=tmp_path)
    assert report.n_records == 4
    assert len(report.exact_conflicts) == 2
    refund_group = next(g for g in report.exact_conflicts if "refund" in g.labels)
    assert set(refund_group.labels) == {"refund", "billing"}


def test_audit_finds_near_duplicate_conflicts(tmp_path: Path):
    _write_classification_workflow(tmp_path)
    inputs = [
        {"id": "a", "text": "Please refund my order"},
        {"id": "b", "text": "please refund my order"},
        {"id": "c", "text": "I forgot my password please help"},
        {"id": "d", "text": "I forgot password please help"},
    ]
    (tmp_path / "inputs.jsonl").write_text(
        "\n".join(json.dumps(x) for x in inputs) + "\n", encoding="utf-8"
    )
    report = audit_labels(
        "ticket_classifier", _workflow(tmp_path), cwd=tmp_path, near_threshold=0.7
    )
    assert any(g.kind == "near_duplicate" for g in report.conflict_groups)


def test_audit_clean_dataset_reports_no_conflicts(tmp_path: Path):
    (tmp_path / "inputs.jsonl").write_text(
        "\n".join(
            json.dumps({"id": f"t{i}", "text": f"unique ticket {i}"})
            for i in range(4)
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "labels.jsonl").write_text(
        "\n".join(
            json.dumps({"id": f"t{i}", "category": "billing"}) for i in range(4)
        )
        + "\n",
        encoding="utf-8",
    )
    wf = Workflow.model_validate(
        {
            "run": {"command": "true", "input_path": "inputs.jsonl", "output_path": "o.jsonl"},
            "model": {"current": "m", "env_var": "M"},
            "eval": {
                "labels_path": "labels.jsonl",
                "label_field": "category",
                "id_field": "id",
            },
        }
    )
    report = audit_labels("wf", wf, cwd=tmp_path)
    assert not report.has_conflicts
    assert "No duplicate" in format_audit_report(report)


def test_audit_rejects_non_classification_workflows(tmp_path: Path):
    wf = Workflow.model_validate(
        {
            "run": {"command": "true", "input_path": "i", "output_path": "o"},
            "model": {"current": "m", "env_var": "M"},
            "eval": {"score_field": "score"},
        }
    )
    with pytest.raises(DriftlessError, match="classification"):
        audit_labels("wf", wf, cwd=tmp_path)


def test_cli_audit_labels_fail_exit_code(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_classification_workflow(tmp_path)
    ok = runner.invoke(app, ["audit-labels", "-w", "ticket_classifier"])
    assert ok.exit_code == 0
    assert "Exact duplicates" in ok.output

    failed = runner.invoke(
        app, ["audit-labels", "-w", "ticket_classifier", "--fail"]
    )
    assert failed.exit_code == 1


def test_migrate_strict_label_audit_blocks_before_engine(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_classification_workflow(tmp_path)
    Path("driftless.yml").write_text(
        Path("driftless.yml").read_text()
        + """
    thresholds:
      min_f1: 0.9
    migration:
      max_iterations: 1
      holdout_required: false
""",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "migrate",
            "-w",
            "ticket_classifier",
            "--to",
            "new-model",
            "--generator",
            "none",
            "--strict-label-audit",
        ],
    )
    assert result.exit_code == 1
    assert "Exact duplicates" in result.output
    assert "Migrating" not in result.output
