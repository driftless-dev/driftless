# driftless

When you change the model behind an LLM app, the prompt that used to work often
stops working. Driftless runs **your** eval on the old model and the new one,
repairs only the files you allow, and opens a pull request with the evidence —
or **blocks** the change if quality drops.

You need an eval you can run from the command line. The bundled demo needs no
API key. Automatic prompt repair on a real workflow does.

> If you know Poetry and Dependabot: `driftless.yml` is the manifest (model +
> eval dataset), the prompt is the lockfile, and delivery is a gated PR. LLM
> behavior is empirical, so Driftless scores candidates on your eval instead of
> resolving versions.

> Status: **public alpha** — `0.3.x` on [PyPI](https://pypi.org/project/driftless/).
> Upgrading from 0.2.x? Follow the [upgrade guide](https://github.com/driftless-dev/driftless/blob/main/docs/UPGRADING.md) first.

## Install

```bash
pip install driftless
```

Python 3.10 or newer. No API key for the steps below.

## Quickstart

Copy the bundled support-classifier example and run it. `-w` is the workflow
name from `driftless.yml`.

```bash
driftless copy-example support-classifier --out-dir driftless-classifier-demo
cd driftless-classifier-demo
driftless validate -w support_classifier
driftless compare -w support_classifier --to gpt-4o-mini
```

`validate` checks that the project is wired correctly. `compare` runs the
**current** model and the **cheaper target** on the same tiny eval. You should
see something like:

```text
F1          current 1.000   target 0.000
Total cost  current 0.024   target 0.004
FAIL min_f1: 0.000 >= 0.9
```

Read that last line as: the new model scored **0.000**, you required **at least
0.9**, so the cheaper swap is **not safe to ship**. That failure is the point of
the demo.

Continue without API keys. `--generator none` makes **no** prompt edits, so
migration stays blocked. `--generator fixture` applies the known-good patch
shipped with this example and can pass.

```bash
driftless migrate -w support_classifier --to gpt-4o-mini --generator none
# Expected: BLOCKED, non-zero exit. Run the next commands anyway.

driftless migrate -w support_classifier --to gpt-4o-mini --generator fixture
# Expected: PASS — bundled patch, still no API key.

driftless report -w support_classifier
driftless open-pr -w support_classifier
# Dry run: prints what it would open. Add --create only when you mean it.
```

> **This demo has only 4 eval rows.** It proves install, gating, and a
> key-free pass/block loop. It is not production evidence. For a real
> workflow use a representative eval and `--generator llm` (needs a provider
> key). See [eval confidence](https://github.com/driftless-dev/driftless/blob/main/docs/CONFIDENCE.md).

### Words you'll see

| Term | Meaning |
|---|---|
| **Workflow** | One LLM task in the repo (classifier, RAG answerer, agent). |
| **Contract** | `driftless.yml` — how to run the task, what may be edited, what “good” means. |
| **Harness** | Your command that runs the task and writes one JSON object per line. |
| **Generator** | Who writes the repair: `none` (no edits), `fixture` (bundled demo patch), `llm` (calls a provider). |
| **Holdout** | Eval rows saved for a final check; the repair loop never trains on them. |

## Product proof

This is the actual output of the cold-install quickstart:

![Terminal output from Driftless compare showing a cheaper target blocked by the F1 gate](https://raw.githubusercontent.com/driftless-dev/driftless/main/docs/visuals/compare-terminal.png)

A larger offline migration was also run against the public
[`support-classifier-svc`](https://github.com/driftless-dev/support-classifier-svc)
testbed. It produced [draft PR #4](https://github.com/driftless-dev/support-classifier-svc/pull/4)
with the generated scorecard, holdout evidence, prompt diff, and model update:

![Real GitHub pull request created from a passing Driftless migration](https://raw.githubusercontent.com/driftless-dev/driftless/main/docs/visuals/github-migration-pr.png)

PR #4 is historical proof of a 290-label testbed run. The published CLI
reproduces a passing four-row repair with `--generator fixture`; regenerating
PR #4's exact patch still needs provider-backed `--generator llm` (or the
testbed's own simulator) and may differ.

Other bundled examples:

```bash
driftless copy-example support-classifier-live
driftless copy-example rag-qa
driftless copy-example tool-agent
```

To put Driftless on an existing app, follow the
[existing-repository walkthrough](https://github.com/driftless-dev/driftless/blob/main/docs/GETTING_STARTED.md#adopt-driftless-in-an-existing-repository).
Start with `scan` and `configure --apply`, then review the draft contract
before repair or CI.

## How it works

You describe the workflow once in `driftless.yml`: the command that runs it,
how to switch models, which files may be edited, and the quality bar. Driftless
runs **your** command under different models, compares results, repairs only
allowed files, checks the winner on holdout data, and opens a PR with the
evidence.

You own the workflow. Driftless orchestrates it.

Not a classifier? Pick a grading mode that matches the task:

- **`eval.score_field` / `eval.pass_field`** — your command emits a numeric score
  or a pass/fail per record (summarization, codegen, agents).
- **`eval.fields`** — structured extraction, scored per field against gold labels.
- **`eval.judge`** — an LLM grades free-form output against a rubric. Run
  `driftless judge-check -w <workflow>` before optimizing.

<details>
<summary>CLI reference</summary>

| Command | Purpose |
|---|---|
| `copy-example` | Copy a bundled example (`support-classifier`, `support-classifier-live`, `rag-qa`, `tool-agent`). |
| `init` | Scaffold a `driftless.yml`. |
| `init-policy` | Scaffold a `.driftless/policy.yml` (when to migrate). |
| `init-ci` | Scaffold `.github/workflows/` for scan, migrate, refine, poll, plan, label audit, and judge check. |
| `scan` | Find probable LLM usage and at-risk models. |
| `plan` | Discover at-risk workflows and apply the migration policy (CI triage). |
| `plan --act` | Migrate + open a PR/issue for every actionable trigger. |
| `configure <workflow>` | Write `.driftless/configure/<workflow>.yml`; add `--apply` to create or append root `driftless.yml`. |
| `calibrate -w <w>` | Measure the baseline and suggest starting thresholds. |
| `compare -w <w> --to <model>` | Baseline vs target scorecard; add `--enforce` to fail CI when gates fail. |
| `migrate -w <w> --to <model>` | Repair + validate + produce migrated files. |
| `refine -w <w>` | Re-optimize the prompt for a changed eval dataset (model pinned). |
| `poll [--act]` | Detect external eval-dataset changes and refine on a meaningful change. |
| `validate -w <w>` | Check the contract parses and the harness runs. |
| `judge-check -w <w>` | Measure judge↔human agreement (`--enforce` to gate). |
| `audit-labels -w <w>` | Find duplicate inputs with disagreeing gold labels (`--fail` for CI). |
| `report` | Render the latest migration report. |
| `view` | Open the optimization run viewer (charts + attempt log). |
| `open-pr -w <w>` | Open a PR (or issue) from the latest migration result. |

</details>

<details>
<summary>Configuring <em>when</em> to migrate</summary>

`plan` reads an optional `.driftless/policy.yml` — the “when to propose a
change” layer. Scaffold it with `driftless init-policy`. An empty file behaves
like no file. It controls which triggers are enabled (`deprecation` is on and
forced; `cost`/`quality`/`new_model` are optional), thresholds a candidate must
clear, a `cooldown_days` for freshly released models, allow/deny globs, and an
`ignore` list. The engine still decides whether a candidate passes *your* eval —
policy only decides whether to propose it.

</details>

## GitHub Action

A composite GitHub Action wraps the same CLI so scans and migrations can run in
CI. After you have a working local contract:

```yaml
- uses: driftless-dev/driftless@v0.3.6
  with:
    command: scan
```

See `.github/workflows/` in this repo for scheduled scan, weekly `plan --act`,
and manually triggered migration examples.

## Documentation

**Start here**

- [Landing page](https://driftless-dev.github.io/driftless/) — product overview.
- [Hosted docs](https://driftless-dev.github.io/driftless/docs.html) — install, quickstart, contract, CLI.
- [Getting started](https://github.com/driftless-dev/driftless/blob/main/docs/GETTING_STARTED.md) — golden-path example, then adopt in your repo.
- [Command chooser](https://github.com/driftless-dev/driftless/blob/main/docs/COMMAND_CHOOSER.md) — “I want to do X, which command?”
- [Known limits](https://github.com/driftless-dev/driftless/blob/main/docs/LIMITS.md) — what Driftless will and will not do.
- [Eval confidence](https://github.com/driftless-dev/driftless/blob/main/docs/CONFIDENCE.md) — when a pass is trustworthy.
- [Cost and budgets](https://github.com/driftless-dev/driftless/blob/main/docs/COST_AND_BUDGETS.md) — how eval loops spend money.

**When you need them**

- [Upgrading to 0.3](https://github.com/driftless-dev/driftless/blob/main/docs/UPGRADING.md) — replace legacy `migration.allow_*` with `files.editable`.
- [Use-case guides](https://driftless-dev.github.io/driftless/blog/) — model migration, dataset refine, CI, cost, labels, judges, RAG, agents.
- [RAG and agents](https://github.com/driftless-dev/driftless/blob/main/docs/rag-and-agents.md) — contract patterns.
- [Repair prompts and custom generators](https://github.com/driftless-dev/driftless/blob/main/docs/repair-and-generators.md)
- [Example blocked issue](https://github.com/driftless-dev/driftless/blob/main/docs/EXAMPLE_REVIEW_ARTIFACT.md) and [example success PR](https://github.com/driftless-dev/driftless/blob/main/docs/EXAMPLE_SUCCESS_PR.md)
- [Run viewer](https://driftless-dev.github.io/driftless/runs.html)
- [Changelog](https://github.com/driftless-dev/driftless/blob/main/CHANGELOG.md)
- [Contributing](https://github.com/driftless-dev/driftless/blob/main/CONTRIBUTING.md)
