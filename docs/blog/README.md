# Driftless blog series

Use-case posts grounded in the
**[support-classifier-svc](https://github.com/driftless-dev/support-classifier-svc)**
testbed — a fictional B2B ticket classifier (290 labeled tickets, strict JSON,
LiteLLM, simulator + real API paths). Every post includes **repro commands** you
can run locally.

**Audience:** engineers with an offline eval (JSONL + harness command + prompts in
git) who hit model deprecation or eval drift.

---

## Series arc

| # | Post | Testbed anchor |
|---|------|----------------|
| 1 | [Model swap ≠ migration](./01-model-swap-is-not-a-migration.md) | `compare` shows F1 0.903 → 0.000, 100% schema errors on naive `gpt-4o-mini` swap; 2×2 real-API table |
| 2 | [Labels move → refine](./02-when-labels-move-refine-not-remodel.md) | `_apply_refund_policy.py` (25 tickets), `t002`/`t021`, refine-on-label-change Action |
| 3 | [CI / Dependabot shape](./03-dependabot-for-prompts-in-ci.md) | `plan` table for both workflows; six workflow YAML files mapped |
| 4 | [Cost trigger](./04-cheaper-model-same-quality-bar.md) | *outline* — `cost_field`, `policy.yml`, needs active baseline + real savings table |
| 5 | [Label audit](./05-audit-labels-before-you-trust-f1.md) | *outline, expand next* — `audit-labels.yml` on eval PRs + intentional conflict branch |
| 6 | [LLM judge trust](./06-trust-your-llm-judge.md) | *outline* — needs judge calibration demo, likely outside classifier testbed |
| 7 | [RAG prompts drift too](./07-rag-prompts-drift-too.md) | `examples/rag-qa`: fixed JSONL knowledge base, `score_field`, cost row, prompt/config-only edit scope |
| 8 | [Agent tool selection drifts too](./08-agent-tool-selection-drift.md) | `examples/tool-agent`: fake tools, trace fields, `score_field`, planner/tool-description edit scope |

Posts **1–3** and **7–8** are publishable drafts with captured CLI output,
pending screenshots and release pinning. Posts **4–6** should stay unpublished
until they have real artifacts, not just product-shaped outlines.

Suggested expansion order:

1. **Post 5** — easiest next proof point; create an intentional label conflict,
   capture `audit-labels --fail`, and show the failed CI check.
2. **Post 4** — needs an active baseline model so cost rows are not hidden by
   deprecation rows.
3. **Post 7** — add screenshots from the in-repo RAG QA fixture and, later, a
   calibrated judge variant.
4. **Post 8** — add screenshots from the in-repo tool-agent fixture and, later,
   budget guidance for longer trajectories.
5. **Post 6** — needs a true judge workflow with calibration rows; do not force
   it through the classifier example.

---

## Quick reproduce (all three pillars)

```bash
git clone https://github.com/driftless-dev/support-classifier-svc
cd support-classifier-svc
pip install -r requirements.txt driftless
export SUPPORT_CLASSIFIER_SIMULATE=1

# Post 1 — model migration
cp evals/fixtures/prompt-baseline-scenario3.md prompts/system.md
driftless compare -w support_classifier --to gpt-4o-mini

# Post 2 — dataset refine (after applying label policy)
python evals/_apply_refund_policy.py
driftless refine -w support_classifier --strict-label-audit

# Post 3 — policy triage
driftless plan
```

RAG/agent workflows: start from the contract shape in
[`docs/rag-and-agents.md`](../rag-and-agents.md). The first publishable version
should keep the retrieval index fixed and show prompt/config migration only.

Real API migrations: set `OPENAI_API_KEY`, unset `SUPPORT_CLASSIFIER_SIMULATE`,
use Actions → **Migrate model**.

---

## Publishing checklist

- [ ] Screenshot: `compare` scorecard or `plan` table
- [ ] Screenshot: migration PR body from testbed Actions run
- [ ] Pin `driftless==X.Y.Z` / `@vX.Y.Z` to current release
- [ ] Note token cost for live `migrate`/`refine` on 290 tickets
