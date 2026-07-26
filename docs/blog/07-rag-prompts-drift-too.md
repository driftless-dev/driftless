# RAG QA: new answer model, same knowledge base

**Status:** published guide — uses the in-repo deterministic
[`examples/rag-qa`](../../examples/rag-qa) fixture and includes a run-viewer
capture.

## The use case

You ship a retrieval-augmented QA feature: user asks a question, the app
retrieves chunks from a knowledge base, and an LLM writes an answer that should
stay grounded in those chunks and cite them. Quality is measured end-to-end —
not "did the LLM sound plausible?" but "did the answer use the retrieved
context correctly?"

Then you change the generator model (deprecation, cost, or latency). The
**retrieval index stays the same**. On smoke tests the new model still answers
every question. In eval, though, groundedness falls: answers invent details that
were not in the retrieved context, or they drop citations the product requires.
Teams often misread this as "we need to re-embed the corpus" or "RAG is broken."
Usually the failure is in the **generator / retrieval prompt contract** under the
new model — the same prompt-debt pattern as a classifier swap, with a longer
pipeline.

The use case is migrating a RAG *workflow* while holding the index fixed, and
proving the end-to-end eval still passes before you merge.

**What driftless does here:** run the whole RAG pipeline under the candidate
model, score the final answer/citations through your evaluator, and repair only
the prompt/config files you allow — not the embedding store.

Artifact reference:
[`EXAMPLE_SUCCESS_PR.md`](../EXAMPLE_SUCCESS_PR.md) shows the evidence shape and
separates public testbed PR #4 from the different bundled saved success fixture;
the RAG fixture uses the same report and `open-pr` path.

![Browser capture of the Driftless run viewer](../visuals/run-viewer.png)

If you only remember one rule: **RAG migration is not embedding migration.**
Keep the index fixed for this workflow. Let Driftless optimize the generator and
retrieval prompts against the same end-to-end eval your app already uses.

---

## The app

The example is intentionally small and dependency-free:

| Piece | Path |
|-------|------|
| Contract | `examples/rag-qa/driftless.yml` |
| Eval command | `python3 -m app.eval_rag` |
| Knowledge base | `data/docs.jsonl` |
| Fixed index metadata | `data/index_manifest.json` |
| Questions | `evals/questions.jsonl` |
| Gold expectations | `evals/gold.jsonl` |
| Editable prompts | `prompts/rag_answer.md`, `prompts/retrieval_rewrite.md` |

`app.eval_rag` retrieves one support article, generates an answer, and emits one
JSON object per question:

```jsonl
{"id":"q001","answer":"...","citations":["doc-sso"],"score":1.0,"cost":0.018,"retrieved_doc":"doc-sso"}
```

In a real app, `score` might blend answer correctness, citation support,
faithfulness, and context relevance. In this fixture it is deterministic so the
example runs without provider keys.

---

## Reproduce the naive regression

From the repo root:

```bash
cd examples/rag-qa
driftless validate -w rag_qa
driftless compare -w rag_qa --to gpt-4o-mini
```

Actual local output from the fixture:

```text
Running gpt-4 (baseline) and gpt-4o-mini (target)...

┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┓
┃ Metric            ┃ Current ┃ Target (orig files) ┃
┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━┩
│ F1                │     n/a │                 n/a │
│ Precision         │     n/a │                 n/a │
│ Recall            │     n/a │                 n/a │
│ Accuracy          │     n/a │                 n/a │
│ Score / pass-rate │   1.000 │               0.000 │
│ Schema error rate │    0.0% │                0.0% │
│ Refusal rate      │    0.0% │                0.0% │
│ Total cost        │   0.072 │               0.016 │
└───────────────────┴─────────┴─────────────────────┘

Thresholds (target vs contract):
  FAIL min_score: 0.000 >= 0.86
  PASS max_cost_increase: -77.8% <= +20%
```

This is exactly the trap: the candidate is cheaper, but it fails the RAG quality
bar. A cost win is not a migration unless the quality gate still passes.

---

## The contract boundary

The important part of `driftless.yml` is the edit scope:

```yaml
files:
  editable:
    - prompts/rag_answer.md
    - prompts/retrieval_rewrite.md
  readonly:
    - app/
    - data/docs.jsonl
    - data/index_manifest.json
    - evals/questions.jsonl
    - evals/gold.jsonl
```

Driftless can change the prompt instructions. It cannot silently rebuild the
index, change the documents, or rewrite retrieval code.

That boundary keeps the migration reviewable:

| Surface | Driftless role |
|---------|----------------|
| Answer prompt | Editable |
| Retrieval rewrite prompt | Editable |
| Knowledge base | Read-only context |
| Index manifest | Read-only context |
| Eval scorer | Owned by the app |
| Embedding model/index rebuild | Out of scope |

---

## Why `score_field` is enough to start

The workflow uses task-agnostic score mode:

```yaml
eval:
  id_field: id
  score_field: score
  cost_field: cost

thresholds:
  min_score: 0.86
  max_cost_increase: 0.20
```

This is the simplest way to bring RAG under Driftless: your app decides what a
good answer means and emits a number. Driftless aggregates that score, applies
thresholds, and uses the failing rows as repair evidence.

Use `eval.judge` later when quality is semantic and you do not have a reliable
deterministic scorer. Start with a human-calibrated judge check, then optimize.

---

## What a repair should learn

The baseline prompts are intentionally weak:

```markdown
Answer the customer question using the retrieved support article.

Keep the answer concise. If the article seems relevant, summarize the policy in
plain language.
```

For the cheaper model to pass, the prompt needs to become more explicit:

- use only retrieved context;
- cite every factual answer;
- preserve product nouns during retrieval rewriting.

Those are prompt/config changes, not application rewrites. That is the kind of
RAG drift Driftless should handle.

---

## Honest limits

- Do not use this as an embedding-model migration story.
- Do not let the repair loop edit your corpus or index.
- Do not optimize against an uncalibrated judge.
- For agents, emit trace fields (`tools`, `tool_errors`, retrieved docs) so the
  report can explain failures beyond the final answer.

RAG and agent prompts are brittle to model swaps, but the first trustworthy step
is boring in the best way: run the same app, keep the index fixed, measure the
whole pipeline, and review only prompt/config diffs.
