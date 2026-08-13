from pathlib import Path
from shutil import copytree

import pytest
from typer.testing import CliRunner

from driftless.cli import app
from driftless.contract import load_contract
from driftless.evaluation import evaluate
from driftless.harness import run_workflow


def test_rag_qa_example_scores_baseline_and_target(tmp_path: Path):
    source = Path(__file__).resolve().parents[1] / "examples" / "rag-qa"
    work = tmp_path / "rag-qa"
    copytree(source, work)

    contract = load_contract(work / "driftless.yml")
    workflow = contract.workflow("rag_qa")

    baseline = run_workflow(workflow, "gpt-4", cwd=work)
    baseline_score = evaluate(workflow, baseline, cwd=work).score
    target = run_workflow(workflow, "gpt-4o-mini", cwd=work)
    target_score = evaluate(workflow, target, cwd=work).score

    assert baseline_score == pytest.approx(1.0)
    assert target_score == pytest.approx(0.0)


def test_rag_qa_fixture_generator_passes(tmp_path: Path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "examples" / "rag-qa"
    work = tmp_path / "rag-qa"
    copytree(source, work)
    monkeypatch.chdir(work)

    result = CliRunner().invoke(
        app,
        ["migrate", "-w", "rag_qa", "--to", "gpt-4o-mini", "--generator", "fixture"],
    )

    assert result.exit_code == 0, result.output
    answer = (work / "prompts" / "rag_answer.md").read_text().lower()
    rewrite = (work / "prompts" / "retrieval_rewrite.md").read_text().lower()
    assert "use only retrieved context" in answer
    assert "preserve product nouns" in rewrite
