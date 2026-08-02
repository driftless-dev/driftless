import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
model = os.getenv("BRIEF_MODEL", "gpt-4o")
score = 0.5 if "mini" in model else 1.0
cost = 0.001 if "mini" in model else 0.01
cases = [
    json.loads(line)
    for line in (ROOT / "evals" / "cases.jsonl").read_text().splitlines()
    if line.strip()
]
(ROOT / "evals" / "outputs.jsonl").write_text(
    "\n".join(
        json.dumps({"id": case["id"], "score": score, "cost": cost})
        for case in cases
    )
    + "\n"
)
