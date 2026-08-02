# Support changed the labeling policy — model stays put

## What problem are we solving?

The support classifier from
[post 1](./01-model-swap-is-not-a-migration.md) assigns each ticket a category.
Its **gold label** is the expected category used to score one evaluation example.

For a long time, the team labels a request such as “Please reverse the payment
on my latest invoice” as `billing`. After a product decision, support operations
changes the policy: charge-reversal requests should now be `refund`. An engineer
or annotator updates about 25 rows in the JSONL evaluation data, but the model ID
and prompt stay unchanged.

The next evaluation score falls. That can look like a model regression, but the
definition of “correct” moved. This is **label drift**: expected labels or their
meaning changed over time. More broadly, it is **dataset drift**, a change to the
evaluation inputs or expected outputs. Replacing the model would change another
variable and make the cause harder to understand.

The goal is to teach the pinned model the new policy by updating allowed prompt
files, then prove that the update works on unseen examples.

## What Driftless does

An **evaluation**, or **eval**, is a repeatable test of model behavior. Its
**evaluation harness** runs examples, parses model outputs, and computes scores.
The committed `driftless.yml` is the **workflow contract** that connects that
harness to evaluation data, editable files, and release rules.

For a label change, Driftless uses `refine`:

1. Keep the configured model pinned.
2. Ask a **repair generator**—the model or mechanism that proposes prompt
   changes—to edit only allowed files.
3. Score proposed repairs against the changed labels.
4. Compare the winner with the current prompt on a **holdout**, evaluation rows
   the repair loop did not see. For refinement, this is a no-regression check
   against the current workflow, not the model-migration requirement to clear
   the same absolute release thresholds.
5. Suggest fresh thresholds from the achieved holdout metrics, then use `report`
   to summarize saved evidence and `open-pr` to preview or create a pull request.

This differs from the model-change flow:

- `compare` tests a current **baseline** model against a proposed **candidate**
  model with the same files. It does not repair.
- `migrate --to ...` changes the model and repairs prompts to meet configured
  thresholds.
- `refine` keeps the model fixed and repairs prompts after data, labels, or
  behavior expectations change.
- `report` formats saved run evidence.
- `open-pr` turns eligible evidence and diffs into a preview or pull request.

## Before you start: audit labels

Run a label audit before spending repair tokens. It checks for duplicate or
near-duplicate examples with contradictory expected categories. Such conflicts
can cap the best achievable score because no stable rule can satisfy both rows.
Prompt repair cannot resolve that data problem.

The commands below install Driftless, copy the four-row bundled classifier,
validate its workflow contract, and audit its labels without an API key:

```bash
pip install driftless
driftless copy-example support-classifier --out-dir driftless-classifier-demo
cd driftless-classifier-demo
driftless validate -w support_classifier
driftless audit-labels -w support_classifier
```

Expect the fixture to establish the contract and demonstrate the audit command.
Four rows are a smoke test, not evidence that a production labeling policy is
consistent. Read [post 5](./05-audit-labels-before-you-trust-f1.md) for the full
audit workflow.

