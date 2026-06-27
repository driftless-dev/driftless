from pathlib import Path

from driftless.contract import Workflow
from driftless.preflight import provider_preflight


def _wf(tmp_path: Path, *, current="gpt-4o-mini", provider=None, portable=False) -> Workflow:
    model: dict = {"current": current, "env_var": "M", "portable": portable}
    if provider:
        model["provider"] = provider
    return Workflow.model_validate(
        {
            "run": {"command": "true", "input_path": "in", "output_path": "out"},
            "model": model,
        }
    )


def test_cross_provider_swap_warns(tmp_path: Path):
    wf = _wf(tmp_path, current="gpt-4o-mini")
    pf = provider_preflight(wf, "claude-3-5-sonnet", cwd=tmp_path)
    assert pf.mismatch
    assert pf.warning is not None
    assert "claude-3-5-sonnet" in pf.warning


def test_same_provider_no_warning(tmp_path: Path):
    wf = _wf(tmp_path, current="gpt-4o-mini")
    pf = provider_preflight(wf, "gpt-4o", cwd=tmp_path)
    assert not pf.mismatch
    assert pf.warning is None


def test_portable_flag_suppresses_warning(tmp_path: Path):
    wf = _wf(tmp_path, current="gpt-4o-mini", portable=True)
    pf = provider_preflight(wf, "claude-3-5-sonnet", cwd=tmp_path)
    assert pf.mismatch  # providers still differ...
    assert pf.portable
    assert pf.warning is None  # ...but routing is portable


def test_detected_portability_suppresses_warning(tmp_path: Path):
    (tmp_path / "app.py").write_text("import litellm\nlitellm.completion(model=m)\n")
    wf = _wf(tmp_path, current="gpt-4o-mini")
    pf = provider_preflight(wf, "claude-3-5-sonnet", cwd=tmp_path)
    assert pf.portable
    assert pf.warning is None


def test_unknown_target_provider_no_warning(tmp_path: Path):
    wf = _wf(tmp_path, current="gpt-4o-mini")
    pf = provider_preflight(wf, "llama-3-70b", cwd=tmp_path)
    assert pf.warning is None  # can't infer target provider -> don't cry wolf
