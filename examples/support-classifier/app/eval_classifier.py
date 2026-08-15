from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# Closed set the demo gold file uses. ``refund`` is here so a label-change
# refine can retarget billing tickets without editing this harness.
LABELS = ("billing", "technical", "account", "shipping")
KNOWN_LABELS = LABELS + ("refund",)

# Phrasings a real repair LLM actually writes. The old check required the
# exact fixture sentence ``use exact labels only``, which live ``--generator
# llm`` never discovered.
_STRICT_HINTS = (
    "use exact labels only",
    "exact labels only",
    "return only the",
    "return only one",
    "return one of",
    "return the exact",
    "exact category",
    "exact label",
    "choose from",
    "one of the following",
    "one of these",
    "only one of",
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def prompt_text() -> str:
    return (ROOT / "prompts" / "classifier.md").read_text(encoding="utf-8")


def labels_in_prompt(prompt: str) -> list[str]:
    lowered = prompt.lower()
    return [label for label in KNOWN_LABELS if label in lowered]


def prompt_is_strict(prompt: str | None = None) -> bool:
    """True when the prompt names the original taxonomy and demands exact output."""
    text = (prompt if prompt is not None else prompt_text()).lower()
    has_taxonomy = all(label in text for label in LABELS)
    has_hint = any(hint in text for hint in _STRICT_HINTS)
    return has_taxonomy and has_hint


def classify(text: str, allowed: list[str] | None = None) -> str:
    lowered = text.lower()
    if "invoice" in lowered or "charged" in lowered:
        raw = "billing"
    elif "crash" in lowered or "error" in lowered:
        raw = "technical"
    elif "password" in lowered or "login" in lowered:
        raw = "account"
    elif "shipment" in lowered or "delivery" in lowered:
        raw = "shipping"
    else:
        raw = "technical"

    if not allowed:
        return raw
    if raw in allowed:
        return raw
    # Label-change refine: billing tickets follow ``refund`` when billing is gone.
    if raw == "billing" and "refund" in allowed:
        return "refund"
    return allowed[0]


def configured_model() -> str:
    """Prefer MODEL (set by Driftless), then config/llm.yml, then gpt-4."""
    env = os.environ.get("MODEL")
    if env:
        return env
    cfg = ROOT / "config" / "llm.yml"
    if cfg.is_file():
        for line in cfg.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("model:"):
                return stripped.split(":", 1)[1].strip().strip("'\"")
    return "gpt-4"


def main() -> None:
    model = configured_model()
    prompt = prompt_text()
    allowed = labels_in_prompt(prompt)
    strict = prompt_is_strict(prompt)
    rows = []
    for ticket in load_jsonl(ROOT / "evals" / "tickets.jsonl"):
        if "mini" in model and not strict:
            label = "general"
        else:
            label = classify(ticket["text"], allowed)
        rows.append(
            {
                "id": ticket["id"],
                "label": label,
                "cost": 0.001 if "mini" in model else 0.006,
            }
        )

    out = ROOT / "evals" / "outputs.jsonl"
    out.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
