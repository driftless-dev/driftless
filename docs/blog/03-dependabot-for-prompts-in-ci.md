# Prompt repair that doesn’t wait for someone to remember

## The problem and the outcome

Your prompts, evaluation data, and Python test harness already live in Git. You
can test a model change or update a prompt after labels change, but only when
someone remembers to run the commands.

That manual loop breaks down quickly. A provider announces a model retirement.
Someone changes the model ID under deadline pressure. Annotators update labels,
but continuous integration (CI) never checks whether the prompt still matches
them. Cheaper models go unnoticed because no one owns weekly review.

The desired outcome looks like Dependabot for prompts: automation watches model
lifecycle and evaluation data, runs your real tests, and opens a pull request
(PR) or issue with evidence. A human still decides what ships.

Audit the labels first. Gold labels are the expected answers in your evaluation
set, and automation is unsafe when those answers contradict each other. Follow
[post 5](./05-audit-labels-before-you-trust-f1.md) before automating repair.

## Mental model

Driftless separates discovery, decisions, and action:

- A **scan** is a read-only search for likely LLM workflow files, model IDs, and
  lifecycle risks. It does not create `driftless.yml` or edit your repository.
- A **trigger** is a condition that deserves review, such as a retired model, a
  changed dataset, or a cheaper active model.
- A **policy** is the YAML file that turns those conditions into rules: how
  early to warn, what savings matter, and whether the result should be a PR,
  issue, or dry run.
- A **plan** is the decision table produced by applying that policy to detected
  triggers and evaluation results. It routes work; it is not approval to ship.
- A **scheduled workflow** is a GitHub Actions workflow started by a clock, such
  as every Monday, rather than by a commit. GitHub Actions is GitHub's service
  for running repository automation; a workflow is a YAML file containing one
  or more jobs and their command steps.

`driftless init-ci` generates standard GitHub Actions workflows for review.
The external testbed later in this post uses hand-authored workflows instead.
Those testbed files include custom path filters, manual inputs, simulator setup,
and staged rollout behavior that a generic generator cannot infer.

## Prerequisites

- Basic Python and Git command-line use
- A repository with a repeatable evaluation harness
- A Driftless workflow contract in `driftless.yml`
- Trustworthy labels before any automated repair
- Provider and GitHub credentials only when acting on a plan

## Walkthrough 1: verify the bundled fixture

The bundled demo has four deterministic rows and needs no provider key. Install
Driftless, copy the example, validate its contract, compare its current model
with `gpt-4o-mini`, then generate a starter policy and CI workflows:

```bash
pip install driftless
driftless copy-example support-classifier --out-dir driftless-classifier-demo
cd driftless-classifier-demo
driftless validate -w support_classifier
driftless compare -w support_classifier --to gpt-4o-mini
driftless init-policy
driftless init-ci
```

The four-row comparison reports that the candidate fails the configured
thresholds. `compare` can still exit with code `0`: read its threshold table and
the “Naive target does not pass” message instead of treating process success as
quality success. `BLOCKED` is a status used by `migrate` or `refine` when a
repair run cannot produce a shippable result; it is not the status of this
`compare` command.

Review the generated `.driftless/policy.yml` and
`.github/workflows/driftless-*.yml` files before committing them. This fixture
verifies command wiring, not provider behavior or a successful repair. Acting
on plans and LLM-backed repair require credentials; `--create` adds GitHub side
effects.

