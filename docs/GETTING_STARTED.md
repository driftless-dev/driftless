# Getting Started

The fastest way to understand Driftless is to run a bundled example. You do not
need an API key.

If a word is new, jump to [Words used here](#words-used-here). For “which
command do I want?”, use the [command chooser](./COMMAND_CHOOSER.md).

## Golden path: support classifier

This example is a tiny ticket classifier. The cheaper target model is
**supposed** to fail the quality gate until a known-good prompt patch is
applied.

### 1. Install and copy the example

```bash
pip install driftless

driftless copy-example support-classifier --out-dir driftless-classifier-demo
cd driftless-classifier-demo
```

Python 3.10 or newer. `copy-example` writes a small project you can throw away.

### 2. Check the wiring, then compare models

`-w support_classifier` is the workflow name inside `driftless.yml`.

```bash
driftless validate -w support_classifier
driftless compare -w support_classifier --to gpt-4o-mini
```

`validate` runs your eval command once to prove the contract works. `compare`
runs the **current** model and **gpt-4o-mini** on the same four rows, and does
not edit any files.

You should see:

```text
Running gpt-4 (baseline) and gpt-4o-mini (target)...

Metric              Current   Target (orig files)
F1                    1.000                 0.000
Total cost            0.024                 0.004

Thresholds (target vs contract):
  FAIL min_f1: 0.000 >= 0.9
```

In plain language: the cheap model scored **0.000** F1, you required **at least
0.9**, so Driftless will not treat a bare model swap as shippable. Cost went
down; quality did not. That is the demo working.

### 3. Blocked path (no prompt edits)

```bash
driftless migrate -w support_classifier --to gpt-4o-mini --generator none
driftless report -w support_classifier
driftless open-pr -w support_classifier
```

`--generator none` means “do not change the prompt.” `migrate` is expected to
exit **non-zero** with `BLOCKED`. That is success for this step — run `report`
and `open-pr` afterward anyway. `open-pr` only prints what it would open unless
you add `--create`.

### 4. Passing path (bundled patch, still no API key)

```bash
driftless migrate -w support_classifier --to gpt-4o-mini --generator fixture
driftless report -w support_classifier
driftless open-pr -w support_classifier
```

`--generator fixture` applies the known-good patch shipped with this example.
Expect `PASS`. This proves the published CLI can produce a passing evidence
artifact. It is not a general optimizer — real apps use `--generator llm` and
need a provider key. On this example, a prompt that lists the four labels and
says to return only those labels is enough; `llm` can learn that phrasing.

The four-row set is still too small to trust as production evidence. See
[eval confidence](./CONFIDENCE.md).

## Words used here

| Term | Meaning |
|---|---|
| **Workflow** | One LLM task (`support_classifier` in the example). |
| **Contract** | `driftless.yml` — command, model override, editable files, thresholds. |
| **Harness** | The command in `run.command` that writes JSONL (one JSON object per line). |
| **Compare** | Score current vs target model. No file edits. |
| **Migrate** | Try to repair allowed files so the target still meets the bar. |
| **Generator** | Who writes the repair: `none` (no edits), `fixture` (this demo’s patch), `llm` (calls OpenAI or Anthropic). |
| **Holdout** | Eval rows kept back for a final check. The repair loop does not tune on them. |
| **Thresholds** | Numbers in the contract such as `min_f1: 0.9` that a candidate must beat. |

## Other bundled examples

```bash
driftless copy-example support-classifier
driftless copy-example rag-qa
driftless copy-example tool-agent
```

- **rag-qa** — retrieval QA. Retrieval stays fixed; Driftless may edit prompts.
- **tool-agent** — a fake local agent. The eval records which tools were chosen,
  so a fluent wrong tool call still fails.

Same compare → `--generator none` (blocked) → `--generator fixture` (pass)
pattern as above, with a different `-w` name (`rag_qa` or `support_agent`).

## Adopt Driftless in an existing repository

The bundled example is a product tour. For a repo that already has an LLM
workflow, you still have to bring the eval. Driftless will not invent one.

### Checklist (you own these)

1. **Eval command** — a repeatable harness that writes JSONL to `run.output_path`.
2. **Model override** — `model.env_var` or `model.config_file` + `model.config_path`.
3. **Editable scope** — exact file paths in `files.editable`; everything else is read-only.
4. **Labels or scorer** — `eval.labels_path` / `score_field` / `pass_field` / `judge`.
5. **Thresholds** — start from `calibrate`, then review; do not auto-accept.
6. **Credentials and budget** — provider keys only for `--generator llm` / judges;
   see [`.env.example`](../.env.example) and [`COST_AND_BUDGETS.md`](./COST_AND_BUDGETS.md).
7. **Sandbox** — agent tools and `run.command` execute in *your* CI. Review the
   contract like any other workflow that can run shell.

A complete application built before Driftless was added is available at
[`alexminnaar/incident-brief-driftless-battletest`](https://github.com/alexminnaar/incident-brief-driftless-battletest).

```bash
cd your-existing-repo
driftless scan
driftless configure <workflow> --apply
```

`scan` looks for model usage. `configure` writes a reviewable draft at
`.driftless/configure/<workflow>.yml`. With `--apply`, it also creates
`driftless.yml` or appends a new workflow without rewriting existing comments.
It prefills description, harness paths, model/env, a cheaper same-provider
target when known, and common readonly trees. Without `--apply`, copy the
reviewed workflow block manually. Driftless refuses to load a contract while
`TODO` or `<placeholder>` values remain.

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

**Only paths listed in `files.editable` may be changed.** A directory in
`files.readonly` is a documented “do not touch” zone; everything not named as
an exact editable path is already off-limits. Use `files.context` for parser or
schema files the generator should *read* but never edit. Avoid broad editable
directories and globs.

### 2. Validate before spending provider tokens

```bash
driftless validate -w support_summary
driftless calibrate -w support_summary
driftless compare -w support_summary --to gpt-4o-mini
driftless compare -w support_summary --to gpt-4o-mini --enforce  # CI gate
```

`validate` runs the harness unless you pass `--no-run`. `calibrate` measures the
current model and *suggests* thresholds — review them, do not treat them as
automatic policy. `compare` runs current and target models, so it can cost
money if your harness calls live APIs. Start small; see
[`COST_AND_BUDGETS.md`](./COST_AND_BUDGETS.md) before scaling.

### 3. Repair only after the boundary and budget are approved

```bash
# No edits, no API key: records BLOCKED evidence.
driftless migrate -w support_summary --to gpt-4o-mini --generator none

# Bundled examples only (not this workflow):
# driftless migrate -w support_classifier --to gpt-4o-mini --generator fixture

# Paid repair — needs a key:
export OPENAI_API_KEY=...  # or ANTHROPIC_API_KEY
driftless migrate -w support_summary --to gpt-4o-mini --generator llm
driftless report -w support_summary
driftless view -w support_summary
driftless open-pr -w support_summary       # dry run
```

A passing tuning candidate is not enough: keep `holdout_required: true`, inspect
every editable-file diff, and never put application code, schemas, eval labels,
secrets, or side-effecting tool config in `files.editable`.

`open-pr` does nothing on GitHub unless you pass `--create`. Add generated CI
only after local validation looks right:

```bash
driftless init-ci --setup-command 'pip install -e ".[dev]"'
```

The setup command must install *your* app and eval dependencies. The Driftless
Action installs Driftless, not your project. Review the generated workflow
before committing. Refinement stays manual unless you pass `--refine-on-push`.

See [`EXAMPLE_REVIEW_ARTIFACT.md`](./EXAMPLE_REVIEW_ARTIFACT.md) for a sample
blocked-path issue body.

## If a command fails

- `workflow did not write expected output`: the harness must write the file
  named in `run.output_path`. Point the contract at wherever your eval already
  writes.
- `no model override mechanism is configured`: set `model.env_var`, or
  `model.config_file` plus `model.config_path`, so Driftless can rerun the same
  command under a different model.
- `input is not valid JSONL`: each non-empty line in `run.input_path` must be
  one JSON object.
- Endpoint `401` or `403`: set `DRIFTLESS_ENDPOINT_TOKEN` if the endpoint wants
  a bearer token. For custom headers, wrap the call in `run.command`.
- Provider-backed repair needs provider credentials. Bundled examples work
  without keys using `--generator none` (blocked) or `--generator fixture`
  (passing). Do not use `fixture` on your own workflow.

## Upgrading from 0.2.x

Version 0.3.0 rejects legacy `migration.allow_*` fields. Update each contract
to exact paths in `files.editable` before installing 0.3. See
[Upgrading Driftless](./UPGRADING.md).
