# Free-form answers graded by an LLM judge

## The use case

Not every LLM workflow is a classifier with gold categories. You might summarize
support tickets, rewrite answers for tone, or grade free-form responses for
faithfulness. There is no single `label_field` to compute F1 against. So the team
adds an **LLM-as-judge**: a second model scores each output against a written
rubric, and you treat the mean score like a quality metric for migrations.

That solves the "how do we score this?" problem and creates a new one. If you
`migrate` or `refine` against the judge, you are optimizing prompts toward
whatever that second model prefers. If the judge is noisy, biased, or drifts when
you change the grading model, you can ship a "successful" migration that humans
would reject — with beautiful charts and a green holdout on a bad proxy.

The use case is the decision *before* the repair loop: **when is a judge trusted
enough to optimize against?** You need a human calibration set, a quantitative
agreement check, and a hard stop when agreement fails — not vibes that "the
rubric looks good."

**What driftless does here:** treat the judge as a grading mode with an optional
**human calibration gate**. Measure judge↔human agreement (`judge-check`) and
refuse to optimize when MAE / correlation miss your bar.

The support-classifier testbed is **label-F1 first**. This post uses that as
contrast, then shows the judge contract shape, CLI, and CI scaffold from the
product itself.

---

## Three grading modes (pick one)

| Mode | Contract | Testbed example | Gate |
|------|----------|-----------------|------|
| Classification | `eval.label_field` | `support_classifier` → macro-F1 | `min_f1` |
| Customer score / pass | `score_field` / `pass_field` | `quick_triage` → escalate yes/no | `min_score` |
| LLM-as-judge | `eval.judge` | *(your summarization / RAG write-up)* | `min_score` + optional MAE/corr |

`quick_triage` is closer to a rubric *in spirit* (binary escalate) but still
uses **gold labels**, not a second model. Jump to judge only when humans cannot
pre-label every row cheaply — and then calibrate.

Posts [1](./01-model-swap-is-not-a-migration.md)–[2](./02-when-labels-move-refine-not-remodel.md)
stay on the F1 path. This post is for everyone else.

---

## Why judge trust is a first-class problem

Putting a model inside the trust loop means:

- The judge can be noisy, biased, or **itself** drift when you change the grading model.
- Optimizing prompts against a bad judge produces confident, wrong migrations.
- Holdout on judge scores is not enough if the judge disagrees with humans.

Driftless keeps the judge injectable (deterministic stubs in tests), normalizes
scores to 0..1, and exposes `judge_agreement()` against a human-scored JSONL.

---

## Contract shape

```yaml
workflows:
  support_summary:
    run:
      command: python evals/run_summary.py
      input_path: evals/tickets.inputs.jsonl
      output_path: evals/summary.outputs.jsonl
    model:
      current: gpt-4o-mini
      env_var: SUMMARY_MODEL
    files:
      editable: [prompts/summary.md]
    eval:
      judge:
        rubric: |
          Award full marks if the summary is faithful to the ticket,
          names the category of ask, and stays under 3 sentences.
          Deduct for hallucinations or leaked internal IDs.
        scale_max: 5              # rubric 0..5 → normalized to 0..1
        # pass_threshold: 0.6     # optional per-row pass
        # input_field: text
        # output_field: summary   # if output is JSON; else raw text
        calibration_path: evals/judge_calibration.jsonl
        max_mae: 0.15             # gate: refuse migrate/compare if exceeded
        min_correlation: 0.80     # Pearson r vs human scores
    thresholds:
      min_score: 0.85
    migration:
      holdout_required: true
```

Calibration JSONL — one human-scored example per line:

```jsonl
{"input": "Please reverse the payment on my latest invoice.", "output": "Customer wants a charge reversed on the latest invoice.", "score": 5}
{"input": "App crashes on login.", "output": "The weather in Paris is lovely.", "score": 0}
```

`score` is on the rubric's `scale_max` (here 0..5). Driftless normalizes both
human and judge scores to 0..1 before MAE / correlation.

Scaffold comments for this block also live in `driftless init` templates.

---

## Measure before you optimize

```bash
driftless judge-check -w support_summary
# prints records, MAE, correlation, and gate status (ok/FAIL) when configured

driftless judge-check -w support_summary --enforce
# same gates migrate/compare/refine apply — exit non-zero on failure
```

Example shape of a passing check:

```
support_summary — judge calibration check

  records: 40
  MAE: 0.112
  correlation: 0.86
  gates: max_mae=0.15 (ok), min_correlation=0.8 (ok)

gates passed — judge vs. human on 40 records: MAE=0.112, corr=0.86
```

If MAE is 0.22 against `max_mae: 0.15`, **stop**. Fix the rubric, calibration
set, or judge model — do not run `migrate`.

With gates set on the contract, `compare` / `migrate` / `refine` call
`require_judge_agreement()` automatically. You do not need `--enforce` for
those commands; `judge-check --enforce` is the preflight you run in CI and
locally.

---

## CI: path-filtered judge-check

```bash
driftless init-ci --judge-check
```

Emits a workflow that re-runs when the rubric or calibration file changes, using
the composite Action:

```yaml
- uses: driftless-dev/driftless@v0.3.0
  with:
    command: judge-check
    workflow: support_summary
    args: "--enforce"
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

Same Dependabot-shaped idea as [post 3](./03-dependabot-for-prompts-in-ci.md):
the file that defines "good" is what triggers the check.

---

## Evidence in the migration PR

When a judge-graded migrate succeeds, the report and `driftless view` include:

- Mean judge score (baseline vs target / repaired)
- Holdout check on `min_score`
- **Judge agreement** summary when calibration ran
- Per-record **rationales** in the attempt log (why the judge dinged a row)

That is the same evidence path as classification migrations — different oracle.

---

## Honest limits

| Risk | Mitigation |
|------|------------|
| Judge drifts when *grading* model changes | Re-run `judge-check --enforce`; bump calibration |
| Thin calibration set | Agreement undefined / weak — add rows before gating |
| Optimizing to game the judge | Keep humans in the loop; refresh calibration from production spot-checks |
| Confusing judge trust with label trust | Classification → [post 5](./05-audit-labels-before-you-trust-f1.md); free-form → this post |

Judge trust ≠ "the numbers look smooth." It means **documented agreement with
humans** before the repair loop spends tokens.

---

## How this relates to the testbed

| Workflow | Grading | Preflight |
|----------|---------|-----------|
| `support_classifier` | F1 on categories | `audit-labels` |
| `quick_triage` | `pass_field: escalate` | gold labels (no judge) |
| Your free-form workflow | `eval.judge` | `judge-check --enforce` |

A future testbed addition could ship a tiny summarization workflow + calibration
file for a one-command demo. Until then, start from `driftless init` comments or
a RAG/agent fixture that already uses `score_field` /
[`docs/rag-and-agents.md`](../rag-and-agents.md) and graduate to `eval.judge`
when you need rubrics.

---

## Next steps

- Classification teams: stay on [posts 1–2](./01-model-swap-is-not-a-migration.md); add [label audit](./05-audit-labels-before-you-trust-f1.md)
- Free-form teams: add `eval.judge` + calibration → `judge-check --enforce` → then `migrate`
- CI: `driftless init-ci --judge-check` next to your migrate workflow ([post 3](./03-dependabot-for-prompts-in-ci.md))
