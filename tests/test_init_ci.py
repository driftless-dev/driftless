from pathlib import Path

from typer.testing import CliRunner

from driftless.cli import app
from driftless.init_ci import (
    dataset_paths,
    default_action_ref,
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
    refine = (out / "driftless-prompt-refine.yml").read_text()
    assert "data/labels.jsonl" in refine
    assert "data/inputs.jsonl" in refine
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


def test_rendered_workflows_use_action_ref():
    ref = "driftless-dev/driftless@v9.9.9"
    assert ref in render_migrate_workflow(ref)
    assert "support_classifier" in render_refine_workflow(
        ref, "support_classifier", ["data/labels.jsonl"]
    )
