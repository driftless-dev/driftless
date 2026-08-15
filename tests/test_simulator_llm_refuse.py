import re
from pathlib import Path
from shutil import copytree

import pytest
from typer.testing import CliRunner

from driftless.cli import app

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

_SIMULATORS = (
    ("support-classifier", "support_classifier"),
    ("rag-qa", "rag_qa"),
    ("tool-agent", "support_agent"),
)


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


@pytest.mark.parametrize("example,workflow", _SIMULATORS)
def test_migrate_llm_refused_on_bundled_simulator(
    tmp_path: Path,
    monkeypatch,
    example: str,
    workflow: str,
):
    work = tmp_path / example
    copytree(_EXAMPLES / example, work)
    monkeypatch.chdir(work)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = CliRunner().invoke(
        app,
        ["migrate", "-w", workflow, "--to", "gpt-4o-mini", "--generator", "llm"],
    )

    out = _plain(result.output)
    assert result.exit_code == 1, result.output
    assert "local simulator" in out
    assert "support-classifier-live" in out
    assert "--generator fixture" in out
    assert "Traceback" not in out


def test_refine_llm_refused_on_classifier_simulator(tmp_path: Path, monkeypatch):
    work = tmp_path / "support-classifier"
    copytree(_EXAMPLES / "support-classifier", work)
    monkeypatch.chdir(work)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = CliRunner().invoke(
        app,
        ["refine", "-w", "support_classifier", "--generator", "llm"],
    )

    out = _plain(result.output)
    assert result.exit_code == 1, result.output
    assert "local simulator" in out
    assert "support-classifier-live" in out
    assert "Traceback" not in out
