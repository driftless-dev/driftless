# Cut inference cost without breaking your quality bar

**Status:** outline only — do not publish until the testbed has an *active*
baseline model and a real `plan`/`compare` capture showing measured savings.

**Use case:** `support_classifier` runs on `gpt-4o` today; finance wants 20%+
savings; eng won't ship a cheaper model that fails the 290-ticket eval.

---

## Testbed setup (today vs demo)

**Today:** both workflows use deprecated `gpt-3.5-turbo`, so `driftless plan`
shows **deprecation** rows first (see [post 3](./03-dependabot-for-prompts-in-ci.md)).
Cost discovery requires an **active, non-at-risk** baseline.

**Demo hack for a blog post:**

1. Temporarily set `model.current: gpt-4o` in `driftless.yml` + `config/llm.yml`
2. Keep `cost.enabled: true` and `min_savings_pct: 0.20` in `.driftless/policy.yml`
3. Run `driftless plan` — expect a **cost** row proposing `gpt-4o-mini`

The testbed already wires per-record cost:

```yaml
eval:
  cost_field: cost_usd
  prompt_tokens_field: prompt_tokens
  completion_tokens_field: completion_tokens
```

`evals/run_eval.py` emits these fields (simulated offline, real usage with API keys).

Publication bar:

| Needed artifact | Why |
|-----------------|-----|
| `plan` output with `Trigger = cost` | Proves this is not a deprecation story |
| `compare` output with measured `Total cost` | Makes savings concrete |
| Quality threshold result | Shows "cheaper" did not override the eval bar |
| PR or issue screenshot | Connects policy to reviewer workflow |

---

## Outline

### 1. Opportunistic vs forced
- Deprecation = deadline-driven (testbed: `gpt-3.5-turbo` retired 277d ago in `plan` output)
- Cost = catalog pricing + policy thresholds

### 2. Policy block (copy from testbed)
```yaml
cost:
  enabled: true
  min_savings_pct: 0.20
  max_quality_drop: 0.01
  action: pr
```

### 3. What `plan` shows
- Catalog-estimated savings for triage
- Measured `total_cost` from `compare` when eval emits token/cost fields
- Same `migrate` + holdout path as [post 1](./01-model-swap-is-not-a-migration.md)

### 4. Scorecard columns to cite
From real `compare` output: `Total cost` row (baseline 0.033 vs target 0.011 sim USD on 290 tickets — illustrative scale, not production spend).

### 5. CTA
- Migrate workflow when cost row passes policy + eval
- Don't conflate with deprecation ISSUE when naive swap fails
- Show the exact savings policy so finance and engineering are arguing about
  numbers, not vibes

---

## Screenshots
- `plan` with a `cost` trigger row (after demo setup above)
- Compare scorecard with cost column
