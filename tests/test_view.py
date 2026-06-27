"""Tests for the run viewer server helpers."""

from __future__ import annotations

import json
from pathlib import Path

from driftless.view import RunViewerHandler, _list_runs, site_root


def test_site_root_exists() -> None:
    assert site_root().is_dir()
    assert (site_root() / "runs.html").is_file()


def test_list_runs_reads_migration_json(tmp_path: Path) -> None:
    mig = tmp_path / ".driftless" / "migrations"
    mig.mkdir(parents=True)
    (mig / "demo.json").write_text(
        json.dumps({"workflow": "demo", "status": "pass"}),
        encoding="utf-8",
    )
    runs = _list_runs(tmp_path)
    assert len(runs) == 1
    assert runs[0]["workflow"] == "demo"
    assert runs[0]["status"] == "pass"


def test_api_runs_endpoint(tmp_path: Path) -> None:
    mig = tmp_path / ".driftless" / "migrations"
    mig.mkdir(parents=True)
    payload = {"workflow": "wf1", "status": "blocked", "experiment_log": []}
    (mig / "wf1.json").write_text(json.dumps(payload), encoding="utf-8")

    site = site_root()
    import socket
    from http.server import ThreadingHTTPServer
    from functools import partial

    handler = partial(RunViewerHandler, site_dir=site, project_dir=tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]

    import threading
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/runs") as resp:
            listing = json.loads(resp.read())
        assert listing[0]["workflow"] == "wf1"

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/runs/wf1") as resp:
            data = json.loads(resp.read())
        assert data["status"] == "blocked"
    finally:
        server.shutdown()
        server.server_close()
