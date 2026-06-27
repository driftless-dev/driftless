from pathlib import Path

from typer.testing import CliRunner

from driftless.cli import app


runner = CliRunner()


def test_cli_version():
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert "driftless" in result.output


def test_init_scaffolds_contract():
    with runner.isolated_filesystem():
        result = runner.invoke(app, ["init", "--path", "driftless.yml"])

        assert result.exit_code == 0
        assert Path("driftless.yml").is_file()
        assert "support_classifier" in Path("driftless.yml").read_text()


def test_init_policy_scaffolds_policy():
    with runner.isolated_filesystem():
        result = runner.invoke(app, ["init-policy"])

        assert result.exit_code == 0
        assert Path(".driftless/policy.yml").is_file()
        assert "deprecation" in Path(".driftless/policy.yml").read_text()


def test_validate_no_run_accepts_minimal_contract():
    with runner.isolated_filesystem():
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


def test_scan_reports_detected_model():
    with runner.isolated_filesystem():
        Path("app.py").write_text(
            'from openai import OpenAI\nMODEL = "gpt-4o-mini"\n'
        )

        result = runner.invoke(app, ["scan", "."])

        assert result.exit_code == 0
        assert "Probable LLM workflows" in result.output
        assert "gpt-4o-mini" in result.output