Provider-backed `refine` needs repair-generator credentials and can incur
repeated evaluation and token costs. The detailed walkthrough uses the separate
[support-classifier-svc](https://github.com/driftless-dev/support-classifier-svc)
testbed: 290 tickets, the same `driftless.yml`, and a different trigger from
post 1. It is not the bundled four-row fixture.

## Walkthrough

### 1. Choose the command from what changed

The trigger determines which variable to hold fixed:

| What changed | First check | Repair path |
|--------------|-------------|-------------|
| Model ID or provider endpoint | `compare` | `migrate --to ...` |
| Gold labels or evaluation inputs | `audit-labels` | `refine` |
| Both changed | Split the pull request if possible | Audit, then migrate/refine one variable at a time |

`migrate` changes the model and tries to satisfy the contract's absolute
thresholds. `refine` pins the model, maximizes the configured metric, checks
holdout performance against the current prompt, and prints suggested thresholds
derived from the refined holdout metrics. Those suggestions are review input,
not an automatic weakening of the committed contract. Changing one variable at
a time keeps the evidence interpretable.

### 2. Apply the policy change

The testbed's dataset builder includes 25 charge-reversal tickets. Two input
examples are:

```json
{"id": "t002", "text": "I need you to reverse the credit card payment because it was charged twice."}
{"id": "t021", "text": "Please reverse the payment on my latest invoice."}
```

Under the old policy, their gold label is `billing`: an adjustment to a charge.
Under the new policy, it is `refund`: the customer wants money returned for a
disputed charge.

The following helper changes the affected labels without hand-editing JSONL:

```bash
python evals/_apply_refund_policy.py
# policy update: re-labeled 25 charge-reversal ticket(s) -> 'refund'
```

On an applicable checkout, expect it to report 25 relabeled tickets. It uses the
same detector as the simulator,
`support_classifier.llm_client._is_charge_reversal`, so offline behavior stays
reproducible. On `main`, the policy may already be applied; then the script can
correctly report `0` changes. For a fresh demo, start from a commit before the
policy change or restore labels from Git history.

### 3. Refine while the model stays pinned

The next commands make classifier calls deterministic, provide credentials for
the separate LLM repair generator, run a strict label audit as part of refinement,
and create a pull request if the result is eligible:

```bash
export SUPPORT_CLASSIFIER_SIMULATE=1
export OPENAI_API_KEY=...  # LLM repair generator; simulator only replaces the harness
driftless refine -w support_classifier --strict-label-audit
driftless open-pr -w support_classifier --create
```

Notice that there is no `--to` argument. The model in `config/llm.yml` should not
change. Expect repair to edit allowed prompt files, evaluate attempts, and check
the winner on holdout against the current prompt. Unlike `migrate`, `refine` does
not require the winner to clear the same absolute threshold gate; it protects
against regression on unseen rows and reports suggested fresh thresholds from
what the holdout achieved. A successful pull request should keep evidence easy
to review: the label/input change belongs in its own commit or branch, the
Driftless pull request contains the prompt diff, model configuration remains
untouched, and the report shows the measured result and threshold suggestions.

`SUPPORT_CLASSIFIER_SIMULATE=1` replaces model calls made by the classification
harness. It does not replace the default `--generator llm`, which still needs
`OPENAI_API_KEY` in this testbed and may make repeated calls. To exercise
refinement orchestration without repair, use `--generator none`. If nothing
beats the current prompt, `refine` returns `NO_CHANGE`, keeps files untouched,
and exits 0 because there is no regression to block. This differs from
`migrate --generator none`: when the unchanged target misses release thresholds,
migration returns `BLOCKED`.

### 4. Read the prompt change as a policy change

Before repair, the prompt contains broad definitions:

```markdown
- billing: questions about invoices, charges, payments, or subscriptions
- refund: the customer wants their money returned
```

A successful real-model repair documented as scenario 3 in the testbed README
made the implicit policy explicit with wording like:

```markdown
- billing: ... including requests to reverse or correct erroneous charges
- refund: ... charged correctly but dissatisfied or no longer wish to pay
```

The exact wording may vary because LLM repair is nondeterministic. Reviewers
should ask whether the edit accurately expresses the product policy, not only
whether a score increased.

## How to interpret the results

On a documented live `gpt-4o-mini` run using `gpt-4o` as the repair generator
and all 290 tickets, the observed results were:

| Metric | Before refine | After refine (tuning) | Holdout |
|--------|---------------|------------------------|---------|
| F1 | 0.72 | 0.96 | **1.00** |
| Accuracy | 0.72 | 0.98 | — |

**F1** balances precision—the fraction of predictions for a class that were
right—and recall—the fraction of that class that was found. **Accuracy** is the
fraction of all rows predicted correctly. **Tuning** rows are visible to repair;
holdout rows are not. The holdout result therefore provides stronger release
evidence than the tuning result alone. In `refine`, holdout answers whether the
proposed prompt regresses relative to the current prompt on unseen rows. It is
not the same absolute-gate decision used by `migrate`. The CLI also reports
suggested thresholds based on the refined holdout metrics so maintainers can
review whether the committed policy should change.

Why was the starting score low? Real models labeled charge reversals as `refund`
about 92% of the time from their prior behavior, while scenario 3's product
policy placed many reversals in `billing`. The prompt had not stated that
counterintuitive rule. The model was not broken; the specification was implicit.

Production policies often use categories differently from everyday language.
For example, a password-reset ticket might belong to `security`, not `account`.
`refine` looks for clusters of failures that can reveal such missing rules,
rather than adding one isolated example without understanding the policy.

### Simulator evidence and live evidence answer different questions

The simulator is free and proves workflow and CI plumbing. Live LiteLLM runs,
with simulation disabled and `OPENAI_API_KEY` set, test actual provider behavior
and can require hundreds or thousands of calls over 290 rows.

Scenario 2, the charge-reversal relabel, is reproducible offline. Scenario 3,
the counterintuitive billing/refund policy on unchanged labels, appears only with
real models. The testbed therefore has both **Refine on label change**
(simulator) and **Real-model refine** (weekly/manual, live API) workflows.

## What happens when it fails?

Failure should narrow the next action:

- Conflicting near-duplicates mean the evaluation cannot define a stable target.
  Fix labels before running repair.
- A clean audit plus failures clustered around a policy boundary suggests the
  prompt does not state the new rule. Run `refine`.
- A clean audit plus scattered failures may mean the evaluation lacks coverage.
  Inspect the report before widening repair.
- A tuning improvement followed by holdout failure suggests overfitting. Do not
  release that repair.
- Missing provider credentials prevent LLM repair. With
  `refine --generator none`, no improving candidate produces `NO_CHANGE` and
  exit code 0; no files are committed. With `migrate --generator none`, a target
  that still misses absolute release gates produces `BLOCKED`.

To make CI stop immediately on contradictory labels, run:

```bash
driftless audit-labels -w support_classifier --fail
```

Expect a nonzero result when conflicts cross the audit's failure boundary. The
testbed runs this check on every pull request touching
`evals/tickets.*.jsonl` through
[audit-labels.yml](https://github.com/driftless-dev/support-classifier-svc/blob/main/.github/workflows/audit-labels.yml).

## Deeper example: a feedback batch

Production datasets often change through additions and relabels together. The
testbed's `evals/_apply_feedback_batch.py` adds 22 subscription-cancellation or
lifecycle tickets that were missing from version 1, and relabels two general
subscription inquiries from `billing` to `account`.

On live `gpt-4o-mini`, account recall on the new tickets rose from `0.11`—16 of
18 were predicted as `billing`—to `1.00` after refinement added a lifecycle
rule. The offline simulator's accuracy rose from `0.936` to `1.000`.

The Git-backed command path remains: apply the script, run `refine`, then prepare
the pull request. If labels instead live outside Git and `eval.data_source` is
configured, the following commands can detect a change and preview actions:

```bash
driftless poll             # detect configured external-data changes
driftless poll --act       # preview refine + PR/issue operations
```

Expect plain `poll` to compare the configured source with saved dataset state.
`poll --act` additionally previews refinement and pull-request/issue operations
for a meaningful change. This testbed stores labels in Git, so its path-filtered
workflow is the supported path; `poll` is not a substitute unless
`eval.data_source` is configured.

## Deeper automation: trigger on the data

For in-repository evaluation data, Git is the change detector. The testbed's
[refine-on-label-change workflow](https://github.com/driftless-dev/support-classifier-svc/blob/main/.github/workflows/refine-on-label-change.yml)
uses this path filter:

```yaml
on:
  push:
    branches: [main]
    paths:
      - "evals/tickets.labels.jsonl"
      - "evals/tickets.inputs.jsonl"
```

Expect the workflow to run when inputs or labels change. `prompts/` is
deliberately absent, so a prompt-only refinement pull request does not trigger
itself again.

The job then:

1. runs `driftless audit-labels -w support_classifier --fail`;
2. runs `driftless refine -w support_classifier --strict-label-audit` with
   `SUPPORT_CLASSIFIER_SIMULATE=1`—the harness is offline, but the LLM repair
   generator still requires `OPENAI_API_KEY`;
3. runs `driftless open-pr -w support_classifier --create`; and
4. uploads `.driftless/reports/` to the GitHub Actions summary and artifacts.

You can test it by committing and pushing a label change or manually dispatching
the workflow from GitHub Actions.

## Next steps

- If the provider model changes, return to
  [post 1 and `migrate`](./01-model-swap-is-not-a-migration.md).
- To schedule `plan` across both workflows, continue to
  [post 3](./03-dependabot-for-prompts-in-ci.md).
- For the larger exercise, clone
  [support-classifier-svc](https://github.com/driftless-dev/support-classifier-svc),
  run `_apply_refund_policy.py`, audit the labels, and then run `refine`.
