# RAG QA Example

This is a tiny deterministic retrieval QA workflow for trying Driftless on a
non-classification task. It keeps retrieval/index data fixed and lets Driftless
edit only prompt/config files.

Start with the `support-classifier` golden path in the main README. To try this
RAG variant without provider keys:

```bash
pip install driftless
driftless copy-example rag-qa --out-dir driftless-rag-demo
cd driftless-rag-demo
driftless validate -w rag_qa
driftless compare -w rag_qa --to gpt-4o-mini
```

The evaluator writes one JSON object per question with an `answer`, `citations`,
and numeric `score`. In a real app, that score might blend answer correctness,
faithfulness, citation support, and cost. Here it is deterministic so the example
runs without provider keys.

Same key-free loop as the classifier: `--generator none` should `BLOCKED`,
`--generator fixture` should `PASS`. `--generator llm` is refused here;
the harness does not call a model. For a live OpenAI eval, use
`copy-example support-classifier-live`.

```bash
driftless migrate -w rag_qa --to gpt-4o-mini --generator none
driftless migrate -w rag_qa --to gpt-4o-mini --generator fixture
```

The names accepted by `copy-example` are `support-classifier`,
`support-classifier-live`, `rag-qa`, and `tool-agent`.
