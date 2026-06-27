import os

from driftless.progress import enabled, log


def test_progress_enabled_in_ci(monkeypatch):
    monkeypatch.delenv("DRIFTLESS_PROGRESS", raising=False)
    monkeypatch.setenv("CI", "true")
    assert enabled() is True


def test_progress_disabled_explicitly(monkeypatch):
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("DRIFTLESS_PROGRESS", "0")
    assert enabled() is False


def test_progress_log_writes_stderr(capsys, monkeypatch):
    monkeypatch.setenv("DRIFTLESS_PROGRESS", "1")
    log("hello from progress")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "hello from progress" in captured.err


def test_progress_log_silent_when_disabled(capsys, monkeypatch):
    monkeypatch.delenv("DRIFTLESS_PROGRESS", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    log("should not appear")
    captured = capsys.readouterr()
    assert captured.err == ""


def test_harness_streams_output_when_progress_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTLESS_PROGRESS", "1")
    script = tmp_path / "run.sh"
    script.write_text(
        "#!/bin/sh\n"
        "echo progress-from-child\n"
        "echo '{\"id\":\"1\",\"category\":\"billing\"}' > \"$EVAL_OUTPUT\"\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    (tmp_path / "inputs.jsonl").write_text('{"id":"1","text":"help"}\n', encoding="utf-8")
    (tmp_path / "driftless.yml").write_text(
        """
version: 1
workflows:
  smoke:
    run:
      command: ./run.sh
      input_path: inputs.jsonl
      output_path: outputs.jsonl
    model:
      current: gpt-4o-mini
      env_var: TEST_MODEL
    files:
      editable: []
    eval:
      labels_path: labels.jsonl
      label_field: category
    thresholds:
      min_f1: 0.5
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "labels.jsonl").write_text('{"id":"1","category":"billing"}\n', encoding="utf-8")

    from driftless.contract import load_contract
    from driftless.harness import run_workflow

    wf = load_contract(tmp_path / "driftless.yml").workflow("smoke")
    monkeypatch.setenv("EVAL_OUTPUT", str(tmp_path / "outputs.jsonl"))
    result = run_workflow(wf, "gpt-4o-mini", cwd=tmp_path)
    assert result.ok
