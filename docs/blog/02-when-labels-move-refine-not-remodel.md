# When labels move, refine — don't re-model

**Use case:** Support ops decides charge reversals are **refunds**, not
**billing**. Nobody touches the model string. Accuracy on the eval set drops
anyway — because "correct" changed, not because GPT got worse.

**What driftless does:** pin the model, re-optimize allowed prompt files against
the new gold labels, validate on holdout, open a PR.

Again we use
[support-classifier-svc](https://github.com/driftless-dev/support-classifier-svc)
— same 290-ticket classifier, same `driftless.yml`, different trigger.

---

## Same repair loop, different variable

| | Model migration (`migrate`) | Dataset refine (`refine`) |
|---|---|---|
| What moved | Provider model ID | Gold labels (or inputs) |
| Model | Changes (`--to gpt-4o-mini`) | **Pinned** |
| Objective | Meet `thresholds:` in contract | Maximize metric; suggest new thresholds |
| Testbed trigger | `gpt-3.5-turbo` deprecation | Label policy update |

If you bump the model when only labels changed, you're debugging the wrong knob.

Use the trigger to choose the tool:

| What changed | First check | Repair path |
|--------------|-------------|-------------|
| Model ID or provider endpoint | `compare` | `migrate --to ...` |
| Gold labels or eval inputs | `audit-labels` | `refine` |
| Both changed | Split the PR if possible | Audit, then migrate/refine one variable at a time |

---

## The policy change (concrete tickets)

The dataset builder seeds **25 charge-reversal tickets**. They read like billing
but, after a policy meeting, should be **`refund`**.

Example rows from `evals/tickets.inputs.jsonl`:

```json
{"id": "t002", "text": "I need you to reverse the credit card payment because it was charged twice."}
{"id": "t021", "text": "Please reverse the payment on my latest invoice."}
```

**Before policy:** gold label `billing` (adjustment on a charge).  
**After policy:** gold label `refund` (customer wants money back on a charge
they dispute).

The testbed ships a one-command event script — no hand-editing JSONL:

```bash
python evals/_apply_refund_policy.py
# policy update: re-labeled 25 charge-reversal ticket(s) -> 'refund'
```

That script uses the same detector as the simulator
(`support_classifier.llm_client._is_charge_reversal`) so offline runs stay
reproducible. On `main` today the policy may already be applied (running the
script prints `0` changes); for a fresh demo, start from a commit before the
policy or restore labels from git history.

Then:

```bash
export SUPPORT_CLASSIFIER_SIMULATE=1
driftless refine -w support_classifier --strict-label-audit
driftless open-pr -w support_classifier --create
```

No `--to`. The model in `config/llm.yml` never changes.

The resulting PR should be boring in the best way: label/input diff in one
commit or branch, prompt diff in the Driftless PR, model config untouched, and a
report that says the repaired prompt meets the current eval policy.

---

## What the repair actually edits

The simulator is calibrated so the **old** prompt scores well on the **old**
labels and poorly after relabeling — until category definitions catch up.

A successful real-model repair (documented in the testbed README, scenario 3)
rewrote `prompts/system.md` from:

```markdown
- billing: questions about invoices, charges, payments, or subscriptions
- refund: the customer wants their money returned
```

to something like:

```markdown
- billing: ... including requests to reverse or correct erroneous charges
- refund: ... charged correctly but dissatisfied or no longer wish to pay
```

**Observed on live `gpt-4o-mini`** (repair generator: `gpt-4o`, 290 tickets):

| Metric | Before refine | After refine (tuning) | Holdout |
|--------|---------------|------------------------|---------|
| F1 | 0.72 | 0.96 | **1.00** |
| Accuracy | 0.72 | 0.98 | — |

Why so low before? Real models label charge reversals `refund` ~92% of the time
from priors alone — but this product's policy says many reversals are `billing`.
The prompt never stated the rule; the model wasn't "broken," the spec was
implicit.

> Counterintuitive gold labels are common in production (password-reset →
> security, not account). `refine` is built to discover explicit rules from
> failure clusters, not just add a few-shot example.

---

## Scenario 4: feedback batch (messier, more realistic)

Pure relabels are rare. The testbed also ships
`evals/_apply_feedback_batch.py`:

- **+22 new tickets** — subscription cancellation / lifecycle requests missing
  from v1 of the eval set
- **2 relabels** — general subscription *inquiries* `billing` → `account`

On real `gpt-4o-mini`, **account recall on the new tickets** goes from **0.11**
(16/18 predicted `billing`) to **1.00** after refine adds a lifecycle rule.
Offline simulator: accuracy **0.936 → 1.000**.

Same command path: apply script → `refine` → PR. Exercises `poll`'s meaningful-
change detection if labels live outside git.

---

## CI: path filter on the file that actually changed

In-repo eval data → **git is the change detector**. The testbed workflow
[refine-on-label-change.yml](https://github.com/driftless-dev/support-classifier-svc/blob/main/.github/workflows/refine-on-label-change.yml):

```yaml
on:
  push:
    branches: [main]
    paths:
      - "evals/tickets.labels.jsonl"
      - "evals/tickets.inputs.jsonl"
```

Notice **`prompts/` is not in `paths`** — otherwise the refine PR would
re-trigger itself.

Job steps (abbreviated):

1. `driftless audit-labels -w support_classifier --fail`
2. `driftless refine -w support_classifier --strict-label-audit` with
   `SUPPORT_CLASSIFIER_SIMULATE=1` (harness offline; repair generator still
   uses `OPENAI_API_KEY` when set)
3. `driftless open-pr -w support_classifier --create`
4. Upload `.driftless/reports/` to the Actions summary + artifacts

**Try it:** commit a label change locally, push, or dispatch the workflow from
Actions.

---

## Preflight: contradictory gold labels

Before spending tokens:

```bash
driftless audit-labels -w support_classifier --fail
```

Near-duplicate ticket text with **different** gold categories caps achievable F1.
The testbed runs audit on every PR touching `evals/tickets.*.jsonl`
([audit-labels.yml](https://github.com/driftless-dev/support-classifier-svc/blob/main/.github/workflows/audit-labels.yml)).

More: [post 5 outline](./05-audit-labels-before-you-trust-f1.md).

This is the boundary between data cleanup and prompt repair:

| Audit result | Interpretation | Action |
|--------------|----------------|--------|
| Conflicting near-duplicates | The eval cannot define a stable target | Fix labels first |
| Clean audit, new failures cluster around a policy edge | Prompt does not say the new rule | Run `refine` |
| Clean audit, failures are scattered | The eval may need more coverage | Inspect report before widening repair |

---

## Simulator vs real API (when to use which)

| Mode | Command | Cost | Proves |
|------|---------|------|--------|
| Simulator | `SUPPORT_CLASSIFIER_SIMULATE=1` | Free | Workflow + CI plumbing |
| Real LiteLLM | unset simulate, set `OPENAI_API_KEY` | Hundreds–thousands of calls on 290 rows | Repair holds on provider behavior |

Scenario 2 (charge-reversal relabel) is reproducible offline. Scenario 3
(counterintuitive billing/refund policy on **unchanged** labels) only bites on
real models — that's why the testbed has both **Refine on label change**
(simulator) and **Real-model refine** (weekly/manual, real API).

---

## Next steps

- **Post 1:** model deprecation → [`migrate`](./01-model-swap-is-not-a-migration.md)
- **Post 3:** weekly `plan` across both workflows → [CI post](./03-dependabot-for-prompts-in-ci.md)
- Clone the testbed, run `_apply_refund_policy.py`, then `refine`
