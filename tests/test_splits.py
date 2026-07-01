"""Tests for tuning/holdout splits."""

from driftless.contract import Workflow
from driftless.splits import make_splits


def _workflow() -> Workflow:
    return Workflow.model_validate(
        {
            "run": {"command": "true", "input_path": "i.jsonl", "output_path": "o.jsonl"},
            "model": {"current": "m", "env_var": "M"},
            "eval": {"labels_path": "l.jsonl", "split": {"tuning": 0.5, "holdout": 0.5}},
        }
    )


def test_different_seeds_produce_different_partitions(tmp_path):
    lines = "\n".join(f'{{"id": {i}, "label": "a"}}' for i in range(20)) + "\n"
    labels = "\n".join('{"id": ' + str(i) + ', "label": "a"}' for i in range(20)) + "\n"
    (tmp_path / "i.jsonl").write_text(lines)
    (tmp_path / "l.jsonl").write_text(labels)

    wf = _workflow()
    wf.eval.id_field = "id"
    a = make_splits(wf, cwd=tmp_path, seed=0)
    b = make_splits(wf, cwd=tmp_path, seed=1)
    assert a.tuning_idx != b.tuning_idx
