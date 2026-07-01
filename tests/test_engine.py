import json
import sys
from pathlib import Path

import pytest

from driftless.contract import Workflow
from driftless.engine import (
    MigrationStatus,
    Patch,
    apply_files,
    assess_split_sizes,
    cluster_failures,
    run_migration,
    validate_patch_scope,
)
from driftless.evaluation import RecordRow

# A demo workflow whose target-model behavior depends on the editable prompt.
RUN_PY = """\
import os, json, pathlib
model = os.environ["DEMO_MODEL"]
prompt = pathlib.Path("prompt.txt").read_text() if pathlib.Path("prompt.txt").exists() else ""
out = pathlib.Path(".driftless/results/out.jsonl")
out.parent.mkdir(parents=True, exist_ok=True)
lines = [l for l in pathlib.Path("inputs.jsonl").read_text().splitlines() if l.strip()]
with out.open("w") as f:
    for l in lines:
        gold = json.loads(l)["label"]
        if model == "good" or "STRICT" in prompt:
            pred = gold
        elif "GUESS" in prompt:
            pred = "billing"
        else:
            pred = None
        f.write(json.dumps({"label": pred}) + "\\n")
"""

INPUTS = [
    {"label": "billing"},
    {"label": "technical"},
    {"label": "refund"},
    {"label": "billing"},
    {"label": "technical"},
    {"label": "refund"},
]


def _make_workflow(tmp_path: Path, *, current="good", min_f1=0.9) -> Workflow:
    (tmp_path / "run.py").write_text(RUN_PY)
    (tmp_path / "inputs.jsonl").write_text(
        "\n".join(json.dumps(x) for x in INPUTS) + "\n"
    )
    (tmp_path / "labels.jsonl").write_text(
        "\n".join(json.dumps(x["label"]) for x in INPUTS) + "\n"
    )
    return Workflow.model_validate(
        {
            "run": {
                "command": f"{sys.executable} run.py",
                "input_path": "inputs.jsonl",
                "output_path": ".driftless/results/out.jsonl",
            },
            "model": {"current": current, "env_var": "DEMO_MODEL", "target_candidates": ["weak"]},
            "files": {"editable": ["prompt.txt"]},
            "eval": {"labels_path": "labels.jsonl"},
            "thresholds": {"min_f1": min_f1},
            "migration": {"max_iterations": 5, "holdout_required": True},
        }
    )


class StrictGen:
    def generate(self, ctx):
        return [Patch(files={"prompt.txt": "STRICT: echo the exact label."}, rationale="strict")]


class GuessGen:
    def generate(self, ctx):
        return [Patch(files={"prompt.txt": "GUESS billing"}, rationale="guess")]


def test_migration_pass_commits_files(tmp_path: Path):
    wf = _make_workflow(tmp_path)
    result = run_migration("demo", wf, "weak", generator=StrictGen(), cwd=tmp_path, seed=1)

    assert result.status == MigrationStatus.PASS
    assert result.edited_files == ["prompt.txt"]
    assert "STRICT" in (tmp_path / "prompt.txt").read_text()  # committed
    assert result.final.f1 == pytest.approx(1.0)
    assert all(c.passed for c in result.holdout_checks)


def test_model_change_only_when_naive_passes(tmp_path: Path):
    wf = _make_workflow(tmp_path)
    # target "good" behaves like baseline, so naive swap already passes.
    result = run_migration("demo", wf, "good", cwd=tmp_path, seed=1)
    assert result.status == MigrationStatus.MODEL_CHANGE_ONLY
    assert result.edited_files == []
    assert not (tmp_path / "prompt.txt").exists()


class TieGen:
    """Two candidates that both score perfectly but differ in edit size."""

    SMALL = "STRICT"
    LARGE = "STRICT\n" + "\n".join(f"filler line {i}" for i in range(10))

    def generate(self, ctx):
        # Offer the large edit first so acceptance must *replace* it with the
        # smaller one on the score tie (not merely keep an early small winner).
        return [
            Patch(files={"prompt.txt": self.LARGE}, rationale="large"),
            Patch(files={"prompt.txt": self.SMALL}, rationale="small"),
        ]


