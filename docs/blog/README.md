# Learn safe LLM changes with Driftless

Changing a large language model (LLM), prompt, or evaluation dataset can change
production behavior even when your Python code and unit tests still pass. This
series shows how to detect those changes before release, understand the evidence,
and decide whether to ship, repair, or stop.

The guides assume basic Python, Git, and continuous integration (CI). They explain
the LLM-evaluation concepts as they appear.

## What Driftless does

An **evaluation**, often shortened to **eval**, is a repeatable test that runs an
LLM workflow on example inputs and scores its outputs against expected results.
An **evaluation harness** is the command and code that perform that test,
including parsing and scoring.

Driftless orchestrates the evaluation harness you already trust. A committed
`driftless.yml` is the **workflow contract**: configuration that names the
harness command, the current and proposed models, evaluation data, files that
repair may edit, and the quality thresholds required for release.

Driftless does not replace your evaluator, parser, or scoring code. Your harness
remains the source of truth. The usual flow is:

1. `compare` runs the current model, called the **baseline**, and the proposed
   model, called the **candidate**, through the same harness. Driftless CLI
   output often calls that same proposed model the **target**; candidate and
   target are equivalent terms here.
2. `migrate` repairs allowed files after a model change. `refine` repairs them
   when the model stays fixed but data or labels change.
3. Driftless checks the result on a **holdout**, a set of evaluation rows that
   the repair loop did not see. This reduces the chance of tuning only to known
   examples.
4. `report` turns saved run evidence into a reviewable summary.
5. `open-pr` previews or creates a pull request when the result passes. When it
   remains blocked, Driftless can preserve the evidence in an issue instead.

In short: `compare → migrate or refine → holdout → report → PR or issue`.

## Before you start

There are two classifier fixtures in these posts. Keep their evidence separate:

- The **bundled demo** has four rows, installs with Driftless, and needs no API
  key. `--generator none` ends at a blocked quality gate; `--generator fixture`
  reproduces a passing repair. It teaches command flow; it is not evidence
  about provider-model quality or statistical confidence.
