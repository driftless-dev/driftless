# Prompt repair that doesn’t wait for someone to remember

## The use case

Your LLM app already looks "done" from a git perspective: prompts live in the
repo, gold labels live in JSONL, and a harness command can score quality offline.
You can migrate a model or refine after a label change *when someone remembers
to*.

In practice, nobody owns that loop. Deprecations arrive as a Slack forward of a
provider email. Someone bumps the model ID under deadline pressure (see
[post 1](./01-model-swap-is-not-a-migration.md)). Separately, annotators merge
label updates and CI never re-tunes the prompt (see
[post 2](./02-when-labels-move-refine-not-remodel.md)). Cost opportunities sit
unnoticed because no one runs a weekly triage. Each incident invents a one-off
runbook; the next person cannot see the same decision table.

What you want is Dependabot's shape applied to prompts: something that
**watches** model lifecycle and eval data, **tests** candidates through your
real harness, and **opens a PR or issue with evidence** — without requiring a
hero engineer every Monday.

**What driftless does here:** scaffold GitHub Actions (`init-ci`), apply a policy
file for when to propose changes, and run `scan` / `plan` / `migrate` / `refine`
through a composite Action so triage is scheduled and reviewable.

## Reproduce locally before adding CI

```bash
pip install driftless
driftless copy-example support-classifier --out-dir driftless-classifier-demo
cd driftless-classifier-demo
driftless validate -w support_classifier
driftless compare -w support_classifier --to gpt-4o-mini
driftless init-policy
driftless init-ci
```

Review generated policy and workflow files; do not commit automation until the
local contract and expected `BLOCKED` four-row smoke result make sense. The
fixture needs no provider key, but it does not prove provider behavior or a
successful repair. Acting on plans and LLM-backed repair require credentials;
`--create` adds GitHub side effects.

Artifact reference:
[`EXAMPLE_SUCCESS_PR.md`](../EXAMPLE_SUCCESS_PR.md) distinguishes public
testbed PR #4 from the different bundled four-row saved success fixture. Both
show the `open-pr` evidence shape, but the published CLI does not ship the
testbed-specific deterministic patch tooling used to prepare PR #4.

![Real GitHub pull request containing Driftless migration evidence](../visuals/github-migration-pr.png)

