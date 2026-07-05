# Example Review Artifact

This page shows the review artifact Driftless produces when a model migration
is unsafe. It uses the bundled `rag-qa` example and does not require provider
keys.

## Commands

```bash
driftless copy-example rag-qa --out-dir driftless-rag-demo
cd driftless-rag-demo
driftless compare -w rag_qa --to gpt-4o-mini
driftless migrate -w rag_qa --to gpt-4o-mini --generator none
driftless report -w rag_qa --raw
driftless open-pr -w rag_qa
```

`--generator none` intentionally makes no prompt edits. It exercises the
failure-path UX: the target is cheaper, but not shippable, so Driftless prepares
an issue instead of a PR.

## Dry-Run GitHub Action

```text
Dry run — ISSUE
  - open issue: 'driftless: migration blocked: rag_qa -> gpt-4o-mini'

re-run with --create to apply (requires git + gh authenticated).
```

## Issue Body

```markdown
# Model Migration: `rag_qa`

Migrates `rag_qa` from `gpt-4` to `gpt-4o-mini`.

**Status:** `blocked`

**Iterations:** 1

## Summary

- **Status:** `blocked` · **Iterations:** 1 · **Attempts:** 0 (0 accepted)
- **Tuning score:** 1.000 → 0.000 (-1.000)

## Result

Could not recover acceptable quality on the target model.

| Metric | Current | Target (orig files) | Target (migrated) |
|---|---:|---:|---:|
| Score / pass-rate | 1.000 | 0.000 | 0.000 |
| Schema error rate | 0.0% | 0.0% | 0.0% |
| Refusal rate | 0.0% | 0.0% | 0.0% |
| Total cost | 0.036 | 0.008 | 0.008 |

## Confidence Caveats

- Small dataset: 4 labeled examples (< 30). Metrics and thresholds are
  low-confidence; add more labeled rows for a reliable migration decision.
- Small holdout: 2 examples, so each one shifts a metric by ~50%. A passing
  holdout may not generalize.

## Changes Made

- No changes were committed.

## Unmet Thresholds

- FAIL `min_score`: 0.000 >= 0.86

## Suggested Fallback Candidates

- `gpt-4o`

## Recommendation

Do not migrate to this model yet. See remaining clusters and consider a fallback
candidate.
```

## What This Proves

- Driftless does not open a migration PR when thresholds fail.
- The artifact gives reviewers the scorecard, unmet threshold, confidence
  caveats, and suggested fallback.
- The same `open-pr` path will open a PR instead of an issue when a migration
  succeeds and produces file changes.

## Still Needed

A public successful PR with prompt/config diffs is still the best final launch
artifact. That requires either a provider-backed repair run or a future
deterministic demo repair generator.

