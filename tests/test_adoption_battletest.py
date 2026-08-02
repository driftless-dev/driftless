from pathlib import Path
from shutil import copytree

from typer.testing import CliRunner

from driftless.cli import app


def test_existing_repository_adoption_journey(tmp_path: Path, monkeypatch):
    source = Path(__file__).parent / "fixtures" / "adoption-app"
    work = tmp_path / "adoption-app"
    copytree(source, work)
    monkeypatch.chdir(work)
    runner = CliRunner()

    scan = runner.invoke(app, ["scan"])
    validate = runner.invoke(app, ["validate", "-w", "incident_brief"])
    calibrate = runner.invoke(app, ["calibrate", "-w", "incident_brief"])
    compare = runner.invoke(
        app,
        [
            "compare",
            "-w",
            "incident_brief",
            "--to",
            "gpt-4o-mini",
            "--enforce",
        ],
    )
    migrate = runner.invoke(
        app,
        [
            "migrate",
            "-w",
            "incident_brief",
            "--to",
            "gpt-4o-mini",
            "--generator",
            "none",
        ],
    )
    report = runner.invoke(app, ["report", "-w", "incident_brief", "--raw"])
    delivery = runner.invoke(app, ["open-pr", "-w", "incident_brief"])
    ci = runner.invoke(
        app,
        [
            "init-ci",
            "--setup-command",
            'pip install -e ".[dev]"',
        ],
    )

    assert scan.exit_code == 0
    assert "BRIEF_MODEL" in scan.output
    assert validate.exit_code == 0, validate.output
    assert calibrate.exit_code == 0
    assert compare.exit_code == 1
    assert migrate.exit_code == 1
    assert report.exit_code == 0
    assert "**Status:** `blocked`" in report.output
    assert delivery.exit_code == 0
    assert "Dry run" in delivery.output
    assert ci.exit_code == 0

    migrate_workflow = Path(".github/workflows/driftless-model-migrate.yml").read_text()
    refine_workflow = Path(".github/workflows/driftless-prompt-refine.yml").read_text()
    assert "Set up application" in migrate_workflow
    assert "continue-on-error: true" in migrate_workflow
    assert "workflow_dispatch:" in refine_workflow
    assert "\n  push:" not in refine_workflow
