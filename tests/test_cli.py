import json
import re
from types import SimpleNamespace
from pathlib import Path

from typer.testing import CliRunner

from driftless import engine, generators, github, report
from driftless.cli import (
    _act_on_trigger,
    _format_retires,
    _model_change_preparer,
    app,
)
from driftless.contract import Workflow
from driftless.templates import CONTRACT_TEMPLATE

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


runner = CliRunner()


def test_cli_help_matches_product_lede():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Keep models, prompts, and eval data in sync" in result.output


def test_format_retires_past_and_future():
    assert _format_retires(None) == "-"
    assert _format_retires(12) == "12d"
    assert _format_retires(0) == "retired today"
    assert _format_retires(-319) == "retired 319d ago"


def test_cli_version(monkeypatch):
    from driftless import __version__

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"driftless {__version__}"
    assert "\x1b[" not in result.output


def test_init_scaffolds_contract(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--path", "driftless.yml"])

    assert result.exit_code == 0
    assert Path("driftless.yml").is_file()
    contract = Path("driftless.yml").read_text()
    assert "my_workflow" in contract
    assert "support_classifier" not in contract
    assert "TODO" in contract


def test_configure_apply_creates_root_contract_and_reports_todos(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("app.py").write_text("print('hello')\n")

    result = runner.invoke(app, ["configure", "summary", "--apply"])

    assert result.exit_code == 0
    contract = Path("driftless.yml").read_text()
    assert "version: 1" in contract
    assert "summary:" in contract
    assert "unresolved placeholder" in _plain(result.output)


def test_configure_apply_merges_without_rewriting_existing_comments(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("app.py").write_text("print('hello')\n")
    Path("driftless.yml").write_text(
        """# keep this comment
version: 1
workflows:
  existing:
    run:
      command: echo ok
      input_path: in.jsonl
      output_path: out.jsonl
    model:
      current: gpt-4o
      env_var: MODEL
"""
    )

    result = runner.invoke(app, ["configure", "summary", "--apply"])

    assert result.exit_code == 0
    contract = Path("driftless.yml").read_text()
    assert "# keep this comment" in contract
    assert "existing:" in contract
    assert "summary:" in contract


def test_validate_refuses_unresolved_scaffold_placeholders(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("driftless.yml").write_text(CONTRACT_TEMPLATE)

    result = runner.invoke(app, ["validate", "--no-run"])

    assert result.exit_code == 1
    assert "unresolved scaffold placeholders" in _plain(result.output)


def test_init_policy_scaffolds_policy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init-policy"])

    assert result.exit_code == 0
    assert Path(".driftless/policy.yml").is_file()
    assert "deprecation" in Path(".driftless/policy.yml").read_text()


def test_copy_example_scaffolds_bundled_example(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["copy-example", "rag-qa"])

    assert result.exit_code == 0
    assert Path("rag-qa/driftless.yml").is_file()
    assert Path("rag-qa/app/eval_rag.py").is_file()
    assert "driftless validate -w rag_qa" in _plain(result.output)


def test_copy_example_prints_support_classifier_workflow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["copy-example", "support-classifier"])

    assert result.exit_code == 0
    assert "driftless validate -w support_classifier" in _plain(result.output)


def test_copy_example_prints_live_classifier_workflow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["copy-example", "support-classifier-live"])

    assert result.exit_code == 0
    assert "driftless validate -w support_classifier_live" in _plain(result.output)


def test_copy_example_help_lists_support_classifier():
    result = runner.invoke(app, ["copy-example", "--help"])

    assert result.exit_code == 0
    assert "support-classifier" in result.output
    assert "support-classifier-live" in result.output
    assert "rag-qa" in result.output
    assert "tool-agent" in result.output


def test_copy_example_requires_name_and_lists_examples(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["copy-example"])

    assert result.exit_code == 1
    out = _plain(result.output)
    assert "missing example name" in out
    assert "support-classifier" in out
    assert "support-classifier-live" in out
    assert "Traceback" not in out


def test_copy_example_rejects_unknown_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["copy-example", "missing-example"])

    assert result.exit_code == 1
    assert "unknown example" in _plain(result.output)
    assert "rag-qa" in _plain(result.output)
    assert "support-classifier" in _plain(result.output)


def test_validate_no_run_accepts_minimal_contract(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("inputs.jsonl").write_text('{"id": "1", "text": "hello"}\n')
    Path("driftless.yml").write_text(
        """
version: 1
workflows:
  smoke:
    run:
      command: python -c "print('not run')"
      input_path: inputs.jsonl
      output_path: .driftless/results/smoke.outputs.jsonl
    model:
      current: gpt-4o-mini
      env_var: SMOKE_MODEL
""".lstrip()
    )

    result = runner.invoke(
        app,
        ["validate", "--workflow", "smoke", "--contract", "driftless.yml", "--no-run"],
    )

    assert result.exit_code == 0
    assert "contract ok" in result.output
    assert "skipping harness run" in result.output
    assert "driftless compare -w smoke --to <model>" in _plain(result.output)


def test_validate_suggests_first_target_candidate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("inputs.jsonl").write_text('{"id": "1", "text": "hello"}\n')
    Path("driftless.yml").write_text(
        """
version: 1
workflows:
  smoke:
    run:
      command: python -c "print('not run')"
      input_path: inputs.jsonl
      output_path: .driftless/results/smoke.outputs.jsonl
    model:
      current: gpt-4
      target_candidates: [gpt-4o-mini]
      env_var: SMOKE_MODEL
""".lstrip()
    )

    result = runner.invoke(app, ["validate", "-w", "smoke", "--no-run"])

    assert result.exit_code == 0
    assert "driftless compare -w smoke --to gpt-4o-mini" in _plain(result.output)


def test_scan_reports_detected_model(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("app.py").write_text('from openai import OpenAI\nMODEL = "gpt-4o-mini"\n')

    result = runner.invoke(app, ["scan", "."])

    assert result.exit_code == 0
    assert "Probable LLM workflows" in result.output
    assert "gpt-4o-mini" in result.output
    assert "configure workflow --apply" in _plain(result.output)


def test_scan_suggests_configure_for_active_package(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("pyproject.toml").write_text('[project]\nname = "incident-brief"\n')
    Path("brief.py").write_text(
        'from openai import OpenAI\nMODEL = os.getenv("BRIEF_MODEL", "gpt-4o")\n'
    )

    result = runner.invoke(app, ["scan", "."])

    assert result.exit_code == 0
    out = _plain(result.output)
    assert "No deprecated or retired models detected" in out
    assert "configure incident_brief --apply" in out


def test_open_pr_dry_run_reads_migration_artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".driftless" / "migrations").mkdir(parents=True)
    (tmp_path / ".driftless" / "reports").mkdir(parents=True)
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "system.md").write_text("prompt\n")
    (tmp_path / "config").mkdir()
    config_path = tmp_path / "config" / "llm.yml"
    config_path.write_text(
        "workflows:\n  support_classifier:\n    model: gpt-4o-mini\n"
    )
    original_config = config_path.read_bytes()
    Path("driftless.yml").write_text(
        """
version: 1
workflows:
  support_classifier:
    run:
      command: "python -c pass"
      input_path: inputs.jsonl
      output_path: outputs.jsonl
    model:
      current: gpt-4o-mini
      target_candidates: [gpt-5-mini]
      config_file: config/llm.yml
      config_path: workflows.support_classifier.model
    eval:
      labels_path: labels.jsonl
""".lstrip()
    )
    migration = {
        "workflow": "support_classifier",
        "current_model": "gpt-4o-mini",
        "target_model": "gpt-5-mini",
        "status": "pass",
        "succeeded": True,
        "edited_files": ["prompts/system.md"],
    }
    Path(".driftless/migrations/support_classifier.json").write_text(json.dumps(migration))
    Path(".driftless/reports/support_classifier.md").write_text("# Migration report\n")

    result = runner.invoke(app, ["open-pr", "-w", "support_classifier"])

    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert "create branch" in result.output
    assert "re-run with --create" in result.output
    assert config_path.read_bytes() == original_config


def test_plan_act_dry_run_does_not_change_model_config(tmp_path, monkeypatch):
    config_path = tmp_path / "llm.yml"
    config_path.write_text("model: provider/old-model\n")
    original_config = config_path.read_bytes()
    wf = Workflow.model_validate(
        {
            "run": {"command": "true", "input_path": "i", "output_path": "o"},
            "model": {
                "current": "provider/old-model",
                "config_file": "llm.yml",
                "config_path": "model",
            },
        }
    )
    migration_result = SimpleNamespace(status=SimpleNamespace(value="pass"))
    result_dict = {
        "workflow": "demo/workflow",
        "current_model": "provider/old-model",
        "target_model": "provider/new:model",
        "succeeded": True,
        "edited_files": [],
    }
    seen: dict = {}

    monkeypatch.setattr(engine, "run_migration", lambda *args, **kwargs: migration_result)
    monkeypatch.setattr(generators, "build_generator", lambda name: object())
    monkeypatch.setattr(report, "save_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(report, "result_to_dict", lambda result: result_dict)
    monkeypatch.setattr(report, "render_markdown", lambda *args: "# report")

    def fake_execute(
        plan, *, cwd, create, push, dedupe, prepare_files, base_branch
    ):
        seen["plan"] = plan
        seen["prepare_files"] = prepare_files
        return ["dry run"]

    monkeypatch.setattr(github, "execute_plan", fake_execute)

    ok, _ = _act_on_trigger(
        "demo/workflow",
        wf,
        "provider/new:model",
        generator_name="none",
        create=False,
        seed=0,
        cwd=tmp_path,
    )

    assert ok
    assert config_path.read_bytes() == original_config
    assert seen["plan"].files == ["llm.yml"]
    assert seen["plan"].kind == "pr"
    assert seen["prepare_files"] is None


def test_model_config_preparation_restores_file_when_git_add_fails(tmp_path, monkeypatch):
    config_path = tmp_path / "llm.yml"
    config_path.write_text("model: provider/old-model\n")
    original = config_path.read_bytes()
    wf = Workflow.model_validate(
        {
            "run": {"command": "true", "input_path": "i", "output_path": "o"},
            "model": {
                "current": "provider/old-model",
                "config_file": "llm.yml",
                "config_path": "model",
            },
        }
    )
    plan = github.build_pr_plan(
        {
            "workflow": "demo",
            "current_model": "provider/old-model",
            "target_model": "provider/new-model",
            "status": "pass",
            "succeeded": True,
        },
        "# report",
        committed_files=["llm.yml"],
    )
    calls: list[list[str]] = []

    def fake_run(args, *, cwd):
        calls.append(args)
        if args[:2] == ["git", "add"]:
            from driftless.errors import DriftlessError

            raise DriftlessError("git add failed")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(github, "_run", fake_run)
    monkeypatch.setattr(github, "current_git_branch", lambda *, cwd: "main")
    monkeypatch.setattr(
        github, "ensure_pr_branch_available", lambda plan, *, cwd, push: None
    )

    from driftless.errors import DriftlessError

    try:
        github.execute_plan(
            plan,
            cwd=tmp_path,
            create=True,
            dedupe=False,
            prepare_files=_model_change_preparer(
                wf, "provider/new-model", cwd=tmp_path
            ),
        )
    except DriftlessError:
        pass
    else:
        raise AssertionError("expected git add failure")

    assert config_path.read_bytes() == original
    assert ["git", "reset", "--", "llm.yml"] in calls
    assert calls[-1] == ["git", "branch", "-D", plan.branch]


def test_open_pr_create_invokes_execute_plan(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".driftless" / "migrations").mkdir(parents=True)
    (tmp_path / ".driftless" / "reports").mkdir(parents=True)
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "system.md").write_text("prompt\n")
    Path("driftless.yml").write_text(
        """
version: 1
workflows:
  support_classifier:
    run:
      command: "python -c pass"
      input_path: inputs.jsonl
      output_path: outputs.jsonl
    model:
      current: gpt-4o-mini
      env_var: SUPPORT_CLASSIFIER_MODEL
    eval:
      labels_path: labels.jsonl
""".lstrip()
    )
    migration = {
        "workflow": "support_classifier",
        "current_model": "gpt-4o-mini",
        "target_model": "gpt-5-mini",
        "status": "pass",
        "succeeded": True,
        "edited_files": ["prompts/system.md"],
    }
    Path(".driftless/migrations/support_classifier.json").write_text(json.dumps(migration))
    Path(".driftless/reports/support_classifier.md").write_text("# report\n")

    seen: dict = {}

    def fake_execute(plan, *, cwd, create, push, dedupe, prepare_files):
        seen.update(create=create, push=push, dedupe=dedupe, kind=plan.kind, title=plan.title)
        assert prepare_files is not None
        assert "driftless.yml" in plan.files
        return ["create branch: x", "PR created"]

    monkeypatch.setattr(github, "execute_plan", fake_execute)

    result = runner.invoke(
        app,
        ["open-pr", "-w", "support_classifier", "--create", "--no-push", "--no-dedupe"],
    )

    assert result.exit_code == 0
    assert seen == {
        "create": True,
        "push": False,
        "dedupe": False,
        "kind": "pr",
        "title": "chore: migrate support_classifier from gpt-4o-mini to gpt-5-mini",
    }
    assert "Creating" in result.output
    assert "PR created" in result.output


def test_judge_check_reports_calibration_agreement(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "calib.jsonl").write_text(
        json.dumps({"input": "q", "output": "good", "score": 1.0}) + "\n"
    )
    Path("driftless.yml").write_text(
        """
version: 1
workflows:
  summarizer:
    run:
      command: "python -c pass"
      input_path: in.jsonl
      output_path: out.jsonl
    model:
      current: old
      env_var: MODEL
    eval:
      judge:
        rubric: "Award full marks if the summary says 'good'."
        calibration_path: calib.jsonl
        max_mae: 0.5
""".lstrip()
    )

    class StubJudge:
        def score(self, *, input_text, output_text):
            from driftless.judges import JudgeResult

            hit = "good" in (output_text or "")
            return JudgeResult(1.0 if hit else 0.2, "ok" if hit else "miss")

    monkeypatch.setattr("driftless.judges.build_judge", lambda spec: StubJudge())

    result = runner.invoke(app, ["judge-check", "-w", "summarizer"])

    assert result.exit_code == 0
    out = _plain(result.output)
    assert "MAE:" in out
    assert "max_mae=0.5 (ok)" in out
    assert "--enforce" in out


def test_judge_check_enforce_fails_when_gate_exceeded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "calib.jsonl").write_text(
        json.dumps({"input": "q", "output": "bad", "score": 1.0}) + "\n"
    )
    Path("driftless.yml").write_text(
        """
version: 1
workflows:
  summarizer:
    run:
      command: "python -c pass"
      input_path: in.jsonl
      output_path: out.jsonl
    model:
      current: old
      env_var: MODEL
    eval:
      judge:
        rubric: "Award full marks if the summary says 'good'."
        calibration_path: calib.jsonl
        max_mae: 0.01
""".lstrip()
    )

    class StubJudge:
        def score(self, *, input_text, output_text):
            from driftless.judges import JudgeResult

            return JudgeResult(0.2, "miss")

    monkeypatch.setattr("driftless.judges.build_judge", lambda spec: StubJudge())

    result = runner.invoke(app, ["judge-check", "-w", "summarizer", "--enforce"])

    assert result.exit_code == 1
    assert "mean absolute error" in result.output.lower()


def _judge_check_contract(tmp_path: Path, *, calibration: str = "calib.jsonl") -> None:
    Path("driftless.yml").write_text(
        f"""
version: 1
workflows:
  summarizer:
    run:
      command: "python -c pass"
      input_path: in.jsonl
      output_path: out.jsonl
    model:
      current: old
      env_var: MODEL
    eval:
      judge:
        rubric: "Award full marks if the summary says 'good'."
        calibration_path: {calibration}
        max_mae: 0.5
""".lstrip()
    )


def test_judge_check_missing_key_is_clean_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / "calib.jsonl").write_text(
        json.dumps({"input": "q", "output": "good", "score": 1.0}) + "\n"
    )
    _judge_check_contract(tmp_path)

    result = runner.invoke(app, ["judge-check", "-w", "summarizer"])

    assert result.exit_code == 1
    out = _plain(result.output)
    assert "Traceback" not in out
    assert "error:" in out
    assert "API key" in out
    assert "--generator" not in out


