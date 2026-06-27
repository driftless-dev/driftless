from pathlib import Path

import pytest

from driftless.contract import Workflow
from driftless.errors import HarnessError
from driftless.harness import check_inputs, run_workflow


def _workflow(command: str, output_path: str = "out/results.jsonl") -> Workflow:
    return Workflow.model_validate(
        {
            "run": {
                "command": command,
                "input_path": "inputs.jsonl",
                "output_path": output_path,
            },
            "model": {"current": "model-a", "env_var": "MY_MODEL"},
        }
    )


def test_run_workflow_injects_model_and_captures_output(tmp_path: Path):
    (tmp_path / "inputs.jsonl").write_text("{}\n")
    # The command echoes the injected model into the output file.
    wf = _workflow('mkdir -p out && printf "%s" "$MY_MODEL" > out/results.jsonl')

    result = run_workflow(wf, "model-b", cwd=tmp_path)

    assert result.ok
    assert result.env_overrides == {"MY_MODEL": "model-b"}
    assert (tmp_path / "out/results.jsonl").read_text() == "model-b"


def test_run_workflow_substitutes_cli_arg(tmp_path: Path):
    wf = _workflow('mkdir -p out && printf "%s" "{{ model }}" > out/results.jsonl')
    result = run_workflow(wf, "gpt-x", cwd=tmp_path)
    assert (tmp_path / "out/results.jsonl").read_text() == "gpt-x"
    assert result.ok


def test_run_workflow_raises_on_nonzero_exit(tmp_path: Path):
    wf = _workflow("exit 3")
    with pytest.raises(HarnessError):
        run_workflow(wf, "model-b", cwd=tmp_path)


def test_run_workflow_raises_when_no_output(tmp_path: Path):
    wf = _workflow("true")  # succeeds but writes nothing
    with pytest.raises(HarnessError):
        run_workflow(wf, "model-b", cwd=tmp_path)


def test_run_workflow_nonzero_exit_hint_carries_stderr(tmp_path: Path):
    (tmp_path / "inputs.jsonl").write_text("{}\n")
    wf = _workflow("echo boom-on-stderr >&2; exit 1")
    with pytest.raises(HarnessError) as ei:
        run_workflow(wf, "model-b", cwd=tmp_path)
    assert "boom-on-stderr" in (ei.value.hint or "")


def test_run_workflow_times_out(tmp_path: Path):
    (tmp_path / "inputs.jsonl").write_text("{}\n")
    wf = Workflow.model_validate(
        {
            "run": {
                "command": "sleep 5",
                "input_path": "inputs.jsonl",
                "output_path": "out.jsonl",
                "timeout_seconds": 1,
            },
            "model": {"current": "m", "env_var": "MY_MODEL"},
        }
    )
    with pytest.raises(HarnessError, match="timed out"):
        run_workflow(wf, "m", cwd=tmp_path)


def test_run_workflow_removes_stale_output_before_running(tmp_path: Path):
    # A previous run's output must never be mistaken for this run's: if the new
    # command writes nothing, the stale file is gone and the harness errors.
    (tmp_path / "inputs.jsonl").write_text("{}\n")
    (tmp_path / "out").mkdir()
    stale = tmp_path / "out" / "results.jsonl"
    stale.write_text("STALE-PREVIOUS-RUN")
    wf = _workflow("true")  # writes nothing this run
    with pytest.raises(HarnessError):
        run_workflow(wf, "model-b", cwd=tmp_path)
    assert not stale.exists()


def test_run_workflow_requires_override(tmp_path: Path):
    wf = Workflow.model_validate(
        {
            "run": {"command": "true", "input_path": "i", "output_path": "o"},
            "model": {"current": "m"},  # no env_var
        }
    )
    with pytest.raises(HarnessError):
        run_workflow(wf, "m", cwd=tmp_path)


def test_check_inputs_missing(tmp_path: Path):
    wf = _workflow("true")
    with pytest.raises(HarnessError):
        check_inputs(wf, cwd=tmp_path)
