# Eval Confidence

Driftless reports whether a candidate passed *your* thresholds on *this* split.
That is a quality gate, not a statistical significance test. Use this page
before treating a `pass` as production evidence.

**Holdout** means eval rows the repair loop never trains on. A pass on four
demo rows is not the same as a pass on a real eval.

## What the engine already warns about

`migrate` and `refine` attach confidence caveats when:

- the labeled set has fewer than 30 examples; or
- holdout is required and has fewer than 15 examples.

A four-row bundled demo can still `PASS` after `--generator fixture`. That
proves orchestration, not that the model is safe to ship.

## Recommended sizes

| Decision | Minimum labeled rows | Holdout | Extra |
|---|---|---|---|
| Smoke / command wiring | 4+ | any | Do not use as launch evidence. |
| First real integration | 30–100 | ≥15, about 30% | Review every editable diff. |
| Shipping a model change | 100+ representative rows | ≥15, about 40% | Prefer `migration.split_seed_count: 3` or higher. |
| High-risk / regulated | 500+ or a sampled then full holdout | ≥15 | Multiple seeds plus human review. |

`migration.split_seed_count` (1–5) re-runs tuning selection across shuffled
splits and keeps a candidate only if it remains the winner. It is a stability
check, not a p-value.

## How to raise confidence

1. `driftless audit-labels -w <workflow> --fail` before repair.
2. Keep `migration.holdout_required: true`.
3. Raise `split_seed_count` for high-risk changes:

   ```yaml
   migration:
     holdout_required: true
     split_seed_count: 3
   ```

4. For judge-graded tasks, pass `driftless judge-check -w <workflow> --enforce`
   before `migrate`.
5. Read the report's confidence caveats. A cheap target that fails `min_f1` is
   blocked for a reason; a tiny eval that passes is still noisy.

## What this does not claim

- No confidence interval or hypothesis test is computed.
- Live provider behavior can differ from a deterministic fixture.
- `--generator fixture` only reproduces bundled-example repairs.

See [`COST_AND_BUDGETS.md`](./COST_AND_BUDGETS.md) for spend defaults and
[`LIMITS.md`](./LIMITS.md) for the supported product surface.
