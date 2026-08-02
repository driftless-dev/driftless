from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _steps() -> dict[str, dict]:
    action = yaml.safe_load((ROOT / "action.yml").read_text())
    return {step["name"]: step for step in action["runs"]["steps"]}


def test_action_inputs_reach_shell_only_through_environment():
    steps = _steps()
    install = steps["Install driftless"]
    run = steps["Run driftless"]

    assert install["env"]["INPUT_VERSION"] == "${{ inputs.version }}"
    assert run["env"]["INPUT_COMMAND"] == "${{ inputs.command }}"
    assert run["env"]["INPUT_WORKFLOW"] == "${{ inputs.workflow }}"
    assert run["env"]["INPUT_TO"] == "${{ inputs.to }}"
    assert run["env"]["INPUT_ARGS"] == "${{ inputs.args }}"
    assert "${{ inputs." not in install["run"]
    assert "${{ inputs." not in run["run"]


def test_action_validates_command_and_parses_args_without_eval():
    run_script = _steps()["Run driftless"]["run"]

    assert 'case "$INPUT_COMMAND" in' in run_script
    assert "shlex.split" in run_script
    assert "eval " not in run_script
    assert 'cmd+=(--workflow "$INPUT_WORKFLOW")' in run_script
    assert 'cmd+=(--to "$INPUT_TO")' in run_script
    assert '"${cmd[@]}"' in run_script
