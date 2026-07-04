# RAG QA Example

This is a tiny deterministic retrieval QA workflow for trying Driftless on a
non-classification task. It keeps retrieval/index data fixed and lets Driftless
edit only prompt/config files.

```bash
cd examples/rag-qa
driftless validate -w rag_qa
driftless compare -w rag_qa --to gpt-4o-mini
```

The evaluator writes one JSON object per question with an `answer`, `citations`,
and numeric `score`. In a real app, that score might blend answer correctness,
faithfulness, citation support, and cost. Here it is deterministic so the example
runs without provider keys.
