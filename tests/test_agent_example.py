from pathlib import Path
from shutil import copytree

import pytest

from driftless.contract import load_contract
from driftless.evaluation import evaluate
from driftless.harness import run_workflow


def test_tool_agent_example_scores_baseline_and_target(tmp_path: Path):
    source = Path(__file__).resolve().parents[1] / "examples" / "tool-agent"
    work = tmp_path / "tool-agent"
    copytree(source, work)

    contract = load_contract(work / "driftless.yml")
    workflow = contract.workflow("support_agent")

    baseline = run_workflow(workflow, "gpt-4", cwd=work)
    baseline_score = evaluate(workflow, baseline, cwd=work).score
    target = run_workflow(workflow, "gpt-4o-mini", cwd=work)
    target_score = evaluate(workflow, target, cwd=work).score

    assert baseline_score == pytest.approx(1.0)
    assert target_score == pytest.approx(0.0)

