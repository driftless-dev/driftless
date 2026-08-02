# RAG QA: new answer model, same knowledge base

**Specialized fixture · 4 rows · key-free:** this guide uses the deterministic
`rag-qa` example installed by `copy-example`. It is not the bundled classifier
or the separate 290-row external testbed.

## The problem: the answer model changes behavior

**Retrieval-augmented generation (RAG)** is an application pattern in which the
app finds relevant source material and gives it to a language model before the
model answers. **Retrieval** is that search step. The **corpus** is the collection
of source documents, and the **index** is the searchable representation used to
find documents or chunks.

Imagine a support question about single sign-on. The app retrieves the matching
support article, and the answer model should use only that article and cite it.
You replace the answer model because the old one is expensive or being retired.
The new model still produces fluent text, but it drops the citation or invents a
policy that was not in the article.

That does not automatically mean the corpus or index is broken. The new model
may interpret the answer and retrieval-rewrite prompts differently.

This walkthrough changes the answer model while keeping the knowledge base and
index fixed. Driftless runs the entire application, measures the final answers
and citations, and may edit only the prompt files allowed by the contract.

If you remember one rule, use this one: **a RAG model migration is not an
embedding or index migration.** Treat index rebuilding as a separate data
pipeline change.

## Mental model: test the pipeline end to end

The application owns retrieval, answer generation, and scoring. For each
question, the fixture writes a result like this:

```jsonl
{"id":"q001","answer":"...","citations":["doc-sso"],"score":1.0,"cost":0.018,"retrieved_doc":"doc-sso"}
```

`score` is the application's quality measurement for that row. In the fixture,
the evaluator gives 75% of the score for required answer terms and 25% for the
required citation. It is deterministic, so no provider key is needed. A real
application might combine correctness, citation support, faithfulness, and
context relevance.

The contract setting **`score_field`** tells Driftless which output property
contains that numeric score. Driftless averages row scores into
**Score / pass-rate** and compares the mean with `min_score`. In this bundled
regression the baseline rows score `1.0` and the uncorrected target rows score
`0.0`; the scoring function itself can also produce values between them.

A **holdout** is a subset of evaluation rows that repair does not use while
choosing prompt changes. Driftless checks the winning candidate on that unseen
subset before treating the migration as safe. This four-row fixture uses a
60% tuning and 40% holdout split, but it is a demonstration, not launch-quality
evidence.

## Before you start

You need Python and a shell. The published fixture is dependency-light and does
not need model-provider credentials.

The copied project contains:

- `driftless.yml`: workflow contract;
- `python3 -m app.eval_rag`: evaluation command;
- `data/docs.jsonl`: fixed support corpus;
- `data/index_manifest.json`: fixed index metadata;
- `evals/questions.jsonl` and `evals/gold.jsonl`: questions and expected terms
  and citations;
- `prompts/rag_answer.md` and `prompts/retrieval_rewrite.md`: editable prompts.

A **repair generator** proposes prompt or configuration edits from failed rows.
The normal LLM repair generator requires provider credentials and makes
nondeterministic calls. The key-free path below deliberately disables it.

## Walkthrough

### 1. Install Driftless and copy the fixture

These commands install the published package, create a standalone demo
directory, and enter it:

```bash
pip install driftless
driftless copy-example rag-qa --out-dir driftless-rag-demo
cd driftless-rag-demo
```

Expect a local copy of the four-row RAG project. It is separate from any changes
in this repository.

### 2. Validate the current workflow

Run the fixture with its configured current model behavior:

```bash
driftless validate -w rag_qa
```

Expect Driftless to run `python3 -m app.eval_rag`, read the output JSONL, and
validate its metrics and schema. The model names select deterministic fixture
behavior; no network model call occurs.

### 3. Compare the current and candidate models

This command runs the same questions and fixed retrieval data for `gpt-4` and
the simulated `gpt-4o-mini` target:

```bash
driftless compare -w rag_qa --to gpt-4o-mini
```

Expect this actual fixture output:

```text
Running gpt-4 (baseline) and gpt-4o-mini (target)...

┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┓
┃ Metric            ┃ Current ┃ Target (orig files) ┃
┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━┩
│ F1                │     n/a │                 n/a │
│ Precision         │     n/a │                 n/a │
│ Recall            │     n/a │                 n/a │
│ Accuracy          │     n/a │                 n/a │
│ Score / pass-rate │   1.000 │               0.000 │
│ Schema error rate │    0.0% │                0.0% │
│ Refusal rate      │    0.0% │                0.0% │
│ Total cost        │   0.072 │               0.016 │
└───────────────────┴─────────┴─────────────────────┘

Thresholds (target vs contract):
  FAIL min_score: 0.000 >= 0.86
  PASS max_cost_increase: -77.8% <= +20%
```

