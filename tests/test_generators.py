import json
import sys
from pathlib import Path

import pytest

from driftless.contract import Workflow
from driftless.engine import MigrationStatus, Patch, PatchContext, run_migration
from driftless.errors import DriftlessError
from driftless.evaluation import Metrics
from driftless.evaluation import RecordRow
from driftless.generators import (
    LLMPatchGenerator,
    _failing_examples,
    _positive_exemplars,
    build_generator,
    build_user_prompt,
    parse_patch,
)

RUN_PY = """\
import os, json, pathlib
model = os.environ["DEMO_MODEL"]
prompt = pathlib.Path("prompt.txt").read_text() if pathlib.Path("prompt.txt").exists() else ""
out = pathlib.Path(".driftless/results/out.jsonl"); out.parent.mkdir(parents=True, exist_ok=True)
lines = [l for l in pathlib.Path("inputs.jsonl").read_text().splitlines() if l.strip()]
with out.open("w") as f:
    for l in lines:
        gold = json.loads(l)["label"]
        f.write(json.dumps({"label": gold if (model=="good" or "STRICT" in prompt) else None})+"\\n")
"""

INPUTS = ["billing", "technical", "refund", "billing", "technical", "refund"]


def _make_workflow(tmp_path: Path) -> Workflow:
    (tmp_path / "run.py").write_text(RUN_PY)
    (tmp_path / "inputs.jsonl").write_text(
        "\n".join(json.dumps({"label": x}) for x in INPUTS) + "\n"
    )
    (tmp_path / "labels.jsonl").write_text("\n".join(json.dumps(x) for x in INPUTS) + "\n")
    return Workflow.model_validate(
        {
            "run": {
                "command": f"{sys.executable} run.py",
                "input_path": "inputs.jsonl",
                "output_path": ".driftless/results/out.jsonl",
            },
            "model": {"current": "good", "env_var": "DEMO_MODEL"},
            "files": {"editable": ["prompt.txt"]},
            "eval": {"labels_path": "labels.jsonl"},
            "thresholds": {"min_f1": 0.9},
            "migration": {"max_iterations": 3},
        }
    )


def test_parse_patch_scopes_to_editable():
    text = json.dumps(
        {
            "rationale": "fix",
            "files": {"prompt.txt": "STRICT", "src/logic.py": "evil", "other.md": 5},
        }
    )
    patch = parse_patch(text, editable={"prompt.txt"})
    assert patch is not None
    assert set(patch.files) == {"prompt.txt"}  # non-editable + non-str dropped
    assert patch.kind == "llm"


def test_parse_patch_handles_fenced_and_garbage():
    fenced = "```json\n" + json.dumps({"files": {"a": "b"}}) + "\n```"
    assert parse_patch(fenced, {"a"}) is not None
    assert parse_patch("not json at all", {"a"}) is None
    assert parse_patch(json.dumps({"files": {}}), {"a"}) is None


def test_llm_generator_drives_migration_to_pass(tmp_path: Path):
    wf = _make_workflow(tmp_path)

    def fake_complete(system: str, user: str, temperature: float) -> str:
        assert "failure_clusters" in user  # prompt carries context
        return json.dumps(
            {"rationale": "be strict", "files": {"prompt.txt": "STRICT: echo the exact label."}}
        )

    gen = LLMPatchGenerator(complete_fn=fake_complete)
    result = run_migration("demo", wf, "weak", generator=gen, cwd=tmp_path, seed=1)

    assert result.status == MigrationStatus.PASS
    assert "STRICT" in (tmp_path / "prompt.txt").read_text()


def test_llm_generator_skips_bad_completion(tmp_path: Path):
    wf = _make_workflow(tmp_path)

    def bad_complete(system: str, user: str, temperature: float) -> str:
        return "totally not json"

    gen = LLMPatchGenerator(complete_fn=bad_complete)
    result = run_migration("demo", wf, "weak", generator=gen, cwd=tmp_path, seed=1)
    # No usable patch -> migration cannot succeed, but must not crash.
    assert result.status in (MigrationStatus.BLOCKED, MigrationStatus.PARTIAL)


def test_build_generator_none_returns_none():
    assert build_generator("none") is None


def test_build_generator_unknown_raises():
    with pytest.raises(DriftlessError):
        build_generator("bogus")


def test_build_generator_llm_without_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(DriftlessError):
        build_generator("llm")


