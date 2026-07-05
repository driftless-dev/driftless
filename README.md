# driftless

**Poetry-style lock regeneration for prompts — delivered Dependabot-style.**

A prompt is pinned to a **model** and an **eval dataset** (like `pyproject.toml`
declares deps and `poetry.lock` pins what works). When either moves, the prompt
goes stale. driftless re-derives it through your real eval, validates on holdout,
and opens a PR with evidence.

> Also described as *Dependabot for LLM models* — same automation shape, different
> core insight: prompts are lockfiles, not just config files.

> Status: early development — `0.2.x` release line on [PyPI](https://pypi.org/project/driftless/).

## Install

```bash
pip install driftless
```

## Quickstart

Try Driftless without provider keys by copying a bundled classification example:

```bash
driftless copy-example support-classifier --out-dir driftless-classifier-demo
cd driftless-classifier-demo
driftless validate -w support_classifier
driftless compare -w support_classifier --to gpt-4o-mini
```

For a non-classifier workflow, copy the bundled RAG example:

```bash
driftless copy-example rag-qa --out-dir driftless-rag-demo
cd driftless-rag-demo
driftless validate -w rag_qa
driftless compare -w rag_qa --to gpt-4o-mini
```

Expected shape:

```text
Score / pass-rate   current 1.000   target 0.000
Total cost          current 0.072   target 0.016
FAIL min_score: 0.000 >= 0.86
```

The target is cheaper, but it fails the quality gate. From there, use
`driftless migrate -w rag_qa --to gpt-4o-mini` to attempt prompt/config repair.

## How it works

You describe your model-dependent workflow once in `driftless.yml`: how to
run it, how to override the model, which files may be edited, and what quality
thresholds must hold. `driftless` orchestrates *your* workflow under
different models, compares results, repairs allowed files, validates on
holdout, and opens a PR with the evidence.

The customer owns the workflow. The tool orchestrates it.

Not a classifier? Choose a grading mode that fits the task — the same loop then
optimizes against it, with your team owning the definition of "good":

- **`eval.score_field` / `eval.pass_field`** — your command emits a numeric score
  or a pass/fail per record (works for any task: summarization, codegen, agents).
- **`eval.fields`** — structured extraction, scored per field with
  precision/recall/F1 against the gold record.
- **`eval.judge`** — an LLM judge grades each free-form output against a rubric
  (with an optional human-scored calibration set for a judge-agreement check).
  Run `driftless judge-check -w <workflow>` before optimizing; set
  `max_mae` / `min_correlation` in the contract to gate `migrate` / `compare`.

## CLI

| Command | Purpose |
|---|---|
| `copy-example` | Copy a bundled example project (`rag-qa`, `tool-agent`). |
| `init` | Scaffold a `driftless.yml`. |
| `init-policy` | Scaffold a `.driftless/policy.yml` (when to migrate). |
| `init-ci` | Scaffold `.github/workflows/` for scan, migrate, refine, poll, plan, label audit, and judge check. |
| `scan` | Find probable LLM usage and at-risk models. |
| `plan` | Discover at-risk workflows and apply the migration policy (CI triage). |
| `plan --act` | Migrate + open a PR/issue for every actionable trigger (close the loop). |
| `configure <workflow>` | Turn a detected workflow into a migration-ready contract. |
| `calibrate -w <w>` | Measure the baseline and suggest starting thresholds. |
| `compare -w <w> --to <model>` | Baseline vs target scorecard. |
| `migrate -w <w> --to <model>` | Repair + validate + produce migrated files. |
| | `--strict-label-audit` warns/blocks on duplicate-label conflicts. |
| `refine -w <w>` | Re-optimize the prompt for a changed eval dataset (model pinned). |
| `poll [--act]` | Detect external eval-dataset changes and refine on a meaningful change. |
| `validate -w <w>` | Check the contract parses and the harness runs. |
| `judge-check -w <w>` | Measure judge↔human agreement on a calibration set (`--enforce` to gate). |
| `audit-labels -w <w>` | Find duplicate inputs with disagreeing gold labels (`--fail` for CI). |
| `report` | Render the latest migration report. |
| `view` | Open the optimization run viewer (charts + attempt log). |
| `open-pr -w <w>` | Open a PR (or issue) from the latest migration result. |

## Configuring *when* to migrate

`plan` reads an optional `.driftless/policy.yml` — the "dependabot.yml" layer.
Scaffold it with `driftless init-policy`; every field matches a default, so an
empty file behaves like no file. It controls which triggers are enabled
(`deprecation` is on and forced; `cost`/`quality`/`new_model` are opportunistic),
the thresholds a candidate must clear (`min_savings_pct`, `min_gain`), a
`cooldown_days` to skip freshly-released models, candidate `allow`/`deny` globs,
and an `ignore` list to snooze specific models or moves. The engine still decides
whether a candidate actually passes *your* eval — policy only decides whether to
propose it.

## GitHub-native usage

A composite GitHub Action (`action.yml`) wraps the CLI so scans and migrations
can run in CI. See `.github/workflows/` for a scheduled deprecation scan, weekly
`plan --act` triage, and manually-triggered migration workflows.

```yaml
- uses: driftless-dev/driftless@v0.2.15
  with:
    command: scan
```

## Documentation

- [Blog series: common use cases](./docs/blog/README.md) — drafts for model migration, dataset refine, CI automation, cost, label audit, and LLM judges.
- [Getting started](./docs/GETTING_STARTED.md) — run bundled RAG and agent examples.
- [Command chooser](./docs/COMMAND_CHOOSER.md) — map common user situations to CLI commands.
- [Known limits](./docs/LIMITS.md) — current boundaries before broad rollout.
- [Cost and budget guidance](./docs/COST_AND_BUDGETS.md) — practical defaults for expensive eval loops.
- [Launch check](./docs/LAUNCH_CHECK.md) — latest local suite, packaging, and example command results.
- [Visual proof plan](./docs/VISUAL_PROOF_PLAN.md) — exact screenshot targets before public launch.
- [Example review artifact](./docs/EXAMPLE_REVIEW_ARTIFACT.md) — dry-run issue/report from a blocked migration.
- [Example successful PR artifact](./docs/EXAMPLE_SUCCESS_PR.md) — dry-run PR/report from a passing migration.
- [RAG and agent workflows](./docs/rag-and-agents.md) — contract patterns for retrieval QA, judge grading, and tool-using agents.
- [User readiness plan](./docs/USER_READINESS_PLAN.md) — what remains before a broader self-serve launch.
- [Release process](./docs/RELEASE.md) — changelog, tagging, GitHub Releases, PyPI.
- [Changelog](./CHANGELOG.md) — version history.
- [Repair prompts & custom generators](./docs/repair-and-generators.md) — customize
  the LLM repair prompt or plug in your own patch generator.
- [Run viewer](./site/runs.html) — inspect optimization attempts, metrics, and diffs.
