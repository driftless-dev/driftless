# Audit your eval labels before you trust F1

**Status:** outline, expand next — the testbed already has the CI gate. This
post needs an intentional conflicting-label branch, captured CLI output, and a
failed check screenshot.

**Use case:** `refine` stalls at F1 0.85. The team blames the prompt; near-duplicate
tickets in the eval disagree on gold labels.

---

## Testbed hook

Every PR touching eval data runs:

[`.github/workflows/audit-labels.yml`](https://github.com/driftless-dev/support-classifier-svc/blob/main/.github/workflows/audit-labels.yml)

```yaml
on:
  pull_request:
    paths:
      - "evals/tickets.labels.jsonl"
      - "evals/tickets.inputs.jsonl"
steps:
  - run: driftless audit-labels -w support_classifier --fail
```

`refine-on-label-change.yml` and `migrate-on-model-change.yml` call the same
audit before spending tokens. Migrations use `--strict-label-audit`.

Publishable version should show one bad row pair end to end:

| Evidence | Reader takeaway |
|----------|-----------------|
| Two near-duplicate ticket texts with different labels | The model cannot learn a stable target |
| `driftless audit-labels --fail` output | The tool catches the ceiling before repair |
| Failed GitHub check | The gate blocks noisy eval updates |
| Fixed-label rerun | The path back to a trustworthy eval is simple |

---

## Outline

### 1. The silent ceiling
290 tickets, class imbalance (technical 105 / billing 95 / account 50 / refund 40
in the builder) — macro-F1 can hide per-class confusion; audit finds *label*
conflicts, not just model errors.

### 2. Commands
```bash
driftless audit-labels -w support_classifier
driftless audit-labels -w support_classifier --fail   # CI exit code
```

### 3. When to fix labels vs prompt
| Symptom | Likely cause | Action |
|---------|--------------|--------|
| Audit reports duplicate-input conflicts | Gold label noise | Fix JSONL, re-run |
| Clean audit, low F1 after policy change | Prompt lag | `refine` ([post 2](./02-when-labels-move-refine-not-remodel.md)) |
| Clean audit, naive swap fails schema | Model + prompt | `migrate` ([post 1](./01-model-swap-is-not-a-migration.md)) |

### 4. Relation to charge-reversal scenario
After `_apply_refund_policy.py`, labels are *consistent* with the new policy —
audit should pass. Failures there mean someone edited labels inconsistently, not
that the policy script ran.

### 5. CTA
- Wire `init-ci` label-audit workflow
- Run audit before first `refine` on a new eval set
- Treat a failed audit as data work, not prompt work

---

## Screenshots
- `audit-labels` CLI output on a branch with an intentional label conflict
- Failed CI check on an eval PR
