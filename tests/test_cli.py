import json
from pathlib import Path

from typer.testing import CliRunner

from driftless import github
from driftless.cli import app


runner = CliRunner()


def test_cli_version():
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert "driftless" in result.output


def test_init_scaffolds_contract(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--path", "driftless.yml"])

    assert result.exit_code == 0
    assert Path("driftless.yml").is_file()
    assert "support_classifier" in Path("driftless.yml").read_text()


def test_init_policy_scaffolds_policy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init-policy"])

    assert result.exit_code == 0
    assert Path(".driftless/policy.yml").is_file()
    assert "deprecation" in Path(".driftless/policy.yml").read_text()


def test_validate_no_run_accepts_minimal_contract(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("inputs.jsonl").write_text('{"id": "1", "text": "hello"}\n')
    Path("driftless.yml").write_text(
        """
version: 1
workflows:
  smoke:
    run:
      command: python -c "print('not run')"
      input_path: inputs.jsonl
      output_path: .driftless/results/smoke.outputs.jsonl
    model:
      current: gpt-4o-mini
      env_var: SMOKE_MODEL
""".lstrip()
    )

    result = runner.invoke(
        app,
        ["validate", "--workflow", "smoke", "--contract", "driftless.yml", "--no-run"],
    )

    assert result.exit_code == 0
    assert "contract ok" in result.output
    assert "skipping harness run" in result.output


def test_scan_reports_detected_model(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("app.py").write_text('from openai import OpenAI\nMODEL = "gpt-4o-mini"\n')

    result = runner.invoke(app, ["scan", "."])

    assert result.exit_code == 0
    assert "Probable LLM workflows" in result.output
    assert "gpt-4o-mini" in result.output


def test_open_pr_dry_run_reads_migration_artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".driftless" / "migrations").mkdir(parents=True)
    (tmp_path / ".driftless" / "reports").mkdir(parents=True)
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "system.md").write_text("prompt\n")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "llm.yml").write_text(
        "workflows:\n  support_classifier:\n    model: gpt-4o-mini\n"
    )
    Path("driftless.yml").write_text(
        """
version: 1
workflows:
  support_classifier:
    run:
      command: "python -c pass"
      input_path: inputs.jsonl
      output_path: outputs.jsonl
    model:
      current: gpt-4o-mini
      target_candidates: [gpt-5-mini]
      config_file: config/llm.yml
      config_path: workflows.support_classifier.model
    eval:
      labels_path: labels.jsonl
""".lstrip()
    )
    migration = {
        "workflow": "support_classifier",
        "current_model": "gpt-4o-mini",
        "target_model": "gpt-5-mini",
        "status": "pass",
        "succeeded": True,
        "edited_files": ["prompts/system.md"],
    }
    Path(".driftless/migrations/support_classifier.json").write_text(json.dumps(migration))
    Path(".driftless/reports/support_classifier.md").write_text("# Migration report\n")

    result = runner.invoke(app, ["open-pr", "-w", "support_classifier"])

    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert "create branch" in result.output
    assert "re-run with --create" in result.output


def test_open_pr_create_invokes_execute_plan(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".driftless" / "migrations").mkdir(parents=True)
    (tmp_path / ".driftless" / "reports").mkdir(parents=True)
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "system.md").write_text("prompt\n")
    Path("driftless.yml").write_text(
        """
version: 1
workflows:
  support_classifier:
    run:
      command: "python -c pass"
      input_path: inputs.jsonl
      output_path: outputs.jsonl
    model:
      current: gpt-4o-mini
      env_var: SUPPORT_CLASSIFIER_MODEL
    eval:
      labels_path: labels.jsonl
""".lstrip()
    )
    migration = {
        "workflow": "support_classifier",
        "current_model": "gpt-4o-mini",
        "target_model": "gpt-5-mini",
        "status": "pass",
        "succeeded": True,
        "edited_files": ["prompts/system.md"],
    }
    Path(".driftless/migrations/support_classifier.json").write_text(json.dumps(migration))
    Path(".driftless/reports/support_classifier.md").write_text("# report\n")

    seen: dict = {}

    def fake_execute(plan, *, cwd, create, push, dedupe):
        seen.update(create=create, push=push, dedupe=dedupe, kind=plan.kind, title=plan.title)
        return ["create branch: x", "PR created"]

    monkeypatch.setattr(github, "execute_plan", fake_execute)

    result = runner.invoke(
        app,
        ["open-pr", "-w", "support_classifier", "--create", "--no-push", "--no-dedupe"],
    )

    assert result.exit_code == 0
    assert seen == {
        "create": True,
        "push": False,
        "dedupe": False,
        "kind": "pr",
        "title": "chore: migrate support_classifier from gpt-4o-mini to gpt-5-mini",
    }
    assert "Creating" in result.output
    assert "PR created" in result.output
