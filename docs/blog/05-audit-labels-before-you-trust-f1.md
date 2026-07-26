# Your offline F1 is lying because the labels conflict

## The use case

You trust your offline eval. Macro-F1 on a few hundred labeled tickets is how
you decide whether a model migration or prompt refine is safe. After a labeling
policy change (or a messy annotation pass), you run `refine` and watch F1 stall
around 0.85. The team assumes the prompt is bad. Someone rewrites category
definitions three times. Someone else proposes a bigger model. Iterations and
API spend pile up; holdout never clears the bar.

The actual problem is upstream of the prompt. Buried in the eval set are
near-duplicate tickets — same customer intent, almost the same wording — with
**disagreeing gold labels**. One row says `billing`, its twin says `refund`. No
prompt can satisfy both. Every optimizer report looks like "the model is flaky"
or "repair isn't converging," when the oracle itself is contradictory.

Until you find and fix those conflicts, F1 has a hard ceiling that has nothing
to do with GPT. The use case is: **prove the gold labels are internally
consistent before you spend a migration or refine budget.**

**What driftless does here:** `audit-labels` finds exact and near-duplicate
inputs with label disagreements *before* `migrate` / `refine` burn iterations.
CI can `--fail` on that report; migrations can `--strict-label-audit`.

Grounded in
[support-classifier-svc](https://github.com/driftless-dev/support-classifier-svc)
(290 labeled tickets) and the same CLI you run in Actions today.

---

## The silent F1 ceiling

Macro-F1 on an imbalanced set (testbed builder: technical ~105 / billing ~95 /
account ~50 / refund ~40) already hides per-class pain. Label noise is worse:
if two inputs normalize to the same text and gold says `billing` vs `refund`,
**no prompt** can hit 1.0 accuracy on both.

That looks like "the model is flaky" or "repair isn't converging." It is a
**data** problem.

---

## Clean baseline on the testbed

```bash
git clone https://github.com/driftless-dev/support-classifier-svc
cd support-classifier-svc
pip install driftless

driftless audit-labels -w support_classifier
```

Expected on `main` (July 2026):

```
Label audit: `support_classifier` (290 labeled records)

No duplicate or near-duplicate inputs with disagreeing labels.
```

A clean audit does **not** mean the labeling *policy* is finished — only that
the JSONL is internally consistent. After
`python evals/_apply_refund_policy.py` ([post 2](./02-when-labels-move-refine-not-remodel.md)),
audit should still pass: 25 charge-reversals move together to `refund`.

---

## What a conflict looks like (reproduce in 30 seconds)

Support-classifier tickets look like this when annotators disagree on the same
intent. Paste into a scratch workspace (or temporarily edit eval JSONL on a
branch):

```jsonl
{"id": "a", "text": "Please refund my order"}
{"id": "b", "text": "please refund my order"}
{"id": "c", "text": "I forgot my password"}
{"id": "d", "text": "I forgot my  password"}
```

```jsonl
{"id": "a", "category": "refund"}
{"id": "b", "category": "billing"}
{"id": "c", "category": "account"}
{"id": "d", "category": "technical"}
```

Normalization lowercases and collapses whitespace, so `a`/`b` and `c`/`d` are
**exact duplicates** with disagreeing labels. Real `audit-labels` output:

```
Label audit: `ticket_classifier` (4 labeled records)

Exact duplicates with label disagreement (2 group(s)):
  - 2 rows, labels: 'billing', 'refund'
      id='a' label='refund': Please refund my order
      id='b' label='billing': please refund my order
  - 2 rows, labels: 'account', 'technical'
      id='c' label='account': I forgot my password
      id='d' label='technical': I forgot my password

These disagreements cap achievable accuracy — fix labels or dedupe inputs
before expecting refine / migrate to converge.
```

Near-duplicates (Jaccard ≥ 0.85 by default) get a separate section with a
similarity score — e.g. two charge-reversal phrasings labeled `billing` vs
`refund` after a messy policy edit.

```bash
driftless audit-labels -w support_classifier --fail   # exit 1 when conflicts exist
```

---

## Wire it where tokens get spent

### 1. Path-filtered CI (testbed)

[audit-labels.yml](https://github.com/driftless-dev/support-classifier-svc/blob/main/.github/workflows/audit-labels.yml):

```yaml
on:
  pull_request:
    paths:
      - "evals/tickets.labels.jsonl"
      - "evals/tickets.inputs.jsonl"
  push:
    branches: [main]
    paths:
      - "evals/tickets.labels.jsonl"
      - "evals/tickets.inputs.jsonl"

jobs:
  audit:
    steps:
      - run: driftless audit-labels -w support_classifier --fail
```

Any PR that introduces conflicting gold labels fails **before** merge.

### 2. Before refine / migrate

The testbed's refine and migrate workflows already call `audit-labels --fail`,
then pass `--strict-label-audit` into the optimizer:

```bash
driftless refine -w support_classifier --strict-label-audit
driftless migrate -w support_classifier --to gpt-4o-mini --strict-label-audit
```

Scaffold the same pattern:

```bash
driftless init-ci --audit-labels
```

---

## Decision tree: labels vs prompt vs model

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| Audit reports conflicts | Gold label noise / duplicate rows | Fix or dedupe JSONL; re-audit |
| Clean audit, F1 drops after policy relabel | Prompt lag | `refine` ([post 2](./02-when-labels-move-refine-not-remodel.md)) |
| Clean audit, naive swap fails schema / F1 | Model + prompt | `migrate` ([post 1](./01-model-swap-is-not-a-migration.md)) |
| Clean audit, cost row looks good, quality dips | Candidate too weak or prompt debt | Compare → migrate; don't "save" on a blocked run ([post 4](./04-cheaper-model-same-quality-bar.md)) |

**Charge-reversal tip:** after `_apply_refund_policy.py`, audit should stay
green. If it fails, someone edited labels inconsistently — not that the policy
script "broke" F1.

---

## What audit does *not* do

- It does not re-label tickets for you.
- It does not judge whether `billing` vs `refund` is the *right* product policy
  — only whether the dataset agrees with itself.
- It applies to **classification** workflows (`eval.label_field`). Pass/fail and
  judge-graded workflows use other preflights ([post 6](./06-trust-your-llm-judge.md)).

---

## Next steps

- Run `audit-labels` on your eval set before the next `refine`
- Add the path-filtered workflow (or `init-ci --audit-labels`)
- Then return to [post 2](./02-when-labels-move-refine-not-remodel.md) or
  [post 1](./01-model-swap-is-not-a-migration.md) with a trustworthy oracle
