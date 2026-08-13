from pathlib import Path
from shutil import copytree

import pytest
from typer.testing import CliRunner

from driftless.cli import app
from driftless.contract import load_contract
from driftless.evaluation import evaluate
from driftless.harness import run_workflow


def test_support_classifier_example_scores_baseline_and_target(tmp_path: Path):
    source = Path(__file__).resolve().parents[1] / "examples" / "support-classifier"
    work = tmp_path / "support-classifier"
    copytree(source, work)

    contract = load_contract(work / "driftless.yml")
    workflow = contract.workflow("support_classifier")

    baseline = run_workflow(workflow, "gpt-4", cwd=work)
    baseline_score = evaluate(workflow, baseline, cwd=work).f1
    target = run_workflow(workflow, "gpt-4o-mini", cwd=work)
    target_score = evaluate(workflow, target, cwd=work).f1

    assert baseline_score == pytest.approx(1.0)
    assert target_score == pytest.approx(0.0)


def test_compare_enforce_exits_nonzero_on_failed_quality_gate(
    tmp_path: Path,
    monkeypatch,
):
    source = Path(__file__).resolve().parents[1] / "examples" / "support-classifier"
    work = tmp_path / "support-classifier"
    copytree(source, work)
    monkeypatch.chdir(work)

    default = CliRunner().invoke(
        app,
        ["compare", "-w", "support_classifier", "--to", "gpt-4o-mini"],
    )
    enforced = CliRunner().invoke(
        app,
        [
            "compare",
            "-w",
            "support_classifier",
            "--to",
            "gpt-4o-mini",
            "--enforce",
        ],
    )

    assert default.exit_code == 0
    assert enforced.exit_code == 1
    assert "Naive target does not pass" in enforced.output


def test_support_classifier_fixture_generator_passes(tmp_path: Path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "examples" / "support-classifier"
    work = tmp_path / "support-classifier"
    copytree(source, work)
    monkeypatch.chdir(work)

    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "-w",
            "support_classifier",
            "--to",
            "gpt-4o-mini",
            "--generator",
            "fixture",
        ],
    )

    assert result.exit_code == 0, result.output
    prompt = (work / "prompts" / "classifier.md").read_text().lower()
    assert "use exact labels only" in prompt
    assert "billing, technical, account, shipping" in prompt
