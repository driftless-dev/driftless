# Your offline F1 is lying because the labels conflict

## The problem and the outcome

Your team uses a few hundred support tickets to decide whether a prompt or model
change is safe. Each ticket has a **label**, such as `billing` or `refund`.
The reviewed expected labels are **gold data**: the answers used to score model
predictions during an evaluation.

After a labeling policy changes, F1 stalls around `0.85`. The team rewrites the
prompt, tries a larger model, and spends more on API calls. Nothing clears the
quality bar.

The problem may be in the gold data. Two tickets can express the same customer
intent but carry different expected labels. One says `billing`; its twin says
`refund`. A model cannot produce both answers for the same input, so the
contradiction caps achievable performance before prompt quality or model choice
enters the discussion.

The outcome you want is a clean label audit before any `refine` or `migrate`
run. Driftless can report conflicting duplicates, fail CI when they appear, and
stop repair before it spends iterations against an inconsistent answer key.

## Mental model

`audit-labels` compares inputs that have different gold labels:

- An **exact duplicate** becomes identical after Driftless lowercases text,
  removes leading and trailing space, and collapses repeated whitespace.
- A **near duplicate** is not identical but shares most of the same unique word
  tokens.
- **Jaccard similarity** measures that overlap: the number of unique tokens in
  both texts divided by the number of unique tokens in either text. Identical
  token sets score `1.0`; no shared tokens score `0.0`.

By default, Driftless reports near-duplicate pairs at Jaccard similarity
`0.85` or higher when their labels disagree. `--near-threshold` changes that
boundary. Raising it reports fewer, more similar pairs; lowering it reports more
candidates and may surface domain boilerplate.

The main quality metric here is **macro-F1**. F1 combines precision and recall
for one class. Macro-F1 computes F1 for each label and takes an unweighted
average, so a small class counts as much as a large class. That is useful on the
testbed's imbalanced distribution—technical about 105, billing about 95,
account about 50, and refund about 40—but no metric can repair contradictory
gold answers.

## Prerequisites

- A classification workflow in `driftless.yml` with `eval.label_field`
- Input and gold-label JSONL files
- Stable record IDs through `eval.id_field`, or matching input and label counts
- No provider key; label auditing is local and key-free

The audit applies to classification workflows. Pass/fail and judge-graded
workflows use different preflight checks.

## Walkthrough 1: verify the bundled fixture

Install Driftless, copy the four-row support-classifier fixture, enter the
directory, and audit its configured workflow:

```bash
pip install driftless
driftless copy-example support-classifier --out-dir driftless-classifier-demo
cd driftless-classifier-demo
driftless audit-labels -w support_classifier
```

The expected result reports **4 labeled records** and no exact or near-duplicate
inputs with disagreeing labels. This confirms the command and contract wiring
without a provider key.

The bundled fixture is only a smoke test. It does not show that a larger
production dataset is consistent. Audit the full representative evaluation
before spending provider tokens on `migrate` or `refine`.

## Walkthrough 2: audit the separate 290-row testbed

