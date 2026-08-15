"""Live OpenAI classifier for the bundled support-classifier-live example.

This harness calls the model. The key-free ``support-classifier`` example does
not. Fail cleanly when ``OPENAI_API_KEY`` is missing.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def prompt_text() -> str:
    return (ROOT / "prompts" / "classifier.md").read_text(encoding="utf-8")


def configured_model() -> str:
    env = os.environ.get("MODEL")
    if env:
        return env
    cfg = ROOT / "config" / "llm.yml"
    if cfg.is_file():
        for line in cfg.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("model:"):
                return stripped.split(":", 1)[1].strip().strip("'\"")
    return "gpt-4o"


def parse_label(text: str) -> str:
    token = (text or "").strip().split()[0] if (text or "").strip() else ""
    return token.strip(".,:;\"'`").lower()


def complete(model: str, system: str, user: str, api_key: str) -> str:
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:400]
        raise SystemExit(f"error: OpenAI HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"error: could not reach OpenAI: {exc.reason}") from exc
    return (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""


def main() -> None:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("error: OPENAI_API_KEY is not set", file=sys.stderr)
        print(
            "hint: this live example calls the model; "
            "use `driftless copy-example support-classifier` for the key-free tour",
            file=sys.stderr,
        )
        raise SystemExit(1)

    model = configured_model()
    system = prompt_text()
    rows = []
    for ticket in load_jsonl(ROOT / "evals" / "tickets.jsonl"):
        output = complete(model, system, ticket["text"], api_key)
        rows.append({"id": ticket["id"], "label": parse_label(output)})

    out = ROOT / "evals" / "outputs.jsonl"
    out.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
