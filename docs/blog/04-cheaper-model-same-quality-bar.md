# Finance wants cheaper inference on the same quality bar

## The use case

Your classifier (or similar LLM workflow) runs on a frontier model — say
`gpt-4o` — because that is what cleared quality when you launched. Volume grew.
Finance now wants **20%+ inference savings**. A cheaper model like `gpt-4o-mini`
is on the table. Engineering's constraint is simple and non-negotiable: the same
offline eval that guards production (e.g. 290 labeled tickets, `min_f1: 0.90`)
must still pass before anyone merges a model change.

The naive path is the same mistake as a deprecation swap: edit the model string,
ship, hope. Sometimes the cheaper model is fine with today's prompt. Often it is
not — formatting drifts, a category rule softens, and you "saved money" by
shipping a silent quality regression. Finance and eng then argue from different
dashboards: one cites unit price, the other cites ticket mishandling.

You need a workflow where **cost is a proposal trigger**, not a merge button:
surface candidates that look ≥20% cheaper on paper (or on measured tokens), then
run the *same* compare → repair → holdout path you use for deprecations. Only
open a PR when quality still clears your bar.

**What driftless does here:** treat cost as an *opportunistic* policy trigger.
When catalog pricing (and optionally measured token cost) clears
`min_savings_pct`, `plan` proposes a cheaper candidate; `compare` / `migrate`
still gate on *your* quality thresholds.

This post uses
[support-classifier-svc](https://github.com/driftless-dev/support-classifier-svc)
for cost wiring and policy, plus catalog math you can reproduce locally.

---

## Forced vs opportunistic (don't confuse them)

| Trigger | When it fires | Testbed today |
|---------|---------------|---------------|
| **Deprecation** (forced) | Current model is deprecated/retired | Both workflows on `gpt-3.5-turbo` → `plan` always shows ISSUE rows |
| **Cost** (opportunistic) | Baseline is *active*, candidate ≥ capability tier, savings ≥ `min_savings_pct` | Ready in policy, but **hidden** while baseline is at-risk |

From [post 3](./03-dependabot-for-prompts-in-ci.md): as long as `gpt-3.5-turbo` is
current, deprecation wins. Cost discovery skips at-risk baselines on purpose —
you shouldn't "save money" by ignoring a retirement deadline.

---

## Wire cost into the contract (testbed already does)

`support_classifier` emits per-record spend so `compare` and `plan` can reason
about real totals — not vibes:

```yaml
# driftless.yml → workflows.support_classifier.eval
cost_field: cost_usd
prompt_tokens_field: prompt_tokens
completion_tokens_field: completion_tokens
```

`evals/run_eval.py` fills these (simulator estimates offline; LiteLLM usage with
a provider key). Prefer `cost_field` when you have it; otherwise driftless
derives USD from token fields × the bundled catalog.

Policy (`.driftless/policy.yml` in the testbed):

```yaml
cost:
  enabled: true
  min_savings_pct: 0.20    # require ≥ 20% cheaper
  max_quality_drop: 0.01   # after compare: F1 may not fall more than 1pt
  action: pr
```

`min_savings_pct` is the *proposal* bar. Your contract `thresholds:` (e.g.
`min_f1: 0.90`) remain the *ship* bar.

---

## Catalog math you can check yourself

```bash
python - <<'PY'
from driftless.discovery import estimate_cost_change_pct
print("gpt-4o → gpt-4o-mini:", estimate_cost_change_pct("gpt-4o", "gpt-4o-mini"))
print("claude-3-opus → claude-3-5-sonnet:",
      estimate_cost_change_pct("claude-3-opus-20240229", "claude-3-5-sonnet"))
PY
```

Typical catalog result (blended input+output $/1M tokens):

| Move | Est. cost change |
|------|------------------|
| `gpt-4o` → `gpt-4o-mini` | **−94%** |
| `claude-3-opus-20240229` → `claude-3-5-sonnet` | **−80%** |

Both clear `min_savings_pct: 0.20`. Discovery still refuses candidates with a
*lower* capability tier than the baseline — it won't auto-propose a silent
quality downgrade for pennies.

On the testbed simulator, a naive `gpt-3.5-turbo` → `gpt-4o-mini` `compare`
already prints a **Total cost** row (~`0.033` → `0.011` on 290 tickets). Treat
those USD as **relative scale**, not production spend — but the column is what
finance and eng should argue about.

---

## Demo: force a cost row on the testbed

With the committed `gpt-3.5-turbo` baseline you will only see deprecation.
To exercise cost discovery:

1. Temporarily set `model.current: gpt-4o` in `driftless.yml` **and**
   `config/llm.yml` for `support_classifier`.
2. Keep `cost.enabled: true` / `min_savings_pct: 0.20`.
3. Run:

```bash
export SUPPORT_CLASSIFIER_SIMULATE=1
driftless plan
```

Expect a **cost** trigger proposing something like `gpt-4o-mini` (same
provider, active, cheaper, not a capability downgrade). Then:

```bash
driftless compare -w support_classifier --to gpt-4o-mini
# if naive swap fails thresholds → migrate, same as post 1
driftless migrate -w support_classifier --to gpt-4o-mini --generator llm
```

Revert the temporary `gpt-4o` baseline when you're done — the testbed's
deprecation demo depends on `gpt-3.5-turbo`.

---

## Same repair loop as migration

Cost does **not** get a special optimizer. Once `plan` (or you) picks a
candidate:

1. `compare` — quality + measured cost side by side
2. `migrate` — repair editable prompts if the naive swap fails
3. Holdout gate — still `min_f1: 0.90` / `max_schema_error_rate: 0.02`
4. `open-pr` — PR only if shippable; else ISSUE with evidence

Policy `max_quality_drop` decides whether a *passing-but-slightly-worse* swap
is worth a PR. Your absolute thresholds still win if the candidate is blocked.

See [post 1](./01-model-swap-is-not-a-migration.md) for the scorecard / holdout
story; only the *trigger* differs.

---

## CI pattern

Weekly `plan` (simulator) already runs in
[plan-preview.yml](https://github.com/driftless-dev/support-classifier-svc/blob/main/.github/workflows/plan-preview.yml).
After you migrate off deprecated models, the same job starts surfacing **cost**
rows without a new workflow.

Manual cost chase: Actions → **Migrate model** with `target_model=gpt-4o-mini`
once the baseline is an active frontier model you want to downsize from.

---

## What *not* to do

- Don't enable `cost` and disable deprecation — retirement still comes first.
- Don't report savings from a swap that failed `min_f1`.
- Don't confuse catalog *estimates* (triage) with measured `total_cost` after
  `compare` (decision evidence). Prefer measured when the harness emits tokens.

---

## Next steps

- [Post 1](./01-model-swap-is-not-a-migration.md) — repair loop details
- [Post 3](./03-dependabot-for-prompts-in-ci.md) — schedule `plan` in Actions
- [Post 5](./05-audit-labels-before-you-trust-f1.md) — audit before spending tokens on a cost migrate
