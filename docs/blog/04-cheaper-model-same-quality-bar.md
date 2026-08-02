# Finance wants cheaper inference on the same quality bar

## The problem and the outcome

Your classifier or other LLM workflow launched on a frontier model such as
`gpt-4o` because it passed the quality checks. Traffic grew, and finance now
wants at least 20% lower inference cost. `gpt-4o-mini` looks attractive.

Changing the model name is not enough. A cheaper model may format JSON
differently, weaken a category rule, or fail examples that the current model
handles. Saving 20% means spending at most 80% of the current amount for the
same workload. It says nothing about whether the new model is accurate enough.

The outcome you want is a cost proposal that must pass the existing quality
gate. In the 290-ticket example, the candidate still needs to clear
`min_f1: 0.90` before anyone merges the change.

Audit labels before spending provider tokens. Contradictory gold answers can
make every model look worse and waste repair iterations; [post
5](./05-audit-labels-before-you-trust-f1.md) shows the audit-first path.

## Mental model

The **baseline** is the current model and current prompt used as the reference.
The **candidate** is the model being considered as its replacement. A cost
comparison is useful only when both run the same representative evaluation.

A **trigger** is a reason to investigate a change. A deprecation trigger is
forced because a model is retiring. A cost trigger is opportunistic: it points
to a possible saving, but you can decline it.

A **policy** is a YAML file containing the team's decision rules. A **quality
threshold** is an absolute pass/fail requirement in the workflow contract, such
as macro-F1 of at least `0.90` or schema error rate no more than `0.02`.
Macro-F1 is the unweighted average of the F1 score for every class, so a small
class counts as much as a large one. F1 combines precision and recall.

Driftless uses two kinds of cost evidence:

- A **catalog estimate** comes from bundled model prices and an assumed blend of
  input and output tokens. It is useful for discovering candidates.
- **Measured cost** is emitted by your evaluation harness for actual test calls,
  or derived from its measured token counts. It is stronger decision evidence,
  but it represents production only when the evaluation workload and usage are
  production-representative.

The cost policy proposes candidates; `compare` and `migrate` still enforce your
quality thresholds. Cheaper is never an automatic approval.

## Prerequisites

- A working `driftless.yml` contract and representative evaluation
- Clean, internally consistent gold labels
- Cost or token fields from the harness when you want measured evidence
- An **active baseline**, meaning the provider lifecycle catalog does not mark
  the current model deprecated or retired, for opportunistic cost discovery
- A provider key for real evaluation and LLM-backed repair

The bundled command below compares a candidate directly. It does not exercise
`plan`'s cost trigger. The external testbed walkthrough temporarily changes to
an active baseline so you can reproduce that trigger.

## Walkthrough 1: see the cost-versus-quality gate

Install Driftless, copy the four-row fixture, enter its directory, and compare
the current model with `gpt-4o-mini`:

```bash
pip install driftless
driftless copy-example support-classifier --out-dir driftless-classifier-demo
cd driftless-classifier-demo
driftless validate -w support_classifier
driftless compare -w support_classifier --to gpt-4o-mini
```

The deterministic fixture reports cost `0.024 → 0.004` while F1 falls
`1.000 → 0.000`, so the candidate fails the quality thresholds. The cost falls
by about 83%, but the quality result makes the saving unsafe. `compare` can
still exit with code `0`; its threshold report, not its process exit code, tells
you whether the candidate passed.

These four-row values are fixture data, not provider pricing or
production-quality evidence. Use a representative evaluation and harness
measurements before making a savings claim.

## Walkthrough 2: wire measured cost into the contract

