from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}


def retrieve(question: str, docs: list[dict[str, Any]]) -> dict[str, Any]:
    q = tokens(question)
    return max(docs, key=lambda doc: len(q & tokens(doc["text"])))


def prompt_is_grounded() -> bool:
    answer_prompt = (ROOT / "prompts" / "rag_answer.md").read_text().lower()
    retrieval_prompt = (ROOT / "prompts" / "retrieval_rewrite.md").read_text().lower()
    return (
        "use only retrieved context" in answer_prompt
        and "cite every factual answer" in answer_prompt
        and "preserve product nouns" in retrieval_prompt
    )


def answer_for(model: str, question: dict[str, Any], doc: dict[str, Any], grounded: bool) -> tuple[str, list[str]]:
    if "mini" in model and not grounded:
        return (
            "The customer can use the standard support workflow. "
            "If unsure, ask an administrator to confirm the latest policy.",
            [],
        )
    return f"{doc['answer']} [{doc['id']}]", [doc["id"]]


def score(answer: str, citations: list[str], gold: dict[str, Any]) -> float:
    answer_text = answer.lower()
    term_hits = sum(1 for term in gold["required_terms"] if term.lower() in answer_text)
    term_score = term_hits / len(gold["required_terms"])
    citation_score = 1.0 if set(gold["required_citations"]).issubset(citations) else 0.0
    return round((0.75 * term_score) + (0.25 * citation_score), 3)


def main() -> None:
    model = os.environ.get("MODEL", "gpt-4")
    docs = load_jsonl(ROOT / "data" / "docs.jsonl")
    questions = load_jsonl(ROOT / "evals" / "questions.jsonl")
    gold_by_id = {row["id"]: row for row in load_jsonl(ROOT / "evals" / "gold.jsonl")}
    grounded = prompt_is_grounded()

    out = ROOT / "evals" / "outputs.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for question in questions:
        doc = retrieve(question["question"], docs)
        answer, citations = answer_for(model, question, doc, grounded)
        rows.append(
            {
                "id": question["id"],
                "answer": answer,
                "citations": citations,
                "score": score(answer, citations, gold_by_id[question["id"]]),
                "cost": 0.004 if "mini" in model else 0.018,
                "retrieved_doc": doc["id"],
            }
        )

    out.write_text("\n".join(json.dumps(row) for row in rows) + "\n")


if __name__ == "__main__":
    main()

