# Tool Agent Example

This is a deterministic, side-effect-free agent workflow for trying Driftless on
tool selection. The "tools" are local functions over fixture data; no real
refunds, emails, or account changes happen.

Start with the `support-classifier` golden path in the main README. To try this
agent variant without provider keys:

```bash
driftless copy-example tool-agent --out-dir driftless-agent-demo
cd driftless-agent-demo
driftless validate -w support_agent
driftless compare -w support_agent --to gpt-4o-mini
```

The evaluator writes one JSON object per case with a final answer, selected
tools, tool errors, numeric `score`, and `cost`. In a real agent, the same shape
can carry planner traces, tool arguments, retrieved docs, and retry history.

The three names accepted by `copy-example` are `support-classifier`, `rag-qa`,
and `tool-agent`.