[Open the public draft PR and inspect the generated report and diff.](https://github.com/driftless-dev/support-classifier-svc/pull/4)

## Optional full testbed appendix

The remaining sections map each layer to the external
[support-classifier-svc](https://github.com/driftless-dev/support-classifier-svc)
workflows you can run today.

---

## The testbed at a glance

Two workflows in one `driftless.yml`:

| Workflow | Job | Model (today) | Eval |
|----------|-----|---------------|------|
| `support_classifier` | 4-way ticket JSON classification | `gpt-3.5-turbo` | 290 labeled tickets, `min_f1: 0.90` |
| `quick_triage` | Escalate yes/no | `gpt-3.5-turbo` | Same inputs, pass/fail labels |

Policy in `.driftless/policy.yml` (committed in the testbed):

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

Both workflows still sit on deprecated `gpt-3.5-turbo`, so **`plan` always
has work** — useful for demoing CI.

The shape is intentionally Dependabot-like:

| Dependency surface | Driftless watches | Action |
|--------------------|-------------------|--------|
| Package version | Provider model lifecycle | `plan`, `compare`, `migrate` |
| Lockfile / manifest policy | `.driftless/policy.yml` | PR, issue, or dry-run |
| Test suite | Your eval harness | Threshold-gated report |
| Generated PR | Prompt/config diffs | `open-pr` |

---

## Scaffold CI from your contract

Greenfield repos:

```bash
driftless init-policy    # .driftless/policy.yml
driftless init-ci        # .github/workflows/driftless-*.yml
```

The testbed instead **dogfoods** hand-written workflows pinned to
`driftless==0.3.2` — copy patterns from
[`.github/workflows/`](https://github.com/driftless-dev/support-classifier-svc/tree/main/.github/workflows).

---

## Layer 1: Weekly `plan` (simulator, free)

[plan-preview.yml](https://github.com/driftless-dev/support-classifier-svc/blob/main/.github/workflows/plan-preview.yml)
runs every Monday:

```yaml
env:
  SUPPORT_CLASSIFIER_SIMULATE: "1"

steps:
  - run: driftless plan || test $? -eq 1
    # exit 1 = triggers found (expected here)
```

Local equivalent:

```bash
cd support-classifier-svc
export SUPPORT_CLASSIFIER_SIMULATE=1
driftless plan
```

**Actual output** (July 2026):

```
┃ Workflow          ┃ Trigger     ┃ Migrate                    ┃ Naive     ┃ Decision      ┃
│ support_classifier│ deprecation │ gpt-3.5-turbo -> gpt-4o-mini │ regresses │ ISSUE (critical) │
│ quick_triage      │ deprecation │ gpt-3.5-turbo -> gpt-4o-mini │ regresses │ ISSUE (critical) │

Why:
  gpt-3.5-turbo retired 277d ago; candidate gpt-4o-mini not shippable as-is
  (status=blocked) -> open issue

2 workflow(s) need action across 1 model move(s):
  gpt-3.5-turbo -> gpt-4o-mini (deprecation): support_classifier, quick_triage
```

One grouped move, two workflows — not two blind migrate PRs. Artifacts land under
`.driftless/reports/` for the run.

**Why ISSUE not PR?** Naive `compare` fails thresholds (100% schema errors on
the simulator — see [post 1](./01-model-swap-is-not-a-migration.md)). Policy
still surfaces the row; `migrate` + repair is required before a PR is safe.

Read the table as a routing layer, not an approval:

| Decision | Meaning | Human expectation |
|----------|---------|-------------------|
| `PR` | Candidate can be repaired and passes gates | Review prompt/config diffs |
| `ISSUE` | Drift exists, but no safe patch is ready | Triage with evidence |
| No rows | No policy trigger crossed the threshold | Nothing to review |

---

## Layer 2: `plan --act` when you're ready to close the loop

[plan-act.yml](https://github.com/driftless-dev/support-classifier-svc/blob/main/.github/workflows/plan-act.yml)
— manual dispatch, optional `--create`:

```bash
driftless plan --act              # preview git/gh operations
driftless plan --act --create     # run migrate/refine + open PRs/issues
```

Scheduled runs stay dry-run; flipping `create=true` on dispatch actually opens
PRs. Needs `OPENAI_API_KEY` (and `GH_TOKEN` for GitHub).

Keep scheduled `plan --act` dry until the issue/PR distinction matches your
team's risk tolerance. The first few runs are calibration: you are teaching the
policy which changes deserve automation and which deserve a human migration
ticket.

---

## Layer 3: Event-driven refine (dataset drift)

When someone commits label changes →
[refine-on-label-change.yml](https://github.com/driftless-dev/support-classifier-svc/blob/main/.github/workflows/refine-on-label-change.yml):

```
push to evals/tickets.labels.jsonl
  → audit-labels --fail
  → refine --strict-label-audit  (simulator harness)
  → open-pr --create
```

See [post 2](./02-when-labels-move-refine-not-remodel.md) for the charge-reversal
policy story (`evals/_apply_refund_policy.py`, 25 tickets).

---

## Layer 4: Manual migration (real API, full PR)

[migrate-on-model-change.yml](https://github.com/driftless-dev/support-classifier-svc/blob/main/.github/workflows/migrate-on-model-change.yml)
— **Actions → Migrate model → Run workflow**:

| Input | Default | Purpose |
|-------|---------|---------|
| `target_model` | `gpt-4o-mini` | `--to` argument |
| `restore_baseline_prompt` | `true` | Copy `evals/fixtures/prompt-baseline-scenario3.md` so each run starts from the hand-written prompt |

Steps: `audit-labels` → real `compare` → `migrate --strict-label-audit` →
`open-pr --create`. Requires `OPENAI_API_KEY`. Timeout **120 minutes** on 290
tickets with LLM repair.

This is the PR you show stakeholders: scorecard, diffs on `prompts/system.md`
and `config/llm.yml`, holdout line, attempt log.

---

## Layer 5: Label hygiene on every eval PR

[audit-labels.yml](https://github.com/driftless-dev/support-classifier-svc/blob/main/.github/workflows/audit-labels.yml)
on PRs touching `evals/tickets.*.jsonl` — blocks merge if similar inputs disagree
on gold labels.

---

## Suggested rollout order

1. **audit-labels** on eval file paths (cheap, catches bad data early)
2. **plan-preview** weekly with simulator (visibility, no keys)
3. **refine-on-label-change** when labels live in git
4. **migrate-on-model-change** manual dispatch when you accept token cost
5. **plan-act --create** only after policy thresholds feel right

That order keeps the blast radius small. First make the eval trustworthy, then
make drift visible, then let automation propose changes.

---

## Workflow cheat sheet (testbed)

| Workflow file | Trigger | Keys required |
|---------------|---------|---------------|
| `plan-preview.yml` | Weekly + dispatch | None (simulator) |
| `plan-act.yml` | Weekly + dispatch (`create` input) | Optional API keys |
| `refine-on-label-change.yml` | Push to eval JSONL | Repair: API key |
| `migrate-on-model-change.yml` | Manual dispatch | `OPENAI_API_KEY` |
| `audit-labels.yml` | PR/push to eval JSONL | None |
| `real-model-refine.yml` | Manual / schedule | `OPENAI_API_KEY` |

---

## Next steps

- [Post 1: compare + migrate](./01-model-swap-is-not-a-migration.md)
- [Post 2: refine on label change](./02-when-labels-move-refine-not-remodel.md)
- [Post 4: cost trigger](./04-cheaper-model-same-quality-bar.md) — needs an
  *active* baseline model; testbed deprecation rows dominate until you migrate
- Product workflows: [driftless `.github/workflows/`](../../.github/workflows/)