[`EXAMPLE_SUCCESS_PR.md`](../EXAMPLE_SUCCESS_PR.md) distinguishes public
testbed PR #4 from the different bundled four-row saved success fixture. Both
show the `open-pr` evidence shape; see the
[repair reproduction boundary](./01-model-swap-is-not-a-migration.md#repair-reproduction-boundary).

![Real GitHub pull request containing Driftless migration evidence](../visuals/github-migration-pr.png)

[Open the public draft PR and inspect the generated report and diff.](https://github.com/driftless-dev/support-classifier-svc/pull/4)

## Walkthrough 2: discover an existing application

Run `scan` before configuration so you can see what Driftless can detect without
changing files. Then apply a workflow contract, review the inferred fields,
resolve any remaining placeholders, and validate it:

```bash
driftless scan .
driftless configure support_classifier --apply
# review the inferred contract; resolve any remaining placeholders
driftless validate -w support_classifier
```

The scan should list probable LLM files and known model lifecycle risks.
Detection is best-effort: models hidden behind environment variables or
gateways may need manual configuration. Validation should pass only after the
contract correctly names your harness, model, inputs, labels, and thresholds.

For a new repository, generate policy and workflow files after local behavior is
understood:

```bash
driftless init-policy    # writes .driftless/policy.yml
driftless init-ci        # writes .github/workflows/driftless-*.yml
```

These are generated starting points. The external
[support-classifier-svc](https://github.com/driftless-dev/support-classifier-svc)
testbed instead dogfoods hand-written workflows pinned to `driftless==0.3.3`.
Use its [workflow directory](https://github.com/driftless-dev/support-classifier-svc/tree/main/.github/workflows)
when you need examples of testbed-specific path filters, manual-dispatch inputs,
simulator setup, or staged rollout.

## Walkthrough 3: preview weekly work in the 290-row testbed

The external testbed is a separate clone with two workflows in one
`driftless.yml`:

| Workflow | Job | Model (today) | Evaluation |
|----------|-----|---------------|------------|
| `support_classifier` | Four-way ticket JSON classification | `gpt-3.5-turbo` | 290 labeled tickets, `min_f1: 0.90` |
| `quick_triage` | Escalate yes/no | `gpt-3.5-turbo` | Same inputs, pass/fail labels |

Its committed `.driftless/policy.yml` says:

```yaml
deprecation:
  enabled: true
  warn_before_days: 90
  action: pr

cost:
  enabled: true
  min_savings_pct: 0.20
  max_quality_drop: 0.01

data_change:
  enabled: true
  min_changed_rows: 5
```

Both workflows still use deprecated `gpt-3.5-turbo`, so `plan` always has work.
The [hand-authored `plan-preview.yml`](https://github.com/driftless-dev/support-classifier-svc/blob/main/.github/workflows/plan-preview.yml)
runs every Monday. Its simulator makes the run free and deterministic:

```yaml
env:
  SUPPORT_CLASSIFIER_SIMULATE: "1"

steps:
  - run: driftless plan || test $? -eq 1
    # exit 1 = triggers found (expected here)
```

To reproduce that preview locally, enter the separate clone, enable its
simulator, and build the plan:

```bash
cd support-classifier-svc
export SUPPORT_CLASSIFIER_SIMULATE=1
driftless plan
```

Actual output from July 2026:

```text
┃ Workflow          ┃ Trigger     ┃ Migrate                    ┃ Naive     ┃ Decision      ┃
│ support_classifier│ deprecation │ gpt-3.5-turbo -> gpt-4o-mini │ regresses │ ISSUE (critical) │
│ quick_triage      │ deprecation │ gpt-3.5-turbo -> gpt-4o-mini │ regresses │ ISSUE (critical) │

Why:
  gpt-3.5-turbo retired 277d ago; candidate gpt-4o-mini not shippable as-is
  (status=blocked) -> open issue

2 workflow(s) need action across 1 model move(s):
  gpt-3.5-turbo -> gpt-4o-mini (deprecation): support_classifier, quick_triage
```

The result groups one model move across two workflows instead of opening two
blind migration PRs. Reports land under `.driftless/reports/`. The decision is
`ISSUE`, not `PR`, because the naive comparison fails thresholds with 100%
schema errors in the simulator; [post 1](./01-model-swap-is-not-a-migration.md)
explains why migration and repair are required.

Interpret decisions this way:

| Decision | Meaning | Human next step |
|----------|---------|-----------------|
| `PR` | The candidate can be repaired and passes gates | Review prompt and config diffs |
| `ISSUE` | Drift exists, but no safe patch is ready | Triage the evidence |
| No rows | No policy trigger crossed its threshold | Nothing to review |

## Walkthrough 4: add action carefully

The hand-authored [plan-act.yml](https://github.com/driftless-dev/support-classifier-svc/blob/main/.github/workflows/plan-act.yml)
uses **manual dispatch**, meaning a person starts it from GitHub's Actions page
and can provide inputs. First preview the Git and GitHub operations:

```bash
driftless plan --act
```

After the preview matches team expectations, allow creation:

```bash
driftless plan --act --create
```

`--act` runs migration or refinement work but remains a dry run by default.
`--create` performs Git and GitHub operations and can open PRs or issues. It
needs `OPENAI_API_KEY` for LLM-backed repair and `GH_TOKEN` for GitHub.
Scheduled runs stay dry-run; only a manual dispatch with `create=true` opens
PRs. Keep the first runs as calibration while the team learns which conditions
deserve automation.

## Walkthrough 5: react to label and model changes

An **event-driven workflow** runs because a repository event occurred. In the
testbed, [refine-on-label-change.yml](https://github.com/driftless-dev/support-classifier-svc/blob/main/.github/workflows/refine-on-label-change.yml)
runs after a push changes the label file:

```text
push to evals/tickets.labels.jsonl
  → audit-labels --fail
  → refine --strict-label-audit  (simulator harness)
  → open-pr --create
```

The audit-first ordering prevents repair from optimizing against contradictory
labels. [Post 2](./02-when-labels-move-refine-not-remodel.md) covers the
charge-reversal policy fixture: `evals/_apply_refund_policy.py` changes 25
tickets.

For a real model move, the hand-authored
[migrate-on-model-change.yml](https://github.com/driftless-dev/support-classifier-svc/blob/main/.github/workflows/migrate-on-model-change.yml)
is started through **Actions → Migrate model → Run workflow**:

| Input | Default | Purpose |
|-------|---------|---------|
| `target_model` | `gpt-4o-mini` | Supplies the `--to` value |
| `restore_baseline_prompt` | `true` | Copies `evals/fixtures/prompt-baseline-scenario3.md`, preserving the hand-written baseline fixture |

Its order is `audit-labels` → real `compare` → `migrate
--strict-label-audit` → `open-pr --create`. It requires `OPENAI_API_KEY` and
allows 120 minutes for LLM repair over 290 tickets. The resulting PR includes a
scorecard, changes to `prompts/system.md` and `config/llm.yml`, a holdout result,
and an attempt log.

Finally, [audit-labels.yml](https://github.com/driftless-dev/support-classifier-svc/blob/main/.github/workflows/audit-labels.yml)
runs on PRs that touch `evals/tickets.*.jsonl` and blocks merge when similar
inputs disagree on gold labels.

## Failure and safety behavior

- `scan` is read-only and best-effort.
- `plan` exits non-zero when it finds work, which is expected in the preview
  workflow.
- A failed naive comparison becomes an issue rather than an unsafe PR.
- Scheduled `plan --act` remains dry-run unless creation is explicitly enabled.
- `--create` has external side effects and requires credentials.
- The four-row fixture is a smoke test; it is not evidence about provider
  behavior. The 290-row testbed is a separate clone with different fixtures.

## Suggested rollout order

1. Run `audit-labels` on evaluation file paths
   ([post 5](./05-audit-labels-before-you-trust-f1.md)).
2. Add `refine-on-label-change` only after the audit is clean
   ([post 2](./02-when-labels-move-refine-not-remodel.md)).
3. Run `plan-preview` weekly with the simulator for visibility without keys.
4. Use `migrate-on-model-change` by manual dispatch when you accept token cost.
5. Enable `plan-act --create` only after policy thresholds match team risk.

The testbed workflow summary is:

| Workflow file | Trigger | Keys required |
|---------------|---------|---------------|
| `plan-preview.yml` | Weekly schedule and manual dispatch | None (simulator) |
| `plan-act.yml` | Weekly schedule and manual dispatch (`create` input) | Optional API keys |
| `refine-on-label-change.yml` | Push to evaluation JSONL | Repair requires API key |
| `migrate-on-model-change.yml` | Manual dispatch | `OPENAI_API_KEY` |
| `audit-labels.yml` | PR or push to evaluation JSONL | None |
| `real-model-refine.yml` | Manual dispatch or schedule | `OPENAI_API_KEY` |

## Next steps

- [Post 1: compare and migrate](./01-model-swap-is-not-a-migration.md)
- [Post 2: refine after a label change](./02-when-labels-move-refine-not-remodel.md)
- [Post 4: cost trigger](./04-cheaper-model-same-quality-bar.md) — this needs an
  active baseline model; testbed deprecation rows dominate until migration
- Product workflows: [Driftless `.github/workflows/`](../../.github/workflows/)
