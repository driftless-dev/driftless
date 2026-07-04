# RAG and Agent Workflows

Driftless can evaluate RAG and agentic systems today because it treats the
application as the unit under test. The workflow stays inside your command or
endpoint; Driftless only swaps the model, edits the files you mark editable, and
scores the resulting behavior.

The useful boundary is:

- **Driftless edits** prompts, planner instructions, tool descriptions, routing
  rules, and other text/config files in `files.editable`.
- **Driftless measures** the full pipeline output: retrieval, tool calls,
  generation, citations, and final answer quality.
- **Driftless does not rebuild** embedding indexes or migrate embedding models.
  Treat that as a separate data-pipeline change.

## Minimal RAG QA Contract

This example assumes your app reads `evals/questions.jsonl`, runs retrieval and
answer generation, and writes one JSON object per line to
`evals/outputs.jsonl`.

```yaml
workflows:
  rag_qa:
    model:
      current: gpt-4
      target_candidates: [gpt-4o, gpt-4o-mini]
      env_var: MODEL

    files:
      editable:
        - prompts/rag_answer.md
        - prompts/retrieval_rewrite.md
      readonly:
        - app/
        - evals/questions.jsonl
        - evals/gold.jsonl
        - data/index_manifest.json

    run:
      command: python3 -m app.eval_rag
      input_path: evals/questions.jsonl
      output_path: evals/outputs.jsonl

    eval:
      id_field: id
      score_field: score
      split:
        tuning: 60%
        holdout: 40%

    thresholds:
      min_score: 0.86
      max_cost_increase: 0.05
```

See [`examples/rag-qa`](../examples/rag-qa) for a runnable version of this
contract. It uses a fixed JSONL knowledge base and deterministic scoring so you
can run it without provider keys.

The command owns retrieval. Driftless only needs a stable output field to
optimize against:

```jsonl
{"id":"q001","answer":"...","citations":["doc-7"],"score":0.94,"cost":0.012}
{"id":"q002","answer":"...","citations":["doc-3","doc-4"],"score":0.78,"cost":0.010}
```

If your evaluator already computes faithfulness, citation support, or answer
correctness, emit a single blended `score` field. That is the simplest path and
keeps the grading logic in your repo.

## Judge-Graded RAG

When you do not have a deterministic scorer, use `eval.judge` with a calibration
set. The calibration set should contain human scores for representative answers,
including bad citations and unsupported claims.

```yaml
eval:
  id_field: id
  judge:
    rubric: |
      Grade the answer from 0 to 5.
      Award credit for answering the question correctly, using only the supplied
      context, and citing every factual claim. Penalize unsupported claims,
      missing citations, and irrelevant retrieved context.
    scale_max: 5
    input_field: question
    output_field: answer
    calibration_path: evals/judge_calibration.jsonl
    max_mae: 0.15
    min_correlation: 0.70
```

Run the judge check before optimizing:

```bash
driftless judge-check -w rag_qa --enforce
driftless migrate -w rag_qa --to gpt-4o-mini
```

Use judge mode when the quality bar is inherently semantic. Use `score_field`
when you can compute a trustworthy score yourself.

## Agent Outputs

For agents, preserve enough trace data in each output row to diagnose failures:

```jsonl
{"id":"a001","final":"Refund issued.","tools":["lookup_order","check_policy","refund_payment"],"tool_errors":[],"score":1.0}
{"id":"a002","final":"Refund not issued.","tools":["refund_payment"],"tool_errors":["missing_lookup_order","missing_check_policy"],"score":0.0}
```

The first useful agent examples should keep execution local or inside CI. Hosted
agent execution needs stronger sandboxing because tool calls can mutate real
systems.

See [`examples/tool-agent`](../examples/tool-agent) for a side-effect-free
version. Its tools are local fixture functions, and the workflow can only edit
planner/tool-description prompts:

```yaml
files:
  editable:
    - prompts/planner.md
    - prompts/tool_descriptions.md
  readonly:
    - app/
    - data/orders.jsonl
    - data/policies.json
    - evals/cases.jsonl
    - evals/gold.jsonl

eval:
  id_field: id
  score_field: score
  cost_field: cost
```

## Recommended Example Sequence

1. **RAG QA demo** — optimize answer/retrieval prompts against a blended score or
   calibrated judge. Keep embeddings and index rebuilds fixed.
2. **Tool-selection agent demo** — optimize planner/tool descriptions while the
   app emits final score plus trace fields.
3. **Budgeted agent evals** — add sampling and run-budget guidance once examples
   become expensive enough to need it.
