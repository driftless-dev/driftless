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
contains an LLM workflow, use this guided path. It keeps discovery, contract
editing, paid repair, and CI as separate review points.

A complete application built before Driftless was added is available at
[`alexminnaar/incident-brief-driftless-battletest`](https://github.com/alexminnaar/incident-brief-driftless-battletest).
The in-repository `tests/fixtures/adoption-app` fixture and
`scripts/battletest-new-repo.sh` continuously exercise the same adoption shape
against built wheels.

```bash
cd your-existing-repo
driftless scan
driftless configure <workflow> --apply
```

`configure` writes a reviewable draft at
`.driftless/configure/<workflow>.yml`. With `--apply`, it also creates
`driftless.yml` or appends a new workflow without rewriting existing comments.
Without `--apply`, copy the reviewed workflow block manually. Driftless refuses
to load a contract while `TODO` or `<placeholder>` values remain.

### 1. Turn the draft into a concrete contract

Suppose the application currently calls `gpt-4` from
`python evals/run_summary.py`, the harness writes JSONL to
`evals/summary.outputs.jsonl`, and only `prompts/summary.md` is safe for an
optimizer to change.

An incomplete generated draft might look like:

```yaml
workflows:
  support_summary:
    run:
      command: TODO
      input_path: TODO
      output_path: TODO
    model:
      current: TODO
      env_var: TODO
    files:
      editable: [TODO]
    thresholds:
      min_score: TODO
```

Replace the placeholders with values that match the real harness, then merge
this reviewed block into root `driftless.yml`:

```yaml
workflows:
  support_summary:
    run:
      command: python evals/run_summary.py
      input_path: evals/summary.inputs.jsonl
      output_path: evals/summary.outputs.jsonl
    model:
      current: gpt-4
      target_candidates: [gpt-4o-mini]
      env_var: SUMMARY_MODEL
    files:
      editable:
        - prompts/summary.md
      context:
        - src/summary_parser.py
        - schemas/summary.schema.json
      readonly:
        - src/
        - schemas/
        - evals/
    eval:
      id_field: id
      score_field: score
      cost_field: cost
    thresholds:
      min_score: 0.90
      max_schema_error_rate: 0.02
      max_cost_increase: 0.20
    migration:
      holdout_required: true
      max_iterations: 3
```

The write contract is exact: **only paths listed in `files.editable` may be
changed**. A directory in `files.readonly` documents a non-editable boundary,
but it does not grant or subtract write access; everything not named by an exact
editable file path is already outside repair scope. Use `files.context` for
parser, schema, or product-policy files the generator should read while
reasoning but must never edit. Avoid broad editable directories and globs.

### 2. Validate before spending provider tokens

```bash
driftless validate -w support_summary
driftless calibrate -w support_summary
driftless compare -w support_summary --to gpt-4o-mini
driftless compare -w support_summary --to gpt-4o-mini --enforce  # CI gate
```

`validate` runs the harness unless you pass `--no-run`. `calibrate` measures the
current baseline and suggests thresholds; review those suggestions rather than
treating them as an automatic safety policy. `compare` runs the current and
target models, so it can incur provider cost when your harness calls live APIs.
Start with a small representative eval, inspect estimated/measured cost, and see
[`COST_AND_BUDGETS.md`](./COST_AND_BUDGETS.md) before scaling.

### 3. Repair only after the boundary and budget are approved

```bash
# Key-free orchestration check: records BLOCKED evidence and makes no repair.
driftless migrate -w support_summary --to gpt-4o-mini --generator none

# Paid, nondeterministic repair:
export OPENAI_API_KEY=...  # or ANTHROPIC_API_KEY
driftless migrate -w support_summary --to gpt-4o-mini --generator llm
driftless report -w support_summary
driftless view -w support_summary
driftless open-pr -w support_summary       # dry run
```

Provider-backed repair requires credentials and multiplies harness cost across
tuning rows, candidates, and iterations. A passing tuning candidate is not
enough: keep `holdout_required: true`, inspect every editable-file diff, and
never add application code, schemas, eval labels, secrets, or side-effecting
tool configuration to `files.editable`.

`open-pr` has no GitHub side effect unless `--create` is supplied. Add generated
CI only after local validation, cost review, and a dry-run artifact are
acceptable:

```bash
driftless init-ci --setup-command 'pip install -e ".[dev]"'
```

Generated refinement is manual by default. Add `--refine-on-push` only when
automatic provider spend on eval-file changes is intentional. The setup command
must install your application and eval-harness dependencies. `init-ci` infers
common Python and npm commands from repository manifests; review the generated
step and override it when needed. The Driftless Action installs Driftless and
its repair-provider SDKs, not your project.

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
