"""P3.2(d): the engine optimizes a judge-graded free-form workflow end-to-end.

Proves the whole loop (no gold labels, free-form text outputs, a second model
inside the loop) works with an injected deterministic judge -- so judge grading
needs no network for the regression harness.
"""

import sys
from pathlib import Path

from driftless.contract import Workflow
from driftless.engine import MigrationStatus, Objective, run_migration
from driftless.judges import JudgeResult


# A free-form "summarizer": emits raw text. The (editable) prompt decides whether
# it appends the word the judge rewards. The target model only complies once the
# prompt explicitly instructs it -- a prompt-fixable regression with no labels.
APP_PY = '''\
import os, pathlib

prompt = pathlib.Path("prompts/sys.txt").read_text(encoding="utf-8").lower()
comply = "say good" in prompt
lines = [l for l in pathlib.Path("in.jsonl").read_text().splitlines() if l.strip()]
out = []
for i, _ in enumerate(lines):
    out.append("summary is good" if comply else "summary here")
pathlib.Path("out.jsonl").write_text("\\n".join(out) + "\\n", encoding="utf-8")
'''


class KeywordJudge:
    def score(self, *, input_text, output_text):
        hit = "good" in (output_text or "")
        return JudgeResult(1.0 if hit else 0.2, "ok" if hit else "no keyword")


class AppendGoodRepair:
    """Scripted generator: add the instruction the judge rewards."""

    PATH = "prompts/sys.txt"

    def generate(self, context):
        from driftless.engine import Patch

        content = context.editable_files[self.PATH]
        if "say good" in content.lower():
            return []
        return [Patch(files={self.PATH: content + "\nAlways say good.\n"}, rationale="comply", kind="scripted")]


def _build(tmp_path: Path) -> Workflow:
    (tmp_path / "app.py").write_text(APP_PY)
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "sys.txt").write_text("Summarize the input.\n")
    (tmp_path / "in.jsonl").write_text("\n".join('{"id": "t%d"}' % i for i in range(10)) + "\n")
    return Workflow.model_validate(
        {
            "run": {"command": f"{sys.executable} app.py", "input_path": "in.jsonl", "output_path": "out.jsonl"},
            "model": {"current": "old", "env_var": "MODEL", "target_candidates": ["new"]},
            "files": {"editable": ["prompts/sys.txt"], "readonly": ["app.py"]},
            "eval": {
                "judge": {"rubric": "Award full marks if the summary says 'good'."},
                "split": {"tuning": "60%", "holdout": "40%"},
            },
            "thresholds": {"min_score": 0.9},
            "migration": {"max_iterations": 4, "holdout_required": True},
        }
    )


def test_engine_optimizes_judge_graded_workflow(tmp_path: Path):
    wf = _build(tmp_path)
    result = run_migration(
        "summarizer", wf, "new", generator=AppendGoodRepair(), judge=KeywordJudge(),
        cwd=tmp_path, seed=1,
    )
    assert result.status == MigrationStatus.PASS, result.message
    assert result.final.score is not None and result.final.score >= 0.9
    assert result.edited_files == ["prompts/sys.txt"]
    committed = (tmp_path / "prompts" / "sys.txt").read_text().lower()
    assert "say good" in committed


def test_refine_maximizes_judge_score(tmp_path: Path):
    # Same engine, MAXIMIZE objective (refine): model pinned, judge-graded.
    wf = _build(tmp_path)
    result = run_migration(
        "summarizer", wf, "old", generator=AppendGoodRepair(), judge=KeywordJudge(),
        cwd=tmp_path, seed=1, objective=Objective.MAXIMIZE,
    )
    assert result.status == MigrationStatus.PASS, result.message
    assert result.suggested_thresholds.get("min_score") is not None
