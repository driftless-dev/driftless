# driftless

**Poetry-style lock regeneration for prompts — delivered Dependabot-style.**

A prompt is pinned to a **model** and an **eval dataset** (like `pyproject.toml`
declares deps and `poetry.lock` pins what works). When either moves, the prompt
goes stale. driftless repairs it through your real eval, validates on holdout,
and opens a PR with evidence.

> Also described as *Dependabot for LLM models* — same automation shape, different
> core insight: prompts are lockfiles, not just config files.

> Status: **public alpha** — `0.3.x` release line on [PyPI](https://pypi.org/project/driftless/).
> Upgrading from 0.2.x? Version 0.3.0 rejects legacy `migration.allow_*`
> fields; follow the [upgrade guide](https://github.com/driftless-dev/driftless/blob/main/docs/UPGRADING.md) before updating.

## Install

```bash
pip install driftless
```

## Quickstart

Try Driftless without provider keys by copying the bundled support-classifier
example:

```bash
driftless copy-example support-classifier --out-dir driftless-classifier-demo
cd driftless-classifier-demo
driftless validate -w support_classifier
driftless compare -w support_classifier --to gpt-4o-mini
```

The comparison intentionally fails:

```text
F1          current 1.000   target 0.000
Total cost  current 0.024   target 0.004
FAIL min_f1: 0.000 >= 0.9
```

> **Smoke-demo warning:** this fixture has only **4 rows**. It proves packaging,
> contract execution, metric gating, evidence rendering, and dry-run PR/issue
> behavior; it does **not** establish production quality, statistical
> confidence, provider behavior, or a successful repair. Use a representative
> eval and real provider credentials before making a shipping decision.

The target is cheaper, but it is not safe to ship because it fails the
classifier's quality gate. Continue through the blocked migration path without
provider keys:

```bash
driftless migrate -w support_classifier --to gpt-4o-mini --generator none
driftless report -w support_classifier
driftless open-pr -w support_classifier
```

`migrate` exits non-zero with `BLOCKED`, as intended. `--generator none` makes
no repair edits, `report` renders the saved evidence, and `open-pr` is a dry run
unless you explicitly pass `--create`.

## Product proof

This is the actual output of the cold-install quickstart:

![Terminal output from Driftless compare showing a cheaper target blocked by the F1 gate](https://raw.githubusercontent.com/driftless-dev/driftless/main/docs/visuals/compare-terminal.png)

A deterministic offline migration was also run against the public
[`support-classifier-svc`](https://github.com/driftless-dev/support-classifier-svc)
testbed. It produced [draft PR #4](https://github.com/driftless-dev/support-classifier-svc/pull/4)
with the generated scorecard, holdout evidence, prompt diff, and model update:

![Real GitHub pull request created from a passing Driftless migration](https://raw.githubusercontent.com/driftless-dev/driftless/main/docs/visuals/github-migration-pr.png)

PR #4 used testbed-specific deterministic patch tooling that is not shipped as
a Driftless CLI generator. It is genuine historical proof of the orchestration
and review artifact, not a claim that the published CLI reproduces that exact
repair without provider credentials.

Other bundled examples are available for retrieval QA and tool-using agents:

```bash
driftless copy-example rag-qa
driftless copy-example tool-agent
```

To adopt Driftless in an existing repository, follow the
[guided existing-repository walkthrough](https://github.com/driftless-dev/driftless/blob/main/docs/GETTING_STARTED.md#adopt-driftless-in-an-existing-repository).
It starts with `scan` and `configure --apply`, then gives a concrete
draft-to-contract example, exact editable-path rules, provider-cost guidance,
and safety checks before repair or CI. `configure` always saves a reviewable
draft; `--apply` also creates or safely appends the workflow to root
`driftless.yml` without rewriting existing comments.

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
| `copy-example` | Copy a bundled example project (`support-classifier`, `rag-qa`, `tool-agent`). |
| `init` | Scaffold a `driftless.yml`. |
| `init-policy` | Scaffold a `.driftless/policy.yml` (when to migrate). |
| `init-ci` | Scaffold `.github/workflows/` for scan, migrate, refine, poll, plan, label audit, and judge check. |
| `scan` | Find probable LLM usage and at-risk models. |
| `plan` | Discover at-risk workflows and apply the migration policy (CI triage). |
| `plan --act` | Migrate + open a PR/issue for every actionable trigger (close the loop). |
| `configure <workflow>` | Write `.driftless/configure/<workflow>.yml`; add `--apply` to create or safely merge root `driftless.yml`. |
| `calibrate -w <w>` | Measure the baseline and suggest starting thresholds. |
| `compare -w <w> --to <model>` | Baseline vs target scorecard; add `--enforce` for a failing CI exit code. |
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
- uses: driftless-dev/driftless@v0.3.3
  with:
    command: scan
```

## Documentation

- [Landing page](https://driftless-dev.github.io/driftless/) — product overview and public-alpha proof.
- [Hosted documentation](https://driftless-dev.github.io/driftless/docs.html) — installation, adoption path, concepts, and reference.
- [Run viewer](https://driftless-dev.github.io/driftless/runs.html) — inspect optimization attempts, metrics, and diffs.
- [Use-case guides](https://driftless-dev.github.io/driftless/blog/) — model migration, dataset refine, CI automation, cost, label audit, judges, RAG, and agents.
- [Getting started](https://github.com/driftless-dev/driftless/blob/main/docs/GETTING_STARTED.md) — run the bundled classifier, RAG, and agent examples.
- [Upgrading to 0.3](https://github.com/driftless-dev/driftless/blob/main/docs/UPGRADING.md) — replace legacy `migration.allow_*` fields with exact `files.editable` paths.
- [Command chooser](https://github.com/driftless-dev/driftless/blob/main/docs/COMMAND_CHOOSER.md) — map common user situations to CLI commands.
- [Known limits](https://github.com/driftless-dev/driftless/blob/main/docs/LIMITS.md) — current public-alpha boundaries.
- [Cost and budget guidance](https://github.com/driftless-dev/driftless/blob/main/docs/COST_AND_BUDGETS.md) — practical defaults for expensive eval loops.
- [Launch check](https://github.com/driftless-dev/driftless/blob/main/docs/LAUNCH_CHECK.md) — latest local suite, packaging, and example command results.
- [Visual proof inventory](https://github.com/driftless-dev/driftless/blob/main/docs/VISUAL_PROOF_PLAN.md) — genuine captures, provenance, and reproduction notes.
- [Example review artifact](https://github.com/driftless-dev/driftless/blob/main/docs/EXAMPLE_REVIEW_ARTIFACT.md) — dry-run issue/report from a blocked migration.
- [Example successful PR artifact](https://github.com/driftless-dev/driftless/blob/main/docs/EXAMPLE_SUCCESS_PR.md) — public testbed PR and separate saved fixture.
- [RAG and agent workflows](https://github.com/driftless-dev/driftless/blob/main/docs/rag-and-agents.md) — contract patterns for retrieval QA, judge grading, and tool-using agents.
- [User readiness plan](https://github.com/driftless-dev/driftless/blob/main/docs/USER_READINESS_PLAN.md) — current adoption boundaries and wider-launch follow-up.
- [Release process](https://github.com/driftless-dev/driftless/blob/main/docs/RELEASE.md) — changelog, tagging, GitHub Releases, PyPI.
- [Changelog](https://github.com/driftless-dev/driftless/blob/main/CHANGELOG.md) — version history.
- [Repair prompts & custom generators](https://github.com/driftless-dev/driftless/blob/main/docs/repair-and-generators.md) — customize
  the LLM repair prompt or plug in your own patch generator.
