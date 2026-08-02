# Free-form answers graded by an LLM judge

**Status: advanced configuration guide.** Driftless does not currently ship a
judge fixture or a key-free judge-model stub. This post explains how to add judge
grading to your own workflow. It does not promise a one-command judge demo.

## The problem: useful answers do not always have labels

Suppose your application summarizes a support ticket:

- input: "Please reverse the payment on my latest invoice."
- output: "Customer wants a charge reversed on the latest invoice."

This is **free-form output**: text with many acceptable wordings, rather than one
answer from a fixed list. Classification metrics such as F1 cannot tell you
whether the summary is faithful, concise, and safe.

One option is **LLM-as-judge**: a second language model grades the application's
answer. It follows a **rubric**, which is a written description of what earns or
loses points. The judge can score thousands of answers more cheaply than a human
reviewer.

The judge is still a model. It can be inconsistent, biased, or wrong. A repair
loop can learn to please a bad judge while making answers worse for users.

The question is therefore not only "What score did the app receive?" It is
"Does this judge agree with people well enough to guide a migration?"

## Mental model: two quality gates

The first gate checks the judge against people. A **calibration set** is a small,
representative collection of inputs and outputs that people have already
scored. Driftless asks the judge to score the same rows and compares the two.

The comparison uses two measurements:

- **Mean absolute error (MAE)** is the judge's average distance from the human
  score. Lower is better. An MAE of `0.15` on Driftless's normalized `0..1`
  scale means the judge is off by 0.15 on average.
- **Correlation** measures whether judge scores rise and fall with human scores.
  Pearson correlation is `1` for perfect agreement in ordering, `0` for no
  linear relationship, and negative when the judge tends to move opposite to
  people.

Intuitively, MAE asks "How far off is the judge?" Correlation asks "Does it rank
better and worse answers in the same direction as people?"

In plain-text notation, for `n` examples:

`MAE = (|judge_1 - human_1| + ... + |judge_n - human_n|) / n`

The vertical bars mean "take the positive distance," so errors above and below
the human score do not cancel each other out.

The second gate checks the application on a **holdout**: evaluation rows kept
away from prompt repair until the final validation. A green holdout is useful
only after the judge itself has passed calibration.

Driftless normalizes judge and human scores to `0..1`, measures agreement with
`judge-check`, and blocks optimization when configured MAE or correlation limits
fail.

## Before you start

You need:

- a free-form evaluation harness that reads the configured input JSONL and
  writes one output per row;
- a rubric with concrete good, bad, and borderline behavior;
- a human-scored calibration JSONL;
- credentials for the configured judge provider;
- a Driftless contract that names the files repair may edit.

A **repair generator** is the component that proposes prompt or configuration
changes from failed examples. Driftless's LLM repair generator requires provider
credentials and makes nondeterministic model calls.

There is no bundled judge fixture. The bundled four-row `support-classifier`
example is key-free, but it grades category labels with F1. The separate
290-row external support-classifier testbed is also label-F1 first. Neither
demonstrates judge reliability.

If you want to learn the basic contract shape before this guide, the classifier
smoke check will copy and validate that different kind of fixture:

```bash
pip install driftless
driftless copy-example support-classifier --out-dir driftless-classifier-demo
cd driftless-classifier-demo
driftless validate -w support_classifier
```

Expect a key-free classifier validation, not judge scores or a calibration
result. Do not use it as evidence that an LLM judge is trustworthy.

## Walkthrough

### 1. Define the human grading standard

Write a rubric before configuring Driftless. For a support summary, it might
award full marks only when the answer is faithful, names the request category,
stays under three sentences, and does not expose internal IDs.

Then create one human-scored JSON object per line:

```jsonl
{"input": "Please reverse the payment on my latest invoice.", "output": "Customer wants a charge reversed on the latest invoice.", "score": 5}
{"input": "App crashes on login.", "output": "The weather in Paris is lovely.", "score": 0}
```

These two rows illustrate the file format, not a sufficient calibration set.
Include representative good, bad, format-breaking, unsupported, and borderline
answers. Every `score` must use the rubric's scale, `0..5` in this example.

### 2. Add the workflow contract

This configuration connects your existing harness to an OpenAI judge. Replace
the example paths, fields, model, and credential provider with your application's
real values.

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
        provider: openai
        model: gpt-4o-mini
        rubric: |
          Award full marks if the summary is faithful to the ticket,
          names the category of ask, and stays under 3 sentences.
          Deduct for hallucinations or leaked internal IDs.
        scale_max: 5              # rubric 0..5 → normalized to 0..1
        # pass_threshold: 0.6     # optional per-row pass
        # input_field: text
        # output_field: summary   # if output is JSON; else raw text
        calibration_path: evals/judge_calibration.jsonl
        max_mae: 0.15
        min_correlation: 0.80
    thresholds:
      min_score: 0.85
    migration:
      holdout_required: true
