"""Plan command integration with opportunistic trigger discovery."""

from pathlib import Path

from typer.testing import CliRunner

from driftless.cli import app
from driftless.compare import Comparison
from driftless.evaluation import Metrics

runner = CliRunner()


def _metrics(**kw) -> Metrics:
    base = dict(n=10, schema_error_rate=0.0, refusal_rate=0.0, f1=0.95)
    base.update(kw)
    return Metrics(**base)


def test_plan_surfaces_cost_trigger_with_catalog_estimate(tmp_path: Path, monkeypatch):
    """Cost triggers use catalog pricing when compare has no measured cost."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".driftless").mkdir()
    (tmp_path / ".driftless" / "policy.yml").write_text(
        "cost:\n  enabled: true\n  min_savings_pct: 0.20\n  max_quality_drop: 0.01\n",
        encoding="utf-8",
    )
    Path("driftless.yml").write_text(
        """
version: 1
workflows:
  support:
    run:
      command: "python -c pass"
      input_path: in.jsonl
      output_path: out.jsonl
    model:
      current: claude-3-opus-20240229
      env_var: MODEL
    eval:
      labels_path: labels.jsonl
""".lstrip(),
        encoding="utf-8",
    )

    def fake_compare(workflow, wf, target, cwd=None):
        return Comparison(
            workflow=workflow,
            current_model=wf.model.current,
            target_model=target,
            baseline=_metrics(total_cost=None),
            target=_metrics(total_cost=None),
            checks=[],
        )

    monkeypatch.setattr("driftless.compare.compare_models", fake_compare)

    result = runner.invoke(app, ["plan"])

    assert result.exit_code == 1  # actionable trigger
    assert "cost" in result.output.lower()
    assert "claude-3-5-sonnet" in result.output
    assert "claude-3-opus-20240229" in result.output


def test_plan_cost_trigger_uses_measured_cost_when_present(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".driftless").mkdir()
    (tmp_path / ".driftless" / "policy.yml").write_text(
        "cost:\n  enabled: true\n  min_savings_pct: 0.20\n  max_quality_drop: 0.01\n",
        encoding="utf-8",
    )
    Path("driftless.yml").write_text(
        """
version: 1
workflows:
  support:
    run:
      command: "python -c pass"
      input_path: in.jsonl
      output_path: out.jsonl
    model:
      current: claude-3-opus-20240229
      env_var: MODEL
    eval:
      labels_path: labels.jsonl
      cost_field: cost_usd
""".lstrip(),
        encoding="utf-8",
    )

    def fake_compare(workflow, wf, target, cwd=None):
        return Comparison(
            workflow=workflow,
            current_model=wf.model.current,
            target_model=target,
            baseline=_metrics(total_cost=10.0),
            target=_metrics(total_cost=4.0),
            checks=[],
        )

    monkeypatch.setattr("driftless.compare.compare_models", fake_compare)

    result = runner.invoke(app, ["plan"])

    assert result.exit_code == 1
    assert "cost" in result.output.lower()
    assert "PR" in result.output.upper() or "pr" in result.output.lower()