- The separate
  **[support-classifier-svc](https://github.com/driftless-dev/support-classifier-svc)**
  testbed has 290 labeled tickets, LiteLLM, and simulator plus real-API paths.
  `copy-example` does not install it. Its historical passing pull request used
  testbed-specific repair tooling that is not shipped in the Driftless CLI.

Live `migrate` and `refine` runs use a **repair generator**, the model or other
mechanism that proposes changes to allowed prompt files. The default
`--generator llm` needs provider credentials and can incur token costs. A
simulator may replace calls made by the classifier harness, but it does not
replace this separate repair generator.

## A recommended route

This route is intentionally not in post-number order: auditing labels before
repair makes the later migration and refinement evidence safer to trust.

1. Run the four-row demo below to learn the contract and comparison flow.
2. Read [post 5](./05-audit-labels-before-you-trust-f1.md) and audit labels
   before optimizing against them.
3. If the model changes, continue with
   [post 1](./01-model-swap-is-not-a-migration.md).
4. If labels or evaluation inputs change while the model stays fixed, continue
   with [post 2](./02-when-labels-move-refine-not-remodel.md).
5. Add scheduled CI automation with
   [post 3](./03-dependabot-for-prompts-in-ci.md).

### Try the bundled demo

The following commands install Driftless, copy the four-row classifier fixture,
check that its workflow contract is valid, and compare its configured baseline
with `gpt-4o-mini`:

```bash
pip install driftless
driftless copy-example support-classifier --out-dir driftless-classifier-demo
cd driftless-classifier-demo
driftless validate -w support_classifier
driftless compare -w support_classifier --to gpt-4o-mini
```

Expect validation to exercise the contract and harness, then expect comparison
to block the candidate on quality. That blocked result is intentional: it shows
that the release gate catches a behavioral regression instead of treating a
model-ID edit as safe.

## Small glossary

- **Baseline / candidate (target):** the current production choice and the
  proposed replacement compared under the same test. The prose often says
  candidate; CLI output and `--to` use target for the same proposed model.
- **Macro-F1:** the average of each class's F1 score, giving every class equal
  weight even when some classes have fewer examples. F1 balances precision
  (how often a predicted class is right) and recall (how many examples of that
  class were found).
- **Schema error rate:** the fraction of model outputs that fail the configured
  output format or parser contract.
- **Holdout:** evaluation rows hidden from repair and candidate selection, then
  used as a final release check.
- **Prompt drift:** a prompt that no longer produces the required behavior
  because its model or surrounding workflow changed.
- **Label drift:** a change in what the expected labels mean or how examples are
  labeled.
- **Dataset drift:** a broader change to evaluation inputs or expected outputs.
  Label drift is one kind of dataset drift.
- **Quality gate:** one or more thresholds that must pass before release.
- **Gold label:** the expected answer used to score one evaluation example.

## The series

1. [Your ticket classifier’s model got deprecated](./01-model-swap-is-not-a-migration.md) —
   compare a model swap, diagnose output-format failure, and migrate safely.
2. [Support changed the labeling policy](./02-when-labels-move-refine-not-remodel.md) —
   audit changed labels and refine a prompt while keeping the model fixed.
3. [Prompt repair that doesn’t wait for someone to remember](./03-dependabot-for-prompts-in-ci.md) —
   use `plan` and CI workflows to find work automatically.
4. [Finance wants cheaper inference, same bar](./04-cheaper-model-same-quality-bar.md) —
   compare cost without lowering the quality contract.
5. [Offline F1 is lying — labels conflict](./05-audit-labels-before-you-trust-f1.md) —
   detect contradictory labels before repair.
6. [Free-form answers graded by an LLM judge](./06-trust-your-llm-judge.md) —
   calibrate an LLM-based grader before trusting it.
7. [RAG QA: new answer model, same knowledge base](./07-rag-prompts-drift-too.md) —
   migrate retrieval-augmented generation (RAG), where retrieved context helps
   the model answer.
8. [Tool-calling agent: new planner, same tools](./08-agent-tool-selection-drift.md) —
   test whether an agent still selects the right tools.

Posts 7–8 use specialized, deterministic RAG and agent fixtures copied with
`copy-example`. They are neither the four-row classifier nor the external
290-row testbed. See also
[`docs/rag-and-agents.md`](../rag-and-agents.md).

## Deeper practice: external testbed reproductions

Use the following only after the bundled demo. These commands clone and install
the separate 290-row testbed, make its harness deterministic, and run the
relevant starting point for posts 1, 2, 3, and 5:

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
export OPENAI_API_KEY=...  # repair generator; simulator only replaces the harness
driftless refine -w support_classifier --strict-label-audit

# Post 3 — policy triage
driftless plan

# Post 5 — label audit (clean set)
driftless audit-labels -w support_classifier
```

Expect each command to reproduce the fixture-specific behavior described in its
post. The simulator makes the classifier harness key-free, but `migrate` and
`refine` still need credentials with the default `--generator llm`. With
`--generator none`, model migration can end `BLOCKED` because the target still
misses release gates; `--generator fixture` is only for bundled examples.
Refinement instead ends `NO_CHANGE` with exit code 0 when
nothing beats the current prompt.

For post 4, temporarily set `model.current: gpt-4o`, then run `driftless plan`
to see the cost row described there. Post 6 is not a testbed reproduction:
configure `eval.judge` and calibration JSONL in a real free-form workflow, then
run `driftless judge-check -w <workflow> --enforce` with judge credentials.

## Maintainer notes

- Keep `driftless==X.Y.Z` / `@vX.Y.Z` pinned to the current release.
- Keep genuine CLI, run-viewer, and testbed PR captures tied to their fixtures.
- State token cost and credential requirements for live `migrate`/`refine`.
- Preserve the canonical pull request #4 reproduction boundary in
  [post 1](./01-model-swap-is-not-a-migration.md#repair-reproduction-boundary);
  other posts should link there instead of repeating it.
