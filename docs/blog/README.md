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

| # | Post | Anchor |
|---|------|--------|
| 1 | [Your ticket classifier’s model got deprecated](./01-model-swap-is-not-a-migration.md) | `compare` F1 0.903 → 0.000, 100% schema errors; 2×2 real-API table |
| 2 | [Support changed the labeling policy](./02-when-labels-move-refine-not-remodel.md) | `_apply_refund_policy.py` (25 tickets), refine-on-label-change Action |
| 3 | [Prompt repair that doesn’t wait on memory](./03-dependabot-for-prompts-in-ci.md) | `plan` table for both workflows; six workflow YAML files |
| 4 | [Finance wants cheaper inference, same bar](./04-cheaper-model-same-quality-bar.md) | `cost_field` + policy; catalog −94% `gpt-4o`→`gpt-4o-mini`; demo needs active baseline |
| 5 | [Offline F1 is lying — labels conflict](./05-audit-labels-before-you-trust-f1.md) | Clean 290-row audit + exact-duplicate conflict CLI capture; `audit-labels.yml` |
| 6 | [Free-form answers graded by an LLM judge](./06-trust-your-llm-judge.md) | `eval.judge` + calibration gates; `judge-check --enforce`; contrast with testbed F1 |
| 7 | [RAG QA: new answer model, same knowledge base](./07-rag-prompts-drift-too.md) | `examples/rag-qa`: fixed KB, `score_field`, prompt/config-only edits |
| 8 | [Tool-calling agent: new planner, same tools](./08-agent-tool-selection-drift.md) | `examples/tool-agent`: fake tools, `score_field`, planner edit scope |

Posts **1–6** are full drafts. **7–8** cover RAG/agent fixtures (see also
[`docs/rag-and-agents.md`](../rag-and-agents.md)).

Before publishing any post: pin `@vX.Y.Z`, add one screenshot, note token cost
for live runs.

---

## Quick reproduce

```bash
git clone https://github.com/driftless-dev/support-classifier-svc
cd support-classifier-svc
pip install -r requirements.txt driftless
export SUPPORT_CLASSIFIER_SIMULATE=1

# Post 1 — model migration
cp evals/fixtures/prompt-baseline-scenario3.md prompts/system.md
driftless compare -w support_classifier --to gpt-4o-mini

# Post 2 — dataset refine
python evals/_apply_refund_policy.py
driftless refine -w support_classifier --strict-label-audit

# Post 3 — policy triage
driftless plan

# Post 5 — label audit (clean set)
driftless audit-labels -w support_classifier
```

**Post 4:** temporarily set `model.current: gpt-4o`, then `driftless plan` for a
cost row (see post for details).

**Post 6:** add `eval.judge` + calibration JSONL to a free-form workflow, then
`driftless judge-check -w <workflow> --enforce`.

---

## Publishing checklist

- [ ] Screenshot: `compare` / `plan` / `audit-labels` / `judge-check` as relevant
- [ ] Screenshot: migration PR body from testbed Actions (posts 1–3)
- [ ] Pin `driftless==X.Y.Z` / `@vX.Y.Z` to current release
- [ ] Note token cost for live `migrate`/`refine` on 290 tickets