def _ctx_with_rows(tmp_path: Path, rows, context_files=None) -> PatchContext:
    wf = _make_workflow(tmp_path)
    m = Metrics(n=len(rows), schema_error_rate=0.0, refusal_rate=0.0)
    return PatchContext(
        workflow=wf,
        workflow_name="demo",
        target_model="weak",
        iteration=0,
        editable_files={"prompt.txt": ""},
        baseline=m,
        current=m,
        clusters=[],
        rows=rows,
        context_files=context_files or {},
    )


def test_failing_examples_carry_real_input_and_output(tmp_path: Path):
    rows = [
        RecordRow(
            index=0, parse_ok=True, schema_ok=True,
            predicted="billing", gold="refund", is_refusal=False,
            is_schema_error=False, is_correct=False,
            raw='{"id":"t0","label":"billing"}',
            input_text='{"id":"t0","text":"I want my money back"}',
        ),
        RecordRow(
            index=1, parse_ok=True, schema_ok=True,
            predicted="billing", gold="billing", is_refusal=False,
            is_schema_error=False, is_correct=True,
            raw='{"id":"t1","label":"billing"}',
            input_text='{"id":"t1","text":"my invoice is wrong"}',
        ),
    ]
    ctx = _ctx_with_rows(tmp_path, rows)

    failing = _failing_examples(ctx)
    assert len(failing) == 1
    assert failing[0]["gold"] == "refund"
    assert "money back" in failing[0]["input"]
    assert "billing" in failing[0]["raw_output"]

    # The real data also reaches the actual prompt sent to the model.
    prompt = build_user_prompt(ctx)
    assert "money back" in prompt
    assert "correct_examples" in prompt


def test_positive_exemplars_are_balanced_per_class(tmp_path: Path):
    rows = [
        RecordRow(i, True, True, lbl, lbl, False, False, True,
                  raw=f'{{"label":"{lbl}"}}', input_text=f"text for {lbl} {i}")
        for i, lbl in enumerate(["billing", "billing", "billing", "technical"])
    ]
    ctx = _ctx_with_rows(tmp_path, rows)
    pos = _positive_exemplars(ctx, per_class=2)
    labels = [e["label"] for e in pos]
    assert labels.count("billing") == 2  # capped per class
    assert labels.count("technical") == 1


def test_readonly_context_files_appear_in_prompt(tmp_path: Path):
    ctx = _ctx_with_rows(
        tmp_path,
        rows=[],
        context_files={"src/parse.py": "def parse(x):\n    return json.loads(x)['label']"},
    )
    prompt = build_user_prompt(ctx)
    assert "readonly_context_files" in prompt
    assert "json.loads" in prompt
    assert "REFERENCE ONLY" in prompt


def test_prompt_respects_char_budget(tmp_path: Path):
    big = "x" * 3000
    rows = [
        RecordRow(
            index=i, parse_ok=True, schema_ok=True,
            predicted="billing", gold="refund", is_refusal=False,
            is_schema_error=False, is_correct=False,
            raw='{"label":"billing"}', input_text=f"{big} {i}",
        )
        for i in range(40)
    ]
    ctx = _ctx_with_rows(tmp_path, rows)
    prompt = build_user_prompt(ctx, max_chars=5000)
    # Evidence was trimmed to fit the budget (editable files here are tiny).
    assert len(prompt) <= 5000
    # ...but the editable file payload is still present (never trimmed).
    assert "prompt.txt" in prompt


def test_generator_multi_candidate_temperature(tmp_path: Path):
    wf = _make_workflow(tmp_path)
    seen = []

    def rec_complete(system: str, user: str, temperature: float) -> str:
        seen.append(temperature)
        return json.dumps({"files": {"prompt.txt": "noop"}})

    gen = LLMPatchGenerator(complete_fn=rec_complete, num_candidates=2)
    ctx = PatchContext(
        workflow=wf,
        workflow_name="demo",
        target_model="weak",
        iteration=0,
        editable_files={"prompt.txt": ""},
        baseline=Metrics(n=1, schema_error_rate=0.0, refusal_rate=0.0),
        current=Metrics(n=1, schema_error_rate=0.0, refusal_rate=0.0),
        clusters=[],
        rows=[],
    )
    patches = gen.generate(ctx)
    assert len(patches) == 2
    assert seen[0] != seen[1]  # temperature varied across candidates
