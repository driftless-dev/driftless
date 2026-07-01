from pathlib import Path

from typer.testing import CliRunner

from driftless.cli import app
from driftless.init_ci import (
    dataset_paths,
    default_action_ref,
    judge_check_targets,
    label_audit_paths,
    label_audit_workflows,
    render_audit_labels_workflow,
    render_judge_check_workflow,
    render_migrate_workflow,
    render_refine_workflow,
)

runner = CliRunner()


def test_init_ci_scaffolds_workflows(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("driftless.yml").write_text(
        """
version: 1
workflows:
  support_classifier:
    run:
      command: echo ok
      input_path: data/inputs.jsonl
      output_path: .driftless/out.jsonl
    model:
      current: gpt-4o-mini
      env_var: MODEL
    eval:
      labels_path: data/labels.jsonl
""".lstrip()
    )
    out = tmp_path / ".github" / "workflows"
    result = runner.invoke(app, ["init-ci", "--out-dir", str(out)])

    assert result.exit_code == 0
    assert (out / "driftless-model-scan.yml").is_file()
    assert (out / "driftless-model-migrate.yml").is_file()
    assert (out / "driftless-prompt-refine.yml").is_file()
    assert (out / "driftless-label-audit.yml").is_file()
    refine = (out / "driftless-prompt-refine.yml").read_text()
    audit = (out / "driftless-label-audit.yml").read_text()
    assert "data/labels.jsonl" in refine
    assert "data/inputs.jsonl" in refine
    assert "data/labels.jsonl" in audit
    assert "audit-labels" in audit
    assert '--fail' in audit or '"--fail"' in audit
    assert default_action_ref() in refine
    assert "OPENAI_API_KEY" in result.output


def test_init_ci_poll_when_data_source(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("driftless.yml").write_text(
        """
version: 1
workflows:
  rag:
    run:
      command: echo ok
      input_path: data/inputs.jsonl
      output_path: .driftless/out.jsonl
    model:
      current: gpt-4o-mini
      env_var: MODEL
    eval:
      labels_path: data/labels.jsonl
      data_source:
        labels_url: https://example.com/labels.jsonl
""".lstrip()
    )
    out = tmp_path / "workflows"
    result = runner.invoke(app, ["init-ci", "--out-dir", str(out), "--no-refine"])

    assert result.exit_code == 0
    assert (out / "driftless-prompt-refine-poll.yml").is_file()


def test_init_ci_refuses_overwrite_without_force(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("driftless.yml").write_text(
        """
version: 1
workflows:
  smoke:
    run:
      command: echo ok
      input_path: in.jsonl
      output_path: out.jsonl
    model:
      current: gpt-4o-mini
      env_var: MODEL
    eval:
      labels_path: labels.jsonl
""".lstrip()
    )
    out = tmp_path / "workflows"
    assert runner.invoke(app, ["init-ci", "--out-dir", str(out)]).exit_code == 0
    retry = runner.invoke(app, ["init-ci", "--out-dir", str(out)])
    assert retry.exit_code == 1
    assert "already exists" in retry.output


def test_dataset_paths_dedupes():
    from driftless.contract import Contract

    contract = Contract.model_validate(
        {
            "version": 1,
            "workflows": {
                "w": {
                    "run": {
                        "command": "x",
                        "input_path": "data/x.jsonl",
                        "output_path": "out.jsonl",
                    },
                    "model": {"current": "gpt-4o-mini", "env_var": "M"},
                    "eval": {"labels_path": "data/x.jsonl"},
                }
            },
        }
    )
    wf = contract.workflows["w"]
    assert dataset_paths(wf) == ["data/x.jsonl"]


def test_init_ci_skips_audit_for_judge_graded_workflow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("driftless.yml").write_text(
        """
version: 1
workflows:
  summarizer:
    run:
      command: echo ok
      input_path: data/inputs.jsonl
      output_path: .driftless/out.jsonl
    model:
      current: gpt-4o-mini
      env_var: MODEL
    eval:
      judge:
        rubric: "Score quality."
""".lstrip()
    )
    out = tmp_path / "workflows"
    result = runner.invoke(app, ["init-ci", "--out-dir", str(out), "--no-refine"])

    assert result.exit_code == 0
    assert not any(p.name.startswith("driftless-label-audit") for p in out.iterdir())


def test_init_ci_audit_matrix_for_multiple_workflows(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("driftless.yml").write_text(
        """
version: 1
workflows:
  alpha:
    run:
      command: echo ok
      input_path: data/a-in.jsonl
      output_path: .driftless/a-out.jsonl
    model:
      current: gpt-4o-mini
      env_var: MODEL
    eval:
      labels_path: data/a-labels.jsonl
  beta:
    run:
      command: echo ok
      input_path: data/b-in.jsonl
      output_path: .driftless/b-out.jsonl
    model:
      current: gpt-4o-mini
      env_var: MODEL
    eval:
      labels_path: data/b-labels.jsonl
""".lstrip()
    )
    out = tmp_path / "workflows"
    result = runner.invoke(
        app, ["init-ci", "--out-dir", str(out), "--no-scan", "--no-migrate"]
    )

    assert result.exit_code == 0
    audit = (out / "driftless-label-audit-all.yml").read_text()
    assert "matrix:" in audit
    assert "'alpha'" in audit or '"alpha"' in audit
    assert "'beta'" in audit or '"beta"' in audit
    assert "data/a-labels.jsonl" in audit
    assert "data/b-labels.jsonl" in audit


def test_init_ci_judge_check_when_calibration_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("driftless.yml").write_text(
        """
version: 1
workflows:
  summarizer:
    run:
      command: echo ok
      input_path: data/in.jsonl
      output_path: data/out.jsonl
    model:
      current: gpt-4o-mini
      env_var: MODEL
    eval:
      judge:
        rubric: "Score summary quality."
        calibration_path: data/calib.jsonl
        max_mae: 0.15
""".lstrip()
    )
    out = tmp_path / "workflows"
    result = runner.invoke(
        app, ["init-ci", "--out-dir", str(out), "--no-scan", "--no-migrate", "--no-refine"]
    )

    assert result.exit_code == 0
    judge = (out / "driftless-judge-check.yml").read_text()
    assert "judge-check" in judge
    assert "data/calib.jsonl" in judge
    assert "--enforce" in judge
    assert "OPENAI_API_KEY" in judge


def test_init_ci_skips_judge_check_without_calibration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("driftless.yml").write_text(
        """
version: 1
workflows:
  summarizer:
    run:
      command: echo ok
      input_path: data/in.jsonl
      output_path: data/out.jsonl
    model:
      current: gpt-4o-mini
      env_var: MODEL
    eval:
      judge:
        rubric: "Score summary quality."
""".lstrip()
    )
    out = tmp_path / "workflows"
    result = runner.invoke(
        app,
        ["init-ci", "--out-dir", str(out), "--no-scan", "--no-migrate", "--no-refine", "--no-audit-labels"],
    )

    assert result.exit_code == 1
    assert "nothing to scaffold" in result.output


def test_label_audit_helpers():
    from driftless.contract import Contract

    contract = Contract.model_validate(
        {
            "version": 1,
            "workflows": {
                "cls": {
                    "run": {
                        "command": "x",
                        "input_path": "in.jsonl",
                        "output_path": "out.jsonl",
                    },
                    "model": {"current": "gpt-4o-mini", "env_var": "M"},
                    "eval": {"labels_path": "labels.jsonl"},
                },
                "sum": {
                    "run": {
                        "command": "x",
                        "input_path": "in2.jsonl",
                        "output_path": "out2.jsonl",
                    },
                    "model": {"current": "gpt-4o-mini", "env_var": "M"},
                    "eval": {"judge": {"rubric": "ok"}},
                },
            },
        }
    )
    assert label_audit_workflows(contract) == ["cls"]
    assert label_audit_paths(contract) == ["labels.jsonl", "in.jsonl"]


def test_rendered_workflows_use_action_ref():
    ref = "driftless-dev/driftless@v9.9.9"
    assert ref in render_migrate_workflow(ref)
    assert "support_classifier" in render_refine_workflow(
        ref, "support_classifier", ["data/labels.jsonl"]
    )
    audit = render_audit_labels_workflow(ref, ["support_classifier"], ["data/labels.jsonl"])
    assert ref in audit
    assert "audit-labels" in audit
    assert "--fail" in audit
    from driftless.init_ci import JudgeCheckTarget

    judge = render_judge_check_workflow(
        ref,
        [JudgeCheckTarget("summarizer", "data/calib.jsonl", True)],
        ["data/calib.jsonl"],
    )
    assert "judge-check" in judge
    assert "--enforce" in judge
