# RAG QA Example

This is a tiny deterministic retrieval QA workflow for trying Driftless on a
non-classification task. It keeps retrieval/index data fixed and lets Driftless
edit only prompt/config files.

Start with the `support-classifier` golden path in the main README. To try this
RAG variant without provider keys:

```bash
driftless copy-example rag-qa --out-dir driftless-rag-demo
cd driftless-rag-demo
driftless validate -w rag_qa
driftless compare -w rag_qa --to gpt-4o-mini
```

The evaluator writes one JSON object per question with an `answer`, `citations`,
and numeric `score`. In a real app, that score might blend answer correctness,
faithfulness, citation support, and cost. Here it is deterministic so the example
runs without provider keys.

The three names accepted by `copy-example` are `support-classifier`, `rag-qa`,
and `tool-agent`.