def test_tie_breaker_prefers_smaller_edit(tmp_path: Path):
    wf = _make_workflow(tmp_path)
    result = run_migration("demo", wf, "weak", generator=TieGen(), cwd=tmp_path, seed=1)

    assert result.status == MigrationStatus.PASS
    # Both candidates score 1.0; the committed prompt is the *smaller* one.
    assert (tmp_path / "prompt.txt").read_text() == TieGen.SMALL

    # Diff sizes are tracked, and the final accepted edit is the smaller one.
    assert all(a.diff_size is not None for a in result.experiment_log)
    accepted = [a for a in result.experiment_log if a.accepted]
    assert accepted[-1].rationale == "small"
    assert accepted[-1].diff_size == 1  # one changed line vs. the (absent) original
    # The smaller winning edit beat a strictly larger same-scoring candidate.
    assert any(a.rationale == "large" and a.diff_size > 1 for a in result.experiment_log)
    assert all(a.file_contents for a in result.experiment_log)
    assert result.original_editable_files == {"prompt.txt": ""}
    assert result.experiment_log[0].file_contents["prompt.txt"] == TieGen.LARGE


def test_partial_does_not_commit(tmp_path: Path):
    wf = _make_workflow(tmp_path)
    result = run_migration("demo", wf, "weak", generator=GuessGen(), cwd=tmp_path, seed=1)

    assert result.status == MigrationStatus.PARTIAL
    assert result.edited_files == []
    assert not (tmp_path / "prompt.txt").exists()  # changes rolled back
    # improved over the all-null naive swap
    assert result.final.f1 > result.naive_target.f1


def test_blocked_without_override(tmp_path: Path):
    wf = _make_workflow(tmp_path)
    wf.model.env_var = None  # remove override mechanism
    result = run_migration("demo", wf, "weak", generator=StrictGen(), cwd=tmp_path)
    assert result.status == MigrationStatus.BLOCKED


def test_validate_patch_scope_rejects_non_editable(tmp_path: Path):
    wf = _make_workflow(tmp_path)
    bad = Patch(files={"src/business_logic.py": "malicious"})
    with pytest.raises(Exception):
        validate_patch_scope(bad, wf, tmp_path)


def test_apply_files_restores(tmp_path: Path):
    target = tmp_path / "prompt.txt"
    target.write_text("original")
    with apply_files({"prompt.txt": "temp"}, cwd=tmp_path):
        assert target.read_text() == "temp"
    assert target.read_text() == "original"


def test_apply_files_deletes_created_file(tmp_path: Path):
    with apply_files({"new.txt": "temp"}, cwd=tmp_path):
        assert (tmp_path / "new.txt").exists()
    assert not (tmp_path / "new.txt").exists()


def test_assess_split_sizes_flags_small_data():
    warnings = assess_split_sizes(8, 3, holdout_required=True)
    assert any("Small dataset" in w for w in warnings)
    assert any("Small holdout" in w for w in warnings)

    # A comfortably large dataset/holdout produces no warnings.
    assert assess_split_sizes(500, 150, holdout_required=True) == []

    # Holdout warning is suppressed when holdout isn't required.
    only_dataset = assess_split_sizes(8, 3, holdout_required=False)
    assert all("holdout" not in w.lower() for w in only_dataset)


def test_small_dataset_run_carries_warning(tmp_path: Path):
    wf = _make_workflow(tmp_path)  # 6 examples -> below the min thresholds
    result = run_migration("demo", wf, "weak", generator=StrictGen(), cwd=tmp_path, seed=1)
    assert any("Small dataset" in w for w in result.warnings)
    assert any("Low per-class support" in w for w in result.warnings)


def test_cluster_failures():
    rows = [
        RecordRow(0, True, True, "billing", "billing", False, False, True),
        RecordRow(1, True, True, "technical", "billing", False, False, False),
        RecordRow(2, True, True, "technical", "billing", False, False, False),
        RecordRow(3, False, False, None, "refund", False, True, False),
        RecordRow(4, True, True, None, "refund", True, False, False),
    ]
    clusters = cluster_failures(rows)
    kinds = {c.kind: c for c in clusters}
    assert kinds["schema_error"].count == 1
    assert kinds["refusal"].count == 1
    assert kinds["misclassification"].count == 2  # billing<-technical pair
    assert kinds["misclassification"].key == "billing -> technical"


def test_multi_seed_tuning_still_passes(tmp_path: Path):
    wf = _make_workflow(tmp_path)
    wf.migration.split_seed_count = 2
    result = run_migration("demo", wf, "weak", generator=StrictGen(), cwd=tmp_path, seed=1)

    assert result.status == MigrationStatus.PASS
    assert result.split_seeds_used == [1, 2]
    assert any("Multi-seed tuning" in w for w in result.warnings)
