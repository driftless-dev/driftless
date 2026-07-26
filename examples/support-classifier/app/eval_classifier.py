from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LABELS = ("billing", "technical", "account", "shipping")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def prompt_is_strict() -> bool:
    prompt = (ROOT / "prompts" / "classifier.md").read_text(encoding="utf-8").lower()
    return "use exact labels only" in prompt and ", ".join(LABELS) in prompt


def classify(text: str) -> str:
    lowered = text.lower()
    if "invoice" in lowered or "charged" in lowered:
        return "billing"
    if "crash" in lowered or "error" in lowered:
        return "technical"
    if "password" in lowered or "login" in lowered:
        return "account"
    if "shipment" in lowered or "delivery" in lowered:
        return "shipping"
    return "technical"


def main() -> None:
    model = os.environ.get("MODEL", "gpt-4")
    strict = prompt_is_strict()
    rows = []
    for ticket in load_jsonl(ROOT / "evals" / "tickets.jsonl"):
        if "mini" in model and not strict:
            label = "general"
        else:
            label = classify(ticket["text"])
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

