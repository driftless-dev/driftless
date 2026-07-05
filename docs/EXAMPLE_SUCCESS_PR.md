# Example Successful PR Artifact

This page shows the evidence artifact Driftless produces when a migration
succeeds and changes prompt/config files. It uses the bundled
`support-classifier` example and the same report/PR planning code that powers
`driftless open-pr`.

## Commands

```bash
driftless copy-example support-classifier --out-dir driftless-classifier-demo
cd driftless-classifier-demo
driftless compare -w support_classifier --to gpt-4o-mini
driftless migrate -w support_classifier --to gpt-4o-mini
driftless report -w support_classifier --raw
driftless open-pr -w support_classifier
```

The saved fixture below represents the successful path: target quality regresses
on the unmodified prompt, a prompt edit restores the contract, and `open-pr`
chooses a PR rather than an issue.

## Dry-Run GitHub Action

```text
Dry run - PR
  - create branch: driftless/support_classifier-to-gpt-4o-mini
  - commit files: prompts/classifier.md
  - open PR: 'chore: migrate support_classifier from gpt-4 to gpt-4o-mini'

re-run with --create to apply (requires git + gh authenticated).
```

## Reviewer Summary

```text
Title: chore: migrate support_classifier from gpt-4 to gpt-4o-mini
Branch: driftless/support_classifier-to-gpt-4o-mini
Files: prompts/classifier.md
```

## Prompt Diff

```diff
--- a/prompts/classifier.md
+++ b/prompts/classifier.md
@@ -1,3 +1,5 @@
 Classify each support ticket by its main customer intent.
 
-Return a short category label.
+Use exact labels only: billing, technical, account, shipping.
+
+Return one short category label and no extra text.
```

## PR Body

````markdown
# Model Migration: `support_classifier`

Migrates `support_classifier` from `gpt-4` to `gpt-4o-mini`.

**Status:** `pass`

**Iterations:** 1

## Summary

- **Status:** `pass` · **Iterations:** 1 · **Attempts:** 1 (1 accepted)
- **Tuning F1:** 1.000 → 1.000 (+0.000)
- **Holdout F1:** 1.000
- **Files changed:** `prompts/classifier.md`

## Result

Migration passed configured thresholds.

| Metric | Current | Target (orig files) | Target (migrated) |
|---|---:|---:|---:|
| F1 | 1.000 | 0.000 | 1.000 |
| Precision | 1.000 | 0.000 | 1.000 |
| Recall | 1.000 | 0.000 | 1.000 |
| Accuracy | 1.000 | 0.000 | 1.000 |
| Schema error rate | 0.0% | 0.0% | 0.0% |
| Refusal rate | 0.0% | 0.0% | 0.0% |
| Avg latency (ms) | 6 | 6 | 6 |
| Total cost | 0.024 | 0.004 | 0.004 |

## Confidence Caveats

- Small dataset: 4 labeled examples (< 30). Metrics and thresholds are
  low-confidence; add more labeled rows before treating this as production
  evidence.

## Proposed Diffs

Unified diff vs. the pre-migration editable files:

<details><summary>`prompts/classifier.md` (4 changed line(s))</summary>

```diff
--- a/prompts/classifier.md
+++ b/prompts/classifier.md
@@ -1,3 +1,5 @@
 Classify each support ticket by its main customer intent.
 
-Return a short category label.
+Use exact labels only: billing, technical, account, shipping.
+
+Return one short category label and no extra text.
```

</details>

## Changes Made

- Edited `prompts/classifier.md`
- Edit size: 3 changed line(s) vs. the original.
- Output schema and read-only files were preserved.

## Holdout Validation

- PASS `min_f1`: 1.000 >= 0.9
- PASS `max_cost_increase`: -83.3% <= +20%

## Remaining Risks

- No residual failure clusters detected.
- Human review recommended before merge.

## Optimization Trajectory

Best tuning F1 by iteration: 1.000

Failure clusters across iterations (count per iteration):

- `misclassification:billing -> general`: 1 -> 0
- `misclassification:technical -> general`: 1 -> 0
- `misclassification:account -> general`: 1 -> 0
- `misclassification:shipping -> general`: 1 -> 0

## Recommendation

Approve migration. Human review recommended before merge.

## Full Run Data

- Machine-readable trace: `.driftless/migrations/support_classifier.json`
- Markdown report: `.driftless/reports/support_classifier.md`
- Inspect locally: `driftless view -w support_classifier` or
  `driftless report -w support_classifier`
````

## What This Proves

- Driftless opens a PR only when thresholds pass and there are committed
  prompt/config changes.
- Reviewers get the exact prompt diff, before/after scorecard, threshold checks,
  confidence caveats, and remaining-risk guidance.
- The migration keeps read-only application code and eval data untouched.
