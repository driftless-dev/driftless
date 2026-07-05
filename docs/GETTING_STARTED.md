# Getting Started

The fastest way to understand Driftless is to run a bundled example. No provider
keys are required.

## Try the RAG Example

```bash
python -m venv .venv
source .venv/bin/activate
pip install driftless

driftless copy-example rag-qa --out-dir driftless-rag-demo
cd driftless-rag-demo
driftless validate -w rag_qa
driftless compare -w rag_qa --to gpt-4o-mini
```

Expected shape:

```text
Running gpt-4 (baseline) and gpt-4o-mini (target)...

Metric              Current   Target (orig files)
Score / pass-rate     1.000                 0.000
Total cost            0.072                 0.016

Thresholds (target vs contract):
  FAIL min_score: 0.000 >= 0.86
  PASS max_cost_increase: -77.8% <= +20%
```

The target is cheaper, but it fails the quality bar. That is the core Driftless
loop: measure the model change through the real workflow before changing
production defaults.

## Try the Agent Example

```bash
driftless copy-example tool-agent --out-dir driftless-agent-demo
cd driftless-agent-demo
driftless validate -w support_agent
driftless compare -w support_agent --to gpt-4o-mini
```

The agent example emits trace fields (`tools`, `tool_errors`, `final`) plus a
numeric `score`, so the eval catches bad tool selection even when the final text
sounds plausible.

## Next Commands

After `compare` shows a target regression:

```bash
driftless migrate -w rag_qa --to gpt-4o-mini --generator none
driftless report -w rag_qa
driftless open-pr -w rag_qa
driftless view
```

`--generator none` makes no edits and produces the blocked-report path without
provider keys. Use the default `--generator llm` when you are ready for
provider-backed prompt/config repair.

See [`EXAMPLE_REVIEW_ARTIFACT.md`](./EXAMPLE_REVIEW_ARTIFACT.md) for the issue
body and dry-run GitHub action produced by this flow.

## If A Command Fails

- `workflow did not write expected output`: check `run.output_path` in
  `driftless.yml`. Driftless reads the file your harness writes; update the
  contract if your eval already writes somewhere else.
- `no model override mechanism is configured`: set `model.env_var`, or use
  `model.config_file` plus `model.config_path`, so Driftless can run the same
  workflow under the baseline and target models.
- `input is not valid JSONL`: each non-empty line in `run.input_path` must be one
  JSON object.
- Endpoint `401` or `403`: set `DRIFTLESS_ENDPOINT_TOKEN` if your endpoint
  expects a bearer token. For custom auth headers, wrap the endpoint call in
  `run.command`.
- Provider-backed repair needs provider credentials. The bundled example flow
  works without keys when you use `--generator none`.
