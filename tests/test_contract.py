from pathlib import Path

import pytest

from driftless.contract import Contract, load_contract
from driftless.errors import ContractError, WorkflowNotFoundError
from driftless.templates import CONTRACT_TEMPLATE


def test_template_parses():
    contract = Contract.model_validate(__import__("yaml").safe_load(CONTRACT_TEMPLATE))
    wf = contract.workflow("support_classifier")
    assert wf.model.current == "gpt-4o-mini"
    assert wf.model.has_override()
    assert wf.eval.split.tuning == pytest.approx(0.7)
    assert wf.eval.split.holdout == pytest.approx(0.3)


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


def test_load_missing_contract(tmp_path: Path):
    with pytest.raises(ContractError):
        load_contract(tmp_path / "nope.yml")
