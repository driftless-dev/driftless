"""The runnable workflow harness.

The customer owns the workflow; we orchestrate it. The harness runs the user's
own command (or hits their endpoint) with the model overridden, then reads the
production-shaped outputs they wrote to disk. We never reimplement their
preprocessing/parsing/postprocessing.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .contract import Workflow
from .errors import HarnessError
from .progress import enabled as progress_enabled, log as progress_log

#: Optional bearer token for endpoint workflows, sent as ``Authorization``.
ENDPOINT_TOKEN_ENV = "DRIFTLESS_ENDPOINT_TOKEN"


@dataclass
class RunResult:
    """Outcome of a single harness run under one model."""

    model: str
    output_path: Path
    returncode: int
    duration_seconds: float
    stdout: str = ""
    stderr: str = ""
    env_overrides: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.output_path.is_file()


def _model_env(workflow: Workflow, model: str) -> dict[str, str]:
    """Build the environment override that selects ``model`` for this run."""
    overrides: dict[str, str] = {}
    spec = workflow.model
    if spec.env_var:
        overrides[spec.env_var] = model
    return overrides


def run_workflow(
    workflow: Workflow,
    model: str,
    *,
    cwd: Path | None = None,
    substitute_cli_arg: bool = True,
    stream_output: bool | None = None,
) -> RunResult:
    """Run ``workflow`` once with ``model``, returning a :class:`RunResult`.

    Supports both command-based execution (shell out to ``run.command``) and
    endpoint-based execution (POST each input record to ``run.endpoint``). The
    contract guarantees exactly one is set.
    """
    run = workflow.run
    cwd = (cwd or Path.cwd()).resolve()

    output_path = (cwd / run.output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Remove a stale output so we never mistake a previous run's results.
    if output_path.exists():
        output_path.unlink()

    if run.endpoint:
        return _run_endpoint(workflow, model, cwd=cwd, output_path=output_path)

    if not workflow.model.has_override():
        raise HarnessError(
            "no model override mechanism is configured",
            hint=(
                "set model.env_var (or model.config_file + model.config_path) so "
                "the workflow can be run under different models; until then run "
                "`driftless configure` to make the workflow migration-ready"
            ),
        )

    command = run.command
    if command is None:
        raise HarnessError(
            "no workflow command is configured",
            hint="set run.command or run.endpoint in the contract",
        )
    if substitute_cli_arg and "{{ model }}" in command:
        command = command.replace("{{ model }}", shlex.quote(model))

    env = os.environ.copy()
    overrides = _model_env(workflow, model)
    env.update(overrides)

    stream = progress_enabled() if stream_output is None else stream_output
    progress_log(
        f"harness: running {workflow.run.command!r} with model={model} "
        f"(output -> {run.output_path})"
    )

    start = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=run.timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise HarnessError(
            f"workflow timed out after {run.timeout_seconds}s",
            hint="increase run.timeout_seconds or speed up the eval command",
        ) from exc
    duration = time.monotonic() - start

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    if stream:
        if stdout:
            sys.stdout.write(stdout)
            if not stdout.endswith("\n"):
                sys.stdout.write("\n")
            sys.stdout.flush()
        if stderr:
            sys.stderr.write(stderr)
            if not stderr.endswith("\n"):
                sys.stderr.write("\n")
            sys.stderr.flush()

    result = RunResult(
        model=model,
        output_path=output_path,
        returncode=proc.returncode,
        duration_seconds=duration,
        stdout=stdout,
        stderr=stderr,
        env_overrides=overrides,
    )

    progress_log(
        f"harness: finished model={model} in {duration:.1f}s "
        f"(exit={proc.returncode})"
    )

    if proc.returncode != 0:
        raise HarnessError(
            f"workflow command exited with code {proc.returncode}",
            hint=_tail(result.stderr) or _tail(result.stdout) or "no output captured",
        )

    if not output_path.is_file():
        raise HarnessError(
            f"workflow did not write expected output: {run.output_path}",
            hint="ensure the command writes results to run.output_path",
        )

    return result


def _http_post(url: str, payload: bytes, headers: dict[str, str], timeout: float) -> str:
    """POST ``payload`` to ``url`` and return the response body text.

    Isolated so tests can stub the network without real sockets.
    """
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        body: bytes = resp.read()
        return str(body.decode("utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HarnessError(
                f"input is not valid JSONL (line {i})",
                hint="each non-empty line of run.input_path must be a JSON object",
            ) from exc
        records.append(obj)
    return records


def _run_endpoint(
    workflow: Workflow, model: str, *, cwd: Path, output_path: Path
) -> RunResult:
    """Execute an endpoint workflow: one POST per input record -> one output line.

    Each input record is sent as JSON with the model injected under
    ``run.model_param`` (default ``"model"``); the JSON response object is written
    as the corresponding output record. When ``eval.id_field`` is set and the
    response omits it, the input's id is copied through so output<->label
    alignment still works.
    """
    run = workflow.run
    input_path = (cwd / run.input_path).resolve()
    if not input_path.is_file():
        raise HarnessError(
            f"input dataset not found: {run.input_path}",
            hint="point run.input_path at your test inputs",
        )

    records = _read_jsonl(input_path)
    model_param = run.model_param or "model"
    id_field = workflow.eval.id_field
    headers = {"Content-Type": "application/json"}
    token = os.environ.get(ENDPOINT_TOKEN_ENV)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    out_lines: list[str] = []
    start = time.monotonic()
    for i, rec in enumerate(records, start=1):
        body = dict(rec)
        body[model_param] = model
        endpoint = run.endpoint
        if endpoint is None:
            raise HarnessError(
                "no endpoint URL is configured",
                hint="set run.endpoint in the contract",
            )
        try:
            text = _http_post(
                endpoint, json.dumps(body).encode("utf-8"), headers, run.timeout_seconds
            )
        except urllib.error.HTTPError as exc:
            raise HarnessError(
                f"endpoint returned HTTP {exc.code} on record {i}",
                hint=_tail(exc.read().decode("utf-8", "replace")) if exc.fp else str(exc),
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HarnessError(
                f"endpoint request failed on record {i}: {run.endpoint}",
                hint=str(getattr(exc, "reason", exc)),
            ) from exc

        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HarnessError(
                f"endpoint returned non-JSON on record {i}",
                hint=_tail(text) or "expected a JSON object per record",
            ) from exc
        if not isinstance(obj, dict):
            raise HarnessError(
                f"endpoint response on record {i} must be a JSON object",
                hint=f"got {type(obj).__name__}",
            )
        if id_field and id_field not in obj and id_field in rec:
            obj[id_field] = rec[id_field]
        out_lines.append(json.dumps(obj))

    duration = time.monotonic() - start
    output_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return RunResult(
        model=model,
        output_path=output_path,
        returncode=0,
        duration_seconds=duration,
        stdout=f"{len(out_lines)} records via {run.endpoint}",
        stderr="",
        env_overrides={},
    )


def check_inputs(workflow: Workflow, *, cwd: Path | None = None) -> Path:
    """Validate that the declared input dataset exists; return its path."""
    cwd = (cwd or Path.cwd()).resolve()
    input_path = (cwd / workflow.run.input_path).resolve()
    if not input_path.is_file():
        raise HarnessError(
            f"input dataset not found: {workflow.run.input_path}",
            hint="point run.input_path at your test inputs",
        )
    return input_path


def _tail(text: str, lines: int = 15) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    return "\n".join(text.splitlines()[-lines:])
