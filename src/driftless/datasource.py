"""Refresh an *external* eval dataset before the data-change poll.

In-repo datasets need nothing here -- git is the change detector. When the eval
set lives outside the repo (object storage, a labeling tool, a warehouse), the
scheduled ``poll`` calls :func:`fetch_dataset` first so the local files
(``run.input_path`` / ``eval.labels_path``) reflect the latest data before we
fingerprint them.

Two mechanisms, both stdlib-only (no new deps):

* ``data_source.command`` -- your script writes the dataset files. The general
  escape hatch: it can talk to any backend (``aws s3 cp``, a warehouse query, a
  labeling-tool export) exactly like ``run.command`` runs the workflow.
* ``data_source.inputs_url`` / ``labels_url`` -- a plain HTTP(S) GET into the
  configured paths, for the trivial "it's just a file behind a URL" case.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .contract import Workflow
from .errors import HarnessError, DriftlessError

#: Optional bearer token for ``inputs_url`` / ``labels_url`` GETs.
DATASOURCE_TOKEN_ENV = "DRIFTLESS_DATASOURCE_TOKEN"


@dataclass
class FetchResult:
    fetched: bool
    actions: list[str] = field(default_factory=list)


def _http_get(url: str, timeout: float) -> bytes:
    """GET ``url`` (with an optional bearer token); factored out for testing."""
    headers = {}
    token = os.environ.get(DATASOURCE_TOKEN_ENV)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        data: bytes = resp.read()
        return data


def _run_command(command: str, *, cwd: Path, timeout: int) -> None:
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise HarnessError(
            f"data_source.command timed out after {timeout}s",
            hint="raise eval.data_source.timeout_seconds or make the fetch faster",
        ) from exc
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-5:]
        raise HarnessError(
            f"data_source.command failed (exit {proc.returncode})",
            hint="\n".join(tail) or "the fetch command must write the dataset files",
        )


def fetch_dataset(workflow: Workflow, *, cwd: Path | None = None) -> FetchResult:
    """Refresh a workflow's external dataset locally (no-op when not configured)."""
    cwd = (cwd or Path.cwd()).resolve()
    source = workflow.eval.data_source
    if source is None:
        return FetchResult(fetched=False)

    actions: list[str] = []
    if source.command:
        _run_command(source.command, cwd=cwd, timeout=source.timeout_seconds)
        actions.append(f"ran data_source.command: {source.command}")

    if source.inputs_url:
        dest = (cwd / workflow.run.input_path).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_http_get(source.inputs_url, source.timeout_seconds))
        actions.append(f"GET {source.inputs_url} -> {workflow.run.input_path}")

    if source.labels_url:
        if not workflow.eval.labels_path:
            raise DriftlessError(
                "data_source.labels_url is set but eval.labels_path is not",
                hint="set eval.labels_path so fetched labels have a destination",
            )
        dest = (cwd / workflow.eval.labels_path).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_http_get(source.labels_url, source.timeout_seconds))
        actions.append(f"GET {source.labels_url} -> {workflow.eval.labels_path}")

    return FetchResult(fetched=True, actions=actions)
