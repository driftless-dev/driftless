"""Local web UI for inspecting migration / refine run artifacts."""

from __future__ import annotations

import json
import mimetypes
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .errors import DriftlessError


def site_root() -> Path:
    """Return the bundled static site directory."""
    bundled = Path(__file__).resolve().parent / "site"
    if bundled.is_dir():
        return bundled
    # Editable install: repo-root site/
    return Path(__file__).resolve().parents[2] / "site"


def _list_runs(cwd: Path) -> list[dict]:
    mig_dir = cwd / ".driftless" / "migrations"
    if not mig_dir.is_dir():
        return []
    runs: list[dict] = []
    for path in sorted(mig_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        runs.append(
            {
                "workflow": data.get("workflow", path.stem),
                "status": data.get("status", "unknown"),
                "path": str(path),
            }
        )
    return runs


class RunViewerHandler(SimpleHTTPRequestHandler):
    """Serve the static site and expose migration JSON from the project cwd."""

    def __init__(
        self,
        *args,
        site_dir: Path,
        project_dir: Path,
        **kwargs,
    ) -> None:
        self.site_dir = site_dir.resolve()
        self.project_dir = project_dir.resolve()
        super().__init__(*args, directory=str(self.site_dir), **kwargs)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        # Quieter than default stderr logging during local dev.
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path == "/api/runs":
            body = json.dumps(_list_runs(self.project_dir)).encode("utf-8")
            self._send_bytes(body, "application/json")
            return

        if path.startswith("/api/runs/"):
            workflow = path[len("/api/runs/") :].removesuffix(".json")
            json_path = self.project_dir / ".driftless" / "migrations" / f"{workflow}.json"
            if not json_path.is_file():
                self.send_error(404, "run not found")
                return
            self._send_bytes(json_path.read_bytes(), "application/json")
            return

        if path in ("", "/"):
            self.path = "/runs.html"
        super().do_GET()

    def _send_bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def guess_type(self, path: str) -> str:
        ctype = super().guess_type(path)
        if ctype.startswith("text/") or path.endswith(".js"):
            return ctype + "; charset=utf-8"
        return ctype


def serve_runs(
    *,
    cwd: Path | None = None,
    port: int = 8777,
    open_browser: bool = True,
    workflow: str | None = None,
) -> None:
    """Start a local server for the run viewer UI."""
    cwd = (cwd or Path.cwd()).resolve()
    site = site_root()
    if not site.is_dir():
        raise DriftlessError(
            "run viewer assets not found",
            hint="reinstall driftless or run from the repo checkout",
        )

    runs = _list_runs(cwd)
    handler = partial(RunViewerHandler, site_dir=site, project_dir=cwd)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)

    url = f"http://127.0.0.1:{port}/runs.html"
    if workflow:
        url += f"?workflow={workflow}"

    print(f"Run viewer: {url}")
    if runs:
        names = ", ".join(r["workflow"] for r in runs)
        print(f"Loaded {len(runs)} run(s) from {cwd / '.driftless' / 'migrations'}: {names}")
    else:
        print(f"No runs in {cwd / '.driftless' / 'migrations'} — use Load JSON or run migrate/refine first")

    if open_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
