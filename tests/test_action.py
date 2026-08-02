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

    assert install["env"]["INPUT_COMMAND"] == "${{ inputs.command }}"
    assert install["env"]["INPUT_VERSION"] == "${{ inputs.version }}"
    assert run["env"]["INPUT_COMMAND"] == "${{ inputs.command }}"
    assert run["env"]["INPUT_WORKFLOW"] == "${{ inputs.workflow }}"
    assert run["env"]["INPUT_TO"] == "${{ inputs.to }}"
    assert run["env"]["INPUT_ARGS"] == "${{ inputs.args }}"
    assert "${{ inputs." not in install["run"]
    assert "${{ inputs." not in run["run"]


def test_action_installs_llm_extra_for_provider_backed_commands():
    install_script = _steps()["Install driftless"]["run"]

    assert 'plan|migrate|refine|poll|judge-check) package="driftless[llm]"' in install_script
    assert 'pip install -e ".[llm]"' in install_script
    assert 'pip install "${package}${INPUT_VERSION}"' in install_script


def test_action_uses_node_24_compatible_python_setup():
    setup = _steps()["Set up Python"]

    assert setup["uses"] == "actions/setup-python@v6"


def test_action_validates_command_and_parses_args_without_eval():
    run_script = _steps()["Run driftless"]["run"]

    assert 'case "$INPUT_COMMAND" in' in run_script
    assert "shlex.split" in run_script
    assert "eval " not in run_script
    assert 'cmd+=(--workflow "$INPUT_WORKFLOW")' in run_script
    assert 'cmd+=(--to "$INPUT_TO")' in run_script
    assert '"${cmd[@]}"' in run_script
