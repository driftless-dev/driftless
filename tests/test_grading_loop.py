"""End-to-end engine test for customer-supplied grading (score mode).

Proves the *whole* loop is task-agnostic: with no gold labels and no
classification, a workflow that emits its own per-record `score` is optimized by
the same clustering + candidate-selection + holdout machinery used for
classification. The "grader" lives entirely in the customer's command.
"""

import json
import sys
from pathlib import Path

from driftless.contract import Workflow
from driftless.engine import Patch, MigrationStatus, cluster_failures, run_migration

# A stdlib "app": its per-record score depends on the (editable) prompt. Without
# the magic instruction the model scores poorly on "hard" rows; with it, every
# row scores 1.0 -- a fixable, prompt-driven quality regression.
APP_PY = '''\
import json, pathlib

prompt = pathlib.Path("prompts/system.txt").read_text(encoding="utf-8").lower()
strict = "be strict" in prompt
lines = [l for l in pathlib.Path("inputs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
out = []
for line in lines:
    rec = json.loads(line)
    if strict:
        score = 1.0
    else:
        score = 0.2 if rec.get("hard") else 0.6
    out.append(json.dumps({"id": rec["id"], "score": score}))
pathlib.Path("out.jsonl").write_text("\\n".join(out) + "\\n", encoding="utf-8")
'''

INITIAL_PROMPT = "Answer the user's question.\n"


def _build(tmp_path: Path) -> Workflow:
    (tmp_path / "app.py").write_text(APP_PY, encoding="utf-8")
    (tmp_path / "prompts").mkdir(exist_ok=True)
    (tmp_path / "prompts" / "system.txt").write_text(INITIAL_PROMPT, encoding="utf-8")
    inputs = [{"id": f"q{i:02d}", "hard": i % 2 == 0} for i in range(12)]
    (tmp_path / "inputs.jsonl").write_text(
        "\n".join(json.dumps(x) for x in inputs) + "\n", encoding="utf-8"
    )
    return Workflow.model_validate(
        {
            "description": "Free-form QA graded by a customer scorer.",
            "run": {
                "command": f"{sys.executable} app.py",
                "input_path": "inputs.jsonl",
                "output_path": "out.jsonl",
            },
            "model": {"current": "old", "env_var": "MODEL", "target_candidates": ["new"]},
            "files": {"editable": ["prompts/system.txt"], "readonly": ["app.py"]},
            "eval": {"score_field": "score", "split": {"tuning": "60%", "holdout": "40%"}},
            "thresholds": {"min_score": 0.9},
            "migration": {"max_iterations": 4, "holdout_required": True},
        }
    )


class ScriptedScoreRepair:
    PATH = "prompts/system.txt"

    def generate(self, context):
        # React to the score-based failure signal the engine surfaces.
        if not any(c.kind == "low_score" for c in context.clusters):
            return []
        content = context.editable_files[self.PATH]
        if "be strict" in content.lower():
            return []
        return [Patch(files={self.PATH: content + "Be strict and precise.\n"}, kind="scripted")]


def test_clusters_surface_low_score_rows():
    from driftless.evaluation import RecordRow

    rows = [
        RecordRow(0, True, True, 0.2, None, False, False, None, score=0.2, is_low_score=True),
        RecordRow(1, True, True, 1.0, None, False, False, None, score=1.0, is_low_score=False),
    ]
    clusters = cluster_failures(rows)
    assert any(c.kind == "low_score" and c.count == 1 for c in clusters)


def test_score_graded_workflow_is_optimized_to_pass(tmp_path: Path):
    wf = _build(tmp_path)
    result = run_migration(
        "qa", wf, "new", generator=ScriptedScoreRepair(), cwd=tmp_path, seed=1
    )
    assert result.status == MigrationStatus.PASS, result.message
    assert (result.final.score or 0.0) >= 0.9
    assert result.final.f1 is None  # never did classification
    assert result.edited_files == ["prompts/system.txt"]
    assert "be strict" in (tmp_path / "prompts" / "system.txt").read_text().lower()


def test_score_graded_workflow_blocks_without_repair(tmp_path: Path):
    wf = _build(tmp_path)
    result = run_migration("qa", wf, "new", cwd=tmp_path, seed=1)
    assert result.status == MigrationStatus.BLOCKED
