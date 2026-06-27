"""Plain-text progress logs for long-running commands (especially CI).

GitHub Actions only streams step output when the process writes flushed lines.
Rich tables and captured subprocess stdout can leave the UI blank for many
minutes. When progress mode is on we log heartbeat lines to stderr.
"""

from __future__ import annotations

import os
import sys


def enabled() -> bool:
    flag = os.environ.get("DRIFTLESS_PROGRESS", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    return os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CI") == "true"


def log(message: str) -> None:
    if not enabled():
        return
    print(message, file=sys.stderr, flush=True)
