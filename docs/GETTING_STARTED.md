# Getting Started

The fastest way to understand Driftless is to run a bundled example. No provider
keys are required.

> **Upgrading from 0.2.x?** Version 0.3.0 rejects legacy
> `migration.allow_*` fields. Update each contract to use exact paths in
> `files.editable` before installing it; see [Upgrading Driftless](./UPGRADING.md)
> for before/after YAML and the complete edit-policy rules.

## Golden Path: Support Classifier

```bash
pip install driftless

driftless copy-example support-classifier --out-dir driftless-classifier-demo
cd driftless-classifier-demo
driftless validate -w support_classifier
driftless compare -w support_classifier --to gpt-4o-mini
```

This is the smallest gold-label path: a deterministic ticket classifier with
macro-F1 thresholds and cost tracking. The comparison intentionally produces:

```text
Running gpt-4 (baseline) and gpt-4o-mini (target)...

Metric              Current   Target (orig files)
F1                    1.000                 0.000
Total cost            0.024                 0.004

Thresholds (target vs contract):
  FAIL min_f1: 0.000 >= 0.9
```

The output is deliberate: the target costs less, but its classifier output
drifts and fails the quality bar. Driftless therefore prevents a cheap but
unsafe model swap.

Continue through the key-free blocked path:

```bash
driftless migrate -w support_classifier --to gpt-4o-mini --generator none
driftless report -w support_classifier
driftless open-pr -w support_classifier
```

`migrate` is expected to exit non-zero with `BLOCKED`; run the next commands
afterward. `--generator none` makes no edits and needs no provider credentials.
`report` renders the evidence saved by the migration, and `open-pr` previews the
issue it would create. It is a dry run unless you add `--create`.

## Other Bundled Examples

`copy-example` includes all three examples:

```bash
driftless copy-example support-classifier
driftless copy-example rag-qa
driftless copy-example tool-agent
```

The RAG example uses numeric score/pass-rate grading. The tool-agent example
emits trace fields (`tools`, `tool_errors`, `final`) so its eval catches bad tool
selection even when the final text sounds plausible.

## Adopt Driftless in an Existing Repository

The bundled example is the fastest product tour. For a repository that already
contains an LLM workflow, discover it and scaffold a contract separately:

```bash
cd your-existing-repo
driftless scan
driftless configure <workflow>
driftless validate -w <workflow>
driftless compare -w <workflow> --to <model>
```

See [`EXAMPLE_REVIEW_ARTIFACT.md`](./EXAMPLE_REVIEW_ARTIFACT.md) for an example
issue body and dry-run GitHub action produced by the same blocked path.

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
