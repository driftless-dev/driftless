"""Tests for tuning/holdout splits."""

import pytest

from driftless.contract import Workflow
from driftless.errors import DriftlessError
from driftless.splits import make_splits


def _workflow(**eval_split) -> Workflow:
    split = {"tuning": 0.5, "holdout": 0.5, **eval_split}
    return Workflow.model_validate(
        {
            "run": {"command": "true", "input_path": "i.jsonl", "output_path": "o.jsonl"},
            "model": {"current": "m", "env_var": "M"},
            "eval": {"labels_path": "l.jsonl", "split": split},
        }
    )


def _write_dataset(tmp_path, n: int = 20) -> None:
    lines = "\n".join(f'{{"id": {i}, "label": "a"}}' for i in range(n)) + "\n"
    labels = "\n".join('{"id": ' + str(i) + ', "label": "a"}' for i in range(n)) + "\n"
    (tmp_path / "i.jsonl").write_text(lines)
    (tmp_path / "l.jsonl").write_text(labels)


def test_different_seeds_produce_different_partitions(tmp_path):
    _write_dataset(tmp_path)
    wf = _workflow()
    wf.eval.id_field = "id"
    a = make_splits(wf, cwd=tmp_path, seed=0)
    b = make_splits(wf, cwd=tmp_path, seed=1)
    assert a.tuning_idx != b.tuning_idx


def test_full_tuning_honors_empty_holdout(tmp_path):
    _write_dataset(tmp_path, n=4)
    wf = _workflow(tuning=1.0, holdout=0.0)
    wf.eval.id_field = "id"
    wf.migration.holdout_required = False
    split = make_splits(wf, cwd=tmp_path, seed=0)
    assert split.tuning_idx == [0, 1, 2, 3]
    assert split.holdout_idx == []


def test_full_tuning_rejected_when_holdout_required(tmp_path):
    _write_dataset(tmp_path, n=4)
    wf = _workflow(tuning=1.0, holdout=0.0)
    wf.eval.id_field = "id"
    with pytest.raises(DriftlessError, match="no holdout"):
        make_splits(wf, cwd=tmp_path, seed=0)


def test_positive_holdout_still_reserves_unseen_rows(tmp_path):
    _write_dataset(tmp_path, n=4)
    wf = _workflow(tuning=0.5, holdout=0.5)
    wf.eval.id_field = "id"
    split = make_splits(wf, cwd=tmp_path, seed=0)
    assert len(split.tuning_idx) == 2
    assert len(split.holdout_idx) == 2
    assert not set(split.tuning_idx) & set(split.holdout_idx)