Current CLI versions may also print confidence caveats and average latency rows
for this four-row smoke fixture. Those extra lines are expected; they do not
change the score and cost results shown above.

The target is 77.8% cheaper in the fixture, but its mean score is `0.000`.
`min_score: 0.86` requires at least `0.860`. Lower cost does not compensate for
a failed quality gate.

### 4. Run the complete key-free blocked path

This migration command evaluates the target but disables prompt proposals:

```bash
driftless migrate -w rag_qa --to gpt-4o-mini --generator none
```

`--generator none` means there is no repair generator. Because the unchanged
target fails `min_score`, Driftless has no candidate prompt edit to test. Expect
a non-zero exit with `BLOCKED`; this is intentional, and no repair is attempted.
The failed migration result is still saved.

Render the saved evidence next:

```bash
driftless report -w rag_qa
```

Expect a report containing the measured scores, remaining failures, and holdout
information when that stage was reached.

Finally, preview the delivery action:

```bash
driftless open-pr -w rag_qa
```

`open-pr` is a dry run unless `--create` is supplied, so this command performs
no GitHub operation. A blocked migration has no shippable file change.
Driftless therefore previews an **issue** that records the blocker rather than a
pull request that implies the migration is ready.

A successful repair requires an LLM generator credential and nondeterministic
provider calls. Review that result before considering `open-pr --create`.

![Browser capture of the Driftless run viewer](../visuals/run-viewer.png)

The report and delivery evidence shape is also shown in
[`EXAMPLE_SUCCESS_PR.md`](../EXAMPLE_SUCCESS_PR.md). See the
[repair reproduction boundary](./01-model-swap-is-not-a-migration.md#repair-reproduction-boundary)
for the limits of reproduced repair output.

### 5. Understand the prompt change a repair would seek

The fixture starts with an intentionally weak answer prompt:

```markdown
Answer the customer question using the retrieved support article.

Keep the answer concise. If the article seems relevant, summarize the policy in
plain language.
```

The deterministic evaluator recognizes a repaired contract only when the
prompts tell the target to:

- use only retrieved context;
- cite every factual answer;
- preserve product nouns during retrieval rewriting.

Those are prompt and configuration changes. They do not require changes to the
corpus, index, or retrieval code.

## Advanced contract boundary

The contract makes the allowed edit scope explicit:

```yaml
files:
  editable:
    - prompts/rag_answer.md
    - prompts/retrieval_rewrite.md
  readonly:
    - app/
    - data/docs.jsonl
    - data/index_manifest.json
    - evals/questions.jsonl
    - evals/gold.jsonl
```

Driftless can clarify the two prompts. It cannot silently rebuild the index,
change documents, rewrite retrieval code, or alter the gold expectations.

The score and cost gates are configured separately:

```yaml
eval:
  id_field: id
  score_field: score
  cost_field: cost
  split:
    tuning: 60%
    holdout: 40%

thresholds:
  min_score: 0.86
  max_cost_increase: 0.20
```

`max_cost_increase: 0.20` allows at most a 20% increase over baseline cost. The
fixture's negative increase is a reduction, so cost passes while quality fails.

Use `eval.judge` only when quality needs semantic grading and you do not have a
reliable deterministic scorer. An LLM judge should pass a human calibration
check before repair optimizes against it.

## Interpret the result

`Score / pass-rate` is the mean of the field named by `score_field`. Here,
`1.000` means every row fully met required-term and citation expectations.
`0.000` means none earned credit under this fixture's scoring rules. It is not a
probability that an answer is correct.

The four-row split is intentionally tiny. A passing demonstration can show that
the commands and edit boundary work, but it cannot establish production
reliability.

## Safety and failure behavior

- Keep the corpus and index read-only during a prompt migration.
- Treat an embedding-model or index rebuild as a separate change with separate
  evidence.
- Do not optimize against an uncalibrated LLM judge.
- Do not use a blocked issue preview as approval to ship.

Cost grows because every evaluation row runs retrieval, generation, and scoring.
Repair candidates and iterations repeat that work; holdout adds another target
evaluation; judge grading adds one judge call per row.

Intuitively, doubling rows doubles work, and testing several candidates per
iteration multiplies it again:

\[
\text{workflow work} \approx
\text{rows} \times \text{candidate runs} \times \text{iterations}
+ \text{holdout run}
\]

Retrieval, retries, reranking, and judge calls add their own cost inside each
run.

## Next steps

- Read [RAG and agent contract details](../rag-and-agents.md).
- Add semantic scoring only after
  [judge calibration](./06-trust-your-llm-judge.md).
- Review [cost and budget guidance](../COST_AND_BUDGETS.md).
- [Automate only after local validation](./03-dependabot-for-prompts-in-ci.md).