The separate
[support-classifier-svc](https://github.com/driftless-dev/support-classifier-svc)
testbed contains 290 labeled tickets. Its `support_classifier` workflow tells
Driftless where each evaluation record reports spend and token use:

```yaml
# driftless.yml → workflows.support_classifier.eval
cost_field: cost_usd
prompt_tokens_field: prompt_tokens
completion_tokens_field: completion_tokens
```

`evals/run_eval.py` fills these fields. The simulator emits fixture estimates;
with a provider key, LiteLLM reports usage. Driftless prefers `cost_field` when
the harness supplies it. Otherwise it estimates dollars from the token fields
and bundled catalog prices.

The expected result is a side-by-side total in `compare`. Treat that total as
measured evaluation cost when the harness records real calls. Do not call it
measured production spend unless the evaluation reflects production traffic.

The testbed policy defines when a saving is worth proposing:

```yaml
cost:
  enabled: true
  min_savings_pct: 0.20    # require at least 20% cheaper
  max_quality_drop: 0.01   # F1 may fall by no more than 0.01
  action: pr
```

`min_savings_pct: 0.20` means the candidate must cost no more than 80% of the
baseline estimate. `max_quality_drop: 0.01` permits at most one F1 point of
regression after comparison. Neither setting replaces absolute workflow
thresholds such as `min_f1: 0.90`; those remain the ship bar.

## Walkthrough 3: check catalog math

Run the following Python snippet to ask Driftless for catalog price changes
between two model pairs:

```bash
python - <<'PY'
from driftless.discovery import estimate_cost_change_pct
print("gpt-4o → gpt-4o-mini:", estimate_cost_change_pct("gpt-4o", "gpt-4o-mini"))
print("claude-3-opus → claude-3-5-sonnet:",
      estimate_cost_change_pct("claude-3-opus-20240229", "claude-3-5-sonnet"))
PY
```

Typical catalog results use blended input and output prices per one million
tokens:

| Move | Estimated cost change |
|------|-----------------------|
| `gpt-4o` → `gpt-4o-mini` | **−94%** |
| `claude-3-opus-20240229` → `claude-3-5-sonnet` | **−80%** |

A `−94%` change means the catalog estimate for the candidate is about 6% of the
baseline estimate. A `−80%` change means it is about 20%. Both clear the 20%
savings policy, but neither proves acceptable quality or measured production
savings.

Discovery also rejects candidates in a lower capability tier than the baseline.
A **capability tier** is the catalog's broad model capability grouping. This
filter avoids automatically proposing an obvious downgrade, but the evaluation
still decides whether a same-tier or higher-tier candidate is safe.

## Walkthrough 4: reproduce a cost trigger in the testbed

The committed testbed uses deprecated `gpt-3.5-turbo`. Deprecation takes
priority, so `plan` shows issue rows for the retirement and hides optional cost
discovery. That is intentional: a possible saving must not distract from a
retirement deadline.

To exercise cost discovery, temporarily use an active baseline:

1. Set `model.current: gpt-4o` in both `driftless.yml` and `config/llm.yml` for
   `support_classifier`.
2. Keep `cost.enabled: true` and `min_savings_pct: 0.20`.
3. Enable the deterministic simulator and ask Driftless to build a plan:

```bash
export SUPPORT_CLASSIFIER_SIMULATE=1
driftless plan
```

A **plan** is the table of policy-triggered work, not an approval. Expect a
`cost` trigger proposing something like `gpt-4o-mini`: same provider, active,
cheaper, and not in a lower capability tier.

Next, compare baseline and candidate on the same workflow:

```bash
driftless compare -w support_classifier --to gpt-4o-mini
```

The comparison should tell you whether the untouched prompt passes the cost and
quality gates for the temporary `gpt-4o` baseline. For reference, the
approximately `0.033 → 0.011` Total cost row documented for the testbed
simulator comes from its **committed**
`gpt-3.5-turbo → gpt-4o-mini` configuration over 290 tickets. It is not output
from the temporary `gpt-4o` configuration you created above. Those simulator
dollars show relative scale, not production spend.

If the active-baseline comparison fails quality thresholds, use migration to
repair editable prompt files. The simulator replaces only the evaluation
harness; the LLM repair generator still needs a provider key:

```bash
export OPENAI_API_KEY=...
driftless migrate -w support_classifier --to gpt-4o-mini --generator llm
```

After the exercise, revert both temporary edits. The testbed's deprecation demo
depends on `gpt-3.5-turbo`. Run `git diff` and confirm the active-baseline edits
will not be committed.

## How to interpret the decision

Cost uses the same repair loop as a forced migration:

1. `compare` runs baseline and candidate side by side for quality and cost.
2. `migrate` repairs allowed prompt files if the untouched candidate fails.
3. A holdout gate tests the repaired result on rows that were not used for
   repair, still requiring `min_f1: 0.90` and
   `max_schema_error_rate: 0.02`.
4. `open-pr` opens a PR only when the result is shippable; otherwise the
   evidence supports an issue.

`max_quality_drop` answers whether a passing but slightly worse candidate is
worth a PR. Absolute thresholds still win: a blocked candidate cannot become
safe because it is cheap. [Post
1](./01-model-swap-is-not-a-migration.md) explains the scorecard and holdout
path.

## Add the check to CI later

A **scheduled workflow** is GitHub Actions automation started by a clock. The
testbed's hand-authored
[plan-preview.yml](https://github.com/driftless-dev/support-classifier-svc/blob/main/.github/workflows/plan-preview.yml)
runs weekly with the simulator. After migration removes deprecated baselines,
the same job can surface cost rows without another workflow.

For a deliberate cost investigation, use **Actions → Migrate model** and set
`target_model=gpt-4o-mini` after the baseline is an active frontier model.
[Post 3](./03-dependabot-for-prompts-in-ci.md) distinguishes these hand-authored
testbed examples from workflows generated by `driftless init-ci`.

## Failure and safety behavior

- Cost discovery skips unknown, deprecated, and retired baselines.
- It considers active models from the same provider and refuses lower
  capability tiers.
- A candidate that fails quality thresholds is not shippable, regardless of
  savings.
- Catalog estimates are for triage; harness totals are decision evidence.
- Simulator cost is fixture data, not a production invoice.
- Keep deprecation enabled because retirement work takes priority over optional
  savings.

## Next steps

- [Post 1](./01-model-swap-is-not-a-migration.md) — repair loop details
- [Post 3](./03-dependabot-for-prompts-in-ci.md) — schedule `plan` in Actions
- [Post 5](./05-audit-labels-before-you-trust-f1.md) — audit before spending
  tokens on a cost migration
