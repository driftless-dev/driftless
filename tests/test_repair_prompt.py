from pathlib import Path

import pytest

from driftless.contract import RepairSpec, Workflow
from driftless.engine import PatchContext
from driftless.errors import DriftlessError
from driftless.evaluation import Metrics
from driftless.generators import (
    _SYSTEM_PROMPT,
    resolve_system_prompt,
    resolve_user_prompt,
)


def _context(tmp_path: Path, repair: dict | None = None) -> PatchContext:
    wf = Workflow.model_validate(
        {
            "run": {"command": "true", "input_path": "i", "output_path": "o"},
            "model": {"current": "m", "env_var": "M"},
            "files": {"editable": ["prompt.txt"]},
            **({"repair": repair} if repair else {}),
        }
    )
    m = Metrics(n=2, schema_error_rate=0.1, refusal_rate=0.0, f1=0.5)
    return PatchContext(
        workflow=wf,
        workflow_name="demo",
        target_model="weak",
        iteration=0,
        editable_files={"prompt.txt": "hello"},
        baseline=m,
        current=m,
        clusters=[],
        rows=[],
        cwd=tmp_path,
    )


def test_default_system_prompt(tmp_path: Path):
    assert resolve_system_prompt(RepairSpec(), tmp_path) == _SYSTEM_PROMPT


def test_inline_system_prompt_and_guidance(tmp_path: Path):
    spec = RepairSpec(system_prompt="BASE RULES", guidance="never label refunds as billing")
    out = resolve_system_prompt(spec, tmp_path)
    assert out.startswith("BASE RULES")
    assert "never label refunds as billing" in out


def test_guidance_appends_to_default(tmp_path: Path):
    spec = RepairSpec(guidance="single-line JSON")
    out = resolve_system_prompt(spec, tmp_path)
    assert out.startswith(_SYSTEM_PROMPT)
    assert "single-line JSON" in out


def test_system_prompt_path(tmp_path: Path):
    (tmp_path / "sys.md").write_text("FROM FILE")
    spec = RepairSpec(system_prompt_path="sys.md")
    assert resolve_system_prompt(spec, tmp_path) == "FROM FILE"


def test_system_prompt_inline_beats_path(tmp_path: Path):
    (tmp_path / "sys.md").write_text("FROM FILE")
    spec = RepairSpec(system_prompt="INLINE", system_prompt_path="sys.md")
    assert resolve_system_prompt(spec, tmp_path) == "INLINE"


def test_missing_prompt_file_raises(tmp_path: Path):
    spec = RepairSpec(system_prompt_path="nope.md")
    with pytest.raises(DriftlessError):
        resolve_system_prompt(spec, tmp_path)


def test_default_user_prompt_when_no_template(tmp_path: Path):
    ctx = _context(tmp_path)
    user = resolve_user_prompt(ctx, ctx.workflow.repair)
    assert "MIGRATION STATE" in user


def test_user_template_substitution(tmp_path: Path):
    ctx = _context(
        tmp_path,
        repair={"user_template": "WF={{workflow}} TARGET={{target_model}} FILES={{editable_files}} UNKNOWN={{nope}}"},
    )
    user = resolve_user_prompt(ctx, ctx.workflow.repair)
    assert "WF=demo" in user
    assert "TARGET=weak" in user
    assert "prompt.txt" in user  # editable_files JSON substituted
    assert "{{nope}}" in user  # unknown placeholder left intact


def test_user_template_from_file(tmp_path: Path):
    (tmp_path / "u.md").write_text("clusters: {{failure_clusters}}")
    ctx = _context(tmp_path, repair={"user_template_path": "u.md"})
    user = resolve_user_prompt(ctx, ctx.workflow.repair)
    assert user.startswith("clusters: [")