Clone the external
[support-classifier-svc](https://github.com/driftless-dev/support-classifier-svc)
testbed, enter it, install Driftless, and run the same audit:

```bash
git clone https://github.com/driftless-dev/support-classifier-svc
cd support-classifier-svc
pip install driftless
driftless audit-labels -w support_classifier
```

Expected on `main` in July 2026:

```text
Label audit: `support_classifier` (290 labeled records)

No duplicate or near-duplicate inputs with disagreeing labels.
```

This means the JSONL files are internally consistent under the audit rules. It
does not prove that the team's labeling policy is correct or complete.

The fixture distinction matters. Running
`python evals/_apply_refund_policy.py` from [post
2](./02-when-labels-move-refine-not-remodel.md) changes 25 charge-reversal
tickets together to `refund`. The audit should remain clean because the policy
was applied consistently.

## Walkthrough 3: reproduce a conflict safely

Start in the bundled `driftless-classifier-demo` directory from Walkthrough 1.
Keep its original contract and data unchanged by making a scratch contract and
two scratch JSONL files:

```bash
cp driftless.yml driftless.conflict.yml
mkdir -p evals/scratch
```

Create the scratch input file:

```bash
cat > evals/scratch/conflict-inputs.jsonl <<'JSONL'
{"id": "a", "text": "Please refund my order"}
{"id": "b", "text": "please refund my order"}
{"id": "c", "text": "I forgot my password"}
{"id": "d", "text": "I forgot my  password"}
JSONL
```

Create the matching gold-label file:

```bash
cat > evals/scratch/conflict-labels.jsonl <<'JSONL'
{"id": "a", "label": "refund"}
{"id": "b", "label": "billing"}
{"id": "c", "label": "account"}
{"id": "d", "label": "technical"}
JSONL
```

The bundled fixture calls its gold field `label`, so this scratch file does too.
If your own JSONL uses a field such as `category`, set `label_field: category`
instead; the contract value must match the JSON key.

Open `driftless.conflict.yml`. Under
`workflows.support_classifier`, keep the other settings unchanged and repoint
these real Driftless contract fields:

```yaml
workflows:
  support_classifier:
    run:
      input_path: evals/scratch/conflict-inputs.jsonl
    eval:
      id_field: id
      labels_path: evals/scratch/conflict-labels.jsonl
      label_field: label
```

`run.input_path` selects the records to inspect. `eval.labels_path` selects the
gold file, `eval.id_field` joins the two files by `id`, and
`eval.label_field` names the expected-answer key in each gold record.

Now run the audit against the scratch contract rather than the untouched
`driftless.yml`:

```bash
driftless audit-labels -w support_classifier --contract driftless.conflict.yml
```

Lowercasing and whitespace normalization make `a` and `b` exact duplicates.
They also make `c` and `d` exact duplicates. Each pair has conflicting labels.
Real `audit-labels` output is:

```text
Label audit: `support_classifier` (4 labeled records)

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

The decision is to inspect the source policy, correct the wrong labels, or
remove accidental duplicate rows. Do not tune a prompt to satisfy both answers.
Near-duplicate conflicts appear in a separate report section with a similarity
score, such as two charge-reversal phrasings labeled `billing` and `refund`.

To use the audit as a gate, add `--fail`:

```bash
driftless audit-labels -w support_classifier --fail
```

The report stays readable, and the process exits with code `1` when conflicts
exist. That non-zero exit lets CI stop the workflow.

## How to interpret audit results

| Result | Likely cause | Next decision |
|--------|--------------|---------------|
| Audit reports conflicts | Gold-label noise or duplicate rows | Fix or deduplicate JSONL, then audit again |
| Clean audit, F1 drops after policy relabeling | Prompt no longer expresses the policy | Run `refine` ([post 2](./02-when-labels-move-refine-not-remodel.md)) |
| Clean audit, naive model swap fails schema or F1 | Model and prompt do not transfer together | Run `migrate` ([post 1](./01-model-swap-is-not-a-migration.md)) |
| Clean audit, cost candidate is cheaper but quality dips | Candidate is too weak or prompt repair is needed | Compare, then migrate; do not ship a blocked run ([post 4](./04-cheaper-model-same-quality-bar.md)) |

After `_apply_refund_policy.py`, a failed audit means labels were changed
inconsistently. It does not mean that the intended refund policy itself lowered
F1.

## Walkthrough 4: put the audit before token spending

GitHub Actions is GitHub's service for repository automation. A workflow is a
YAML file containing jobs and command steps. A **path filter** starts a workflow
only when selected files change.

The testbed's hand-authored
[audit-labels.yml](https://github.com/driftless-dev/support-classifier-svc/blob/main/.github/workflows/audit-labels.yml)
runs for pull requests and pushes that touch either evaluation JSONL:

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

The expected behavior is audit-first: a pull request that introduces
conflicting gold labels fails before merge and before repair spends tokens.

The testbed's hand-authored refine and migrate workflows use the same ordering.
They run `audit-labels --fail`, then make the optimizer enforce the check with
`--strict-label-audit`:

```bash
driftless refine -w support_classifier --strict-label-audit
driftless migrate -w support_classifier --to gpt-4o-mini --strict-label-audit
```

`--strict-label-audit` turns detected conflicts into a blocking exit instead of
the default warning. Without strict mode, `refine` and `migrate` warn about
conflicts and explain how to block or silence the preflight.

To generate standard GitHub Actions workflows containing this pattern, run:

```bash
driftless init-ci --audit-labels
```

Review the generated files before committing them. They are generic scaffolds,
not the hand-authored testbed workflows shown above.

## Failure and safety behavior

- `audit-labels --fail` exits `1` when conflicts are found.
- `refine` and `migrate` warn by default; `--strict-label-audit` blocks.
- The audit does not relabel tickets.
- It checks internal consistency, not whether `billing` or `refund` is the
  correct product policy.
- Near-duplicate detection compares token sets and can produce domain-specific
  candidates; adjust `--near-threshold` after reviewing examples.
- The audit applies only to classification workflows with `eval.label_field`.
  Pass/fail and judge-graded workflows use other preflights ([post
  6](./06-trust-your-llm-judge.md)).

## Next steps

1. Run `audit-labels` on the full evaluation set.
2. Add the path-filtered workflow or generate a starting point with
   `driftless init-ci --audit-labels`.
3. After the audit is clean, return to [prompt refinement](./02-when-labels-move-refine-not-remodel.md)
   or [model migration](./01-model-swap-is-not-a-migration.md) with a trustworthy
   answer key.