```

`min_score: 0.85` means the normalized mean judge score must be at least 0.85.
`max_mae: 0.15` allows an average judge-to-human difference of at most 0.15.
`min_correlation: 0.80` requires strong positive score movement with humans.

For comparison, `score_field` is a contract setting for workflows whose own
evaluator already emits a numeric score. `eval.judge` is for workflows that ask
a second model to produce that score. `quick_triage` in the external testbed
uses gold values through `pass_field`; it is not an LLM judge.

Scaffold comments for judge configuration also live in `driftless init`
templates.

### 3. Check wiring before spending judge calls

If the repository has no contract, this command creates a template. Skip it when
`driftless.yml` already exists, then add your real workflow:

```bash
driftless init --path driftless.yml
```

Next, check paths and contract structure without running the application:

```bash
driftless validate -w support_summary --no-run
```

Expect either a configuration error you can fix without model calls or a
successful wiring check. Full validation then runs your harness and may require
the application's provider credential:

```bash
driftless validate -w support_summary
```

Expect one normal application evaluation. This is not yet the human-agreement
check.

### 4. Measure and enforce judge agreement

The example contract explicitly selects OpenAI, so provide its credential. Use
the corresponding credential when you configure another supported provider.

```bash
export OPENAI_API_KEY=...
driftless judge-check -w support_summary
```

`judge-check` calls the configured judge once per calibration row. It reports
the row count, normalized MAE, and Pearson correlation.

After inspecting the measurements, enforce the limits from the contract:

```bash
driftless judge-check -w support_summary --enforce
```

Expect exit code zero only when MAE is no greater than `0.15` and correlation is
at least `0.80`. Correlation is undefined when there are fewer than two rows or
no score variance; an enforced correlation gate then fails.

### 5. Add the check to CI

This command emits a path-filtered CI workflow for judge calibration:

```bash
driftless init-ci --judge-check
```

Expect generated CI configuration that reruns when the rubric or calibration
file changes. Its important step has this shape:

```yaml
- uses: driftless-dev/driftless@v0.3.2
  with:
    command: judge-check
    workflow: support_summary
    args: "--enforce"
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

The CI secret pays for one judge call per calibration row. This follows the
same file-triggered approach as [post 3](./03-dependabot-for-prompts-in-ci.md).

### 6. Optimize only after calibration passes

With agreement gates in the contract, `compare`, `migrate`, and `refine` call
the agreement requirement automatically. You do not need an extra `--enforce`
flag on those commands.

Judge grading and repair can multiply calls across calibration rows, evaluation
rows, repair candidates, and iterations. A rough mental model is:

\[
\text{work} \approx
\text{rows} \times \text{evaluation runs}
+ \text{calibration rows} \times \text{agreement checks}
\]

Retrieval, tool calls, retries, and multiple repair candidates add more work.
Start with a representative set and a small repair budget.

## Interpret the result

A passing `judge-check --enforce` means this judge met the contract's agreement
limits on this calibration set. It does not prove the rubric is complete or that
the judge will generalize to every production answer.

A successful judge-graded migration report and `driftless view` can include:

- baseline, target, and repaired mean judge scores;
- the holdout check against `min_score`;
- the judge-agreement summary;
- low-scoring records and the judge's rationale for each.

Those rationales are evidence to inspect, not ground truth.

## Safety and failure behavior

When MAE is too high, correlation is too low or undefined, or the calibration
set is empty, the agreement gate fails. CI should stay red. Fix the rubric,
calibration examples, or judge model before asking the repair generator to
optimize. This failure says the judge is not trusted by the contract; it does
not say the application model failed.

A judge call exception or a response without a numeric score receives a
normalized score of `0.0` with a rationale describing the failure. Raw judge
scores are clamped to the `0..1` normalized range.

Other important limits:

- Changing the grading model can change the judge. Rerun
  `judge-check --enforce`.
- A thin calibration set produces weak evidence. Add representative rows.
- Repeated optimization can teach prompts to game the rubric. Keep human
  spot-checks and refresh calibration examples from production.
- Judge trust is different from label trust. For classification, use the
  [label audit](./05-audit-labels-before-you-trust-f1.md).

## Next steps

- Add `eval.judge`, human calibration, and `judge-check --enforce` to your own
  free-form workflow.
- For label classification, keep the F1 workflow from
  [posts 1](./01-model-swap-is-not-a-migration.md) and
  [2](./02-when-labels-move-refine-not-remodel.md), then add the
  [label audit](./05-audit-labels-before-you-trust-f1.md).
- Read the [RAG example](./07-rag-prompts-drift-too.md) for a bundled key-free
  workflow that uses `score_field`, not a judge, and the broader
  [RAG and agent contract guide](../rag-and-agents.md).
- Add CI only after local validation, following
  [post 3](./03-dependabot-for-prompts-in-ci.md).
- Review [cost and budget guidance](../COST_AND_BUDGETS.md) before scaling.
