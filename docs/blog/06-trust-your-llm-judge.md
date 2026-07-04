# When LLM-as-judge is safe enough to optimize against

**Status:** outline only — testbed is classification-first. Use a second repo or
add a real judge-calibration workflow before publishing.

**Use case:** Summarization / rubric grading where F1 doesn't apply. You add
`eval.judge` and need to know if optimizing toward the judge overfits a flaky proxy.

---

## Testbed angle

`support_classifier` uses **macro-F1** on four categories — the happy path for
structured classification.

`quick_triage` uses **`pass_field: escalate`** (pass/fail) — closer to a binary
rubric but still gold-label based, not LLM-judge based.

For a judge post, either:

- Add a small `eval.judge` block + calibration JSONL to the testbed (future work), or
- Point readers at `driftless init-ci --judge-check` scaffold and a summarization
  workflow from their own repo.

Publication bar:

| Needed artifact | Why |
|-----------------|-----|
| Rubric with human calibration rows | Defines what "judge trust" means |
| `judge-check` output with MAE/correlation | Gives readers a quantitative gate |
| One failed calibration example | Shows when optimization should stop |
| Migration/refine PR using judge scores | Connects judge trust to the repair loop |

---

## Outline

### 1. Grading modes (from product README)
- `label_field` / F1 — testbed `support_classifier`
- `pass_field` — testbed `quick_triage`
- `eval.judge` — rubric + calibration set

### 2. Gate before migrate/refine
```bash
driftless judge-check -w my_workflow
driftless judge-check -w my_workflow --enforce
```

Contract knobs: `max_mae`, `min_correlation` on judge vs human calibration rows.

### 3. Evidence in PR
Migration report + `driftless view` attempt log with per-record judge rationales
(same run viewer used for classification migrations).

### 4. Honest limits
- Re-calibrate when the *grading* model changes
- Judge trust ≠ label audit ([post 5](./05-audit-labels-before-you-trust-f1.md))
- Do not optimize against a judge until calibration passes

### 5. CTA
- Classification readers: stay on F1 path (posts 1–2)
- Subjective tasks: judge-check before first `migrate`

---

## Screenshots
- `judge-check` output with MAE / correlation
- Run viewer panel showing judge rationale on a failed row
