import os
import sys
from pathlib import Path
from shutil import copytree
from subprocess import run

import pytest
from typer.testing import CliRunner

from driftless.cli import app
from driftless.contract import load_contract
from driftless.engine import PatchContext
from driftless.errors import DriftlessError
from driftless.evaluation import Metrics
from driftless.generators import FixturePatchGenerator, _fixture_recipe

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _copy_live(tmp_path: Path) -> Path:
    work = tmp_path / "support-classifier-live"
    copytree(_EXAMPLES / "support-classifier-live", work)
    return work


def test_live_classifier_validate_no_run(tmp_path: Path, monkeypatch):
    work = _copy_live(tmp_path)
    monkeypatch.chdir(work)

    result = CliRunner().invoke(
        app,
        ["validate", "-w", "support_classifier_live", "--no-run"],
    )

    assert result.exit_code == 0, result.output


def test_live_harness_exits_cleanly_without_api_key(tmp_path: Path):
    work = _copy_live(tmp_path)
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    env.pop("ANTHROPIC_API_KEY", None)
    completed = run(
        [sys.executable, "-m", "app.eval_classifier"],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert "OPENAI_API_KEY is not set" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert "Traceback" not in completed.stdout


def test_live_classifier_fixture_generator_has_no_patch(tmp_path: Path):
    work = _copy_live(tmp_path)
    prompt = (work / "prompts" / "classifier.md").read_text(encoding="utf-8")
    assert _fixture_recipe({"prompts/classifier.md": prompt}) is None

    contract = load_contract(work / "driftless.yml")
    workflow = contract.workflow("support_classifier_live")
    ctx = PatchContext(
        workflow=workflow,
        workflow_name="support_classifier_live",
        target_model="gpt-4o-mini",
        iteration=0,
        editable_files={"prompts/classifier.md": prompt},
        baseline=Metrics(n=1, schema_error_rate=0.0, refusal_rate=0.0),
        current=Metrics(n=1, schema_error_rate=0.0, refusal_rate=0.0),
        clusters=[],
        rows=[],
    )
    with pytest.raises(DriftlessError, match="fixture generator has no patch"):
        FixturePatchGenerator().generate(ctx)