def test_judge_check_missing_calibration_before_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _judge_check_contract(tmp_path, calibration="missing.jsonl")

    result = runner.invoke(app, ["judge-check", "-w", "summarizer"])

    assert result.exit_code == 1
    out = _plain(result.output)
    assert "calibration file not found" in out
    assert "API key" not in out
    assert "Traceback" not in out


def test_refine_exits_nonzero_when_no_change_below_bar(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("in.jsonl").write_text('{"id": "1"}\n')
    Path("driftless.yml").write_text(
        """
version: 1
workflows:
  summarizer:
    run:
      command: "python -c pass"
      input_path: in.jsonl
      output_path: out.jsonl
    model:
      current: old
      env_var: MODEL
    eval:
      score_field: score
    thresholds:
      min_score: 0.9
""".lstrip()
    )

    from driftless.engine import MigrationResult, MigrationStatus
    from driftless.evaluation import Metrics

    low = Metrics(n=4, schema_error_rate=0.0, refusal_rate=0.0, score=0.5)
    stub = MigrationResult(
        workflow="summarizer",
        current_model="old",
        target_model="old",
        status=MigrationStatus.NO_CHANGE,
        iterations=0,
        baseline=low,
        naive_target=low,
        final=low,
        suggested_thresholds={"min_score": 0.47},
        message="no candidate beat the current prompt on the updated dataset",
    )
    monkeypatch.setattr("driftless.engine.run_migration", lambda *a, **k: stub)
    monkeypatch.setattr("driftless.generators.build_generator", lambda *a, **k: None)

    result = runner.invoke(app, ["refine", "-w", "summarizer", "-g", "none"])

    assert result.exit_code == 1
    out = _plain(result.output)
    assert "below the contract bar" in out
    assert "min_score" in out


def test_poll_fetch_lines_do_not_leak_markup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("in.jsonl").write_text('{"id": "1"}\n')
    Path("gold.jsonl").write_text('{"id": "1", "label": "a"}\n')
    Path("driftless.yml").write_text(
        """
version: 1
workflows:
  support_classifier:
    run:
      command: "python -c pass"
      input_path: in.jsonl
      output_path: out.jsonl
    model:
      current: gpt-4
      env_var: MODEL
    eval:
      labels_path: gold.jsonl
      data_source:
        command: "cp gold.jsonl gold.jsonl"
""".lstrip()
    )

    from driftless.datasource import FetchResult

    monkeypatch.setattr(
        "driftless.datasource.fetch_dataset",
        lambda *a, **k: FetchResult(
            fetched=True,
            actions=["ran data_source.command: cp gold.jsonl gold.jsonl"],
        ),
    )

    result = runner.invoke(app, ["poll"])

    assert result.exit_code == 0
    assert "[dim]" not in result.output
    assert "fetch support_classifier:" in _plain(result.output)
