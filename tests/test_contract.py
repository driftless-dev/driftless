from pathlib import Path

import pytest

from driftless.contract import Contract, Workflow, load_contract
from driftless.errors import ContractError, WorkflowNotFoundError
from driftless.templates import CONTRACT_TEMPLATE


def test_template_parses():
    contract = Contract.model_validate(__import__("yaml").safe_load(CONTRACT_TEMPLATE))
    wf = contract.workflow("my_workflow")
    assert wf.model.current == "<current-model>"
    assert wf.model.has_override()
    assert wf.eval.split.tuning == pytest.approx(0.7)
    assert wf.eval.split.holdout == pytest.approx(0.3)
    assert "allow_prompt_edits" not in CONTRACT_TEMPLATE


def test_percent_and_fraction_coercion():
    contract = Contract.model_validate(
        {
            "workflows": {
                "w": {
                    "run": {"command": "true", "input_path": "i", "output_path": "o"},
                    "model": {"current": "m", "env_var": "M"},
                    "eval": {"split": {"tuning": "80%", "holdout": 0.2}},
                }
            }
        }
    )
    wf = contract.workflow("w")
    assert wf.eval.split.tuning == pytest.approx(0.8)
    assert wf.eval.split.holdout == pytest.approx(0.2)


def test_unknown_key_rejected():
    with pytest.raises(Exception):
        Contract.model_validate(
            {
                "workflows": {
                    "w": {
                        "run": {"command": "true", "input_path": "i", "output_path": "o"},
                        "model": {"current": "m", "env_var": "M"},
                        "bogus": True,
                    }
                }
            }
        )


def test_workflow_not_found():
    contract = Contract.model_validate(
        {
            "workflows": {
                "w": {
                    "run": {"command": "true", "input_path": "i", "output_path": "o"},
                    "model": {"current": "m", "env_var": "M"},
                }
            }
        }
    )
    with pytest.raises(WorkflowNotFoundError):
        contract.workflow("missing")


def test_split_seed_count_must_be_in_range():
    with pytest.raises(Exception):
        Workflow.model_validate(
            {
                "run": {"command": "true", "input_path": "i", "output_path": "o"},
                "model": {"current": "m", "env_var": "M"},
                "migration": {"split_seed_count": 0},
            }
        )


@pytest.mark.parametrize(
    "flag",
    [
        "allow_prompt_edits",
        "allow_example_edits",
        "allow_config_edits",
        "allow_schema_edits",
        "allow_code_edits",
        "allow_business_logic_edits",
    ],
)
def test_legacy_edit_flags_explain_exact_path_policy(flag: str):
    with pytest.raises(Exception) as exc_info:
        Workflow.model_validate(
            {
                "run": {"command": "true", "input_path": "i", "output_path": "o"},
                "model": {"current": "m", "env_var": "M"},
                "migration": {flag: True},
            }
        )

    message = str(exc_info.value)
    assert f"migration.{flag}" in message
    assert "files.editable" in message
    assert "cannot be inferred reliably" in message


def test_load_missing_contract(tmp_path: Path):
    with pytest.raises(ContractError):
        load_contract(tmp_path / "nope.yml")
