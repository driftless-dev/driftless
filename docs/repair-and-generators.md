# Developer Guide: Repair Prompts & Custom Generators

This guide explains how the migration engine repairs a workflow, how to
customize the repair prompt, and how to write your own patch generator.

- [Mental model](#mental-model)
- [The migration loop](#the-migration-loop)
- [Customizing the repair prompt](#customizing-the-repair-prompt)
- [Writing a custom generator](#writing-a-custom-generator)
- [Safety guarantees](#safety-guarantees)
- [Testing your generator](#testing-your-generator)

## Mental model

The engine (`driftless/engine.py`) is fixed orchestration: split data,
run the workflow under each model, score, iterate, validate on holdout, commit.
The **only** creative step is *deciding what edits to try*. That step is a
pluggable seam called a **`PatchGenerator`**.

```
failures ─▶ PatchGenerator.generate(context) ─▶ candidate Patches
                                                    │
                          engine evaluates each on the tuning split,
                          keeps the best, validates on holdout, commits
```

There are two ways to influence repair, from least to most effort:

1. **Customize the prompt** of the built-in `LLMPatchGenerator` via the contract
   (no code).
2. **Write your own generator** that implements the `PatchGenerator` protocol.

## The migration loop

This is the full algorithm implemented by `run_migration` in `engine.py`. The
same loop powers both `migrate` and `refine`; they differ only in the
**objective** (and `refine` pins the model).

**Objectives**

- `MEET_THRESHOLDS` (`migrate`): recover quality on a *new model* until the
  contract's `thresholds:` pass. Candidates are scored by *how close they are to
  passing* (`_score_key`).
- `MAXIMIZE` (`refine`): the *dataset* changed, so the old thresholds are stale.
  The model is pinned and the loop just chases the best primary metric, then
  proposes fresh thresholds (`_maximize_key`).

**Definitions** — `primary` = F1 (or score/pass-rate for graded tasks);
`diff_size(patch)` = changed lines (added + removed) of the patch vs. the
*original* editable files; `evaluate(model, files, split)` = apply `files` in a
backup/restore sandbox, run the real workflow under `model`, score the split.

```text
run_migration(W, M_target, generator G, objective O, seed):

  # ── Setup ───────────────────────────────────────────────────────────────
  tuning, holdout ← split(W.dataset, seed)            # deterministic, seeded
  M_current       ← W.model.current
  baseline        ← evaluate(M_current, current_files, tuning)
  naive_target    ← evaluate(M_target,  current_files, tuning)

  # ── Short-circuit: is a bare model swap already enough? (migrate only) ────
  if O = MEET_THRESHOLDS and passes(W.thresholds, baseline, naive_target)
     and passes_on(holdout):
       return MODEL_CHANGE_ONLY                        # just bump the model ID

  # ── Iterative repair ─────────────────────────────────────────────────────
  original  ← current editable file contents           # frozen, for diff sizing
  best      ← naive_target ;  best_files ← {} ;  best_size ← 0
  width     ← G.num_candidates ;  widened ← false      # adaptive search width

  for i in 1 .. W.migration.max_iterations:
      clusters   ← cluster_failures(best.rows)          # group similar errors
      context    ← { clusters, failing & correct examples, attempt history,
                     read-only context files, current editable files }
      n          ← escalated_width if widened else width
      candidates ← G.generate(context, n)               # the only creative step
      if candidates = ∅: break

      improved ← false
      for patch in candidates:
          size ← diff_size(patch, original)
          try:
              check_scope(patch)                        # reject edits outside files.editable
              cand ← evaluate(M_target, apply(patch), tuning)
          except DriftlessError:                        # patch broke the workflow
              log(patch, error, size) ;  continue       # skip it — never abort the run

          key      ← score_key(cand,  O)                # O-dependent ranking
          best_key ← score_key(best,  O)
          accept   ← key > best_key                     # strictly better, OR …
                     or (key = best_key and size < best_size)   # tie → smaller edit
          log(patch, cand, accept, size)
          if accept:
              best, best_files, best_size ← cand, patch.files, size
              improved ← true

      # commit as soon as we clear the bar on never-tuned data (migrate only)
      if O = MEET_THRESHOLDS and passes(W.thresholds, baseline, best)
         and passes_on(holdout, best_files):
           commit(best_files) ;  return PASS

      if improved:
          widened ← false                               # progress → back to cheap width
      else if can_widen and not widened:
          widened ← true ;  continue                    # stall → widen search once
      else:
          break                                         # stalled at full width → stop

  # ── Resolve outcome ──────────────────────────────────────────────────────
  if O = MAXIMIZE:                                       # refine
      validate(best_files) on holdout (no-regression vs. current prompt)
      suggest fresh thresholds from the holdout metrics
      if best beats naive_target: commit(best_files) ; return PASS
      else:                       return NO_CHANGE       # nothing beat the current prompt
  else:                                                  # migrate, thresholds unmet
      if best improved over naive_target: return PARTIAL # improved but NOT committed
      else:                               return BLOCKED
```

**Key invariants**

- **Sandboxed trials.** Every candidate is applied via backup → run → restore;
  the working tree is only written on a committed `PASS`.
- **Crash isolation.** A candidate that breaks the workflow (e.g. emits invalid
  YAML/JSON) is logged as a failed attempt and skipped — it can't abort the run.
- **Minimal-change tie-breaker.** On an exact score tie the smaller edit wins;
  against the no-op baseline (`best_size = 0`) a same-scoring patch is rejected,
  so the loop never makes a change that doesn't help.
- **Stall-escalation.** A stalled iteration widens the candidate pool once (to
  `max(width × 3, 5)`) before giving up — cheap when easy, broad when stuck.
- **Holdout gate.** Nothing is committed until it clears a split it never tuned
  against, bounding overfitting to the tuning rows.

## Measuring migration gains honestly

`compare` and `migrate` score the **current prompt** on the current model
(`baseline`) and the **same prompt** on the target model (`naive_target`). That
is the right default — it mirrors what happens when you flip a model ID in prod
without touching the prompt.

But it conflates two effects when the prompt was never tuned to its ceiling on
the source model:

1. **Prompt debt** — under-optimization that would improve on *either* model.
2. **Model-induced drift** — quality lost because the target behaves differently
   from the model the prompt was written for.

A headline "we migrated and gained +0.07 F1" can be mostly (1), not migration
repair. The dataset-change path (`refine`) avoids this entirely — the model is
pinned and only the labels move — so scenarios 2–4 in the testbed are clean
demos of prompt repair. The model-switch path needs a control.

### 2×2 control (recommended for model migrations)

Optimize (or hand-tune) the prompt on the **source** model first, *then* switch.
Measure four cells on the same eval set (macro-F1 shown; same 290 baseline
labels, real API calls, no simulate flag):

| Prompt | Source (`gpt-3.5-turbo`) | Target (`gpt-4o-mini`) |
|---|---|---|
| **P0** — original hand prompt | 0.922 | 0.904 |
| **P_src\*** — optimized for source | **0.993** (A) | **0.921** (B) |
| **P_tgt\*** — optimized for target | **1.000** (C) | **0.987** (D) |

How to read it:

- **P0 → A (0.922 → 0.993)** = prompt debt on the source model. Not migration.
- **P0 source vs target (0.922 vs 0.904)** = no meaningful regression with an
  *unoptimized* prompt — easy to misread as "the swap is fine."
- **A → B (0.993 → 0.921, −0.072)** = true model-induced drift *from a strong
  baseline*. The source-tuned few-shots transfer poorly to 4o-mini.
- **B → D (0.921 → 0.987, +0.066)** = gain attributable to re-tuning after the
  switch, starting from an already-source-optimized prompt.
- **C ≈ A** = target optimization also found a generally better prompt; perfect
  separation of "model adaptation" vs "more optimization" isn't possible.

**Practical guidance**

- Treat `compare`'s baseline→naive delta as a **lower bound on urgency**, not
  the full story. If baseline is far below your quality bar, run a source-model
  `refine` (or hand-tune) first, then `compare --to` again.
- Report migration repair relative to **(B)** — target model + source-optimized
  prompt — not relative to **(P0)**.
- Lead product demos with **dataset-change** scenarios when possible; they
  isolate the dependency being tested. Use the 2×2 when demonstrating model
  migration specifically.
- Offline simulator regressions (fenced JSON, refund→billing) are useful for CI
  but **do not reproduce on real `gpt-4o-mini`** for this testbed; real-model
  validation is required for the model-switch axis.

Reproduce the control in `../support-classifier-svc`: `driftless refine` with
the contract pinned to `gpt-3.5-turbo` (yield **P_src\***), score both models,
switch `current` to `gpt-4o-mini`, `refine` again (yield **P_tgt\***), score
both models. See that repo's README §1 for the offline vs real-model split.

## Customizing the repair prompt

The built-in `LLMPatchGenerator` reads an optional `repair:` block from each
workflow in `driftless.yml`. Three levels of control:

### 1. Add guidance (recommended)

Keep all the built-in migration expertise and just add your domain rules:

```yaml
workflows:
  support_classifier:
    # ...
    repair:
      guidance: |
        Refund tickets must never be labeled "billing".
        Keep the JSON output on a single line.
```

`guidance` is appended to whichever system prompt is in effect.

### 2. Replace the system prompt

```yaml
    repair:
      system_prompt: "You are a meticulous prompt engineer. ..."
      # or load from a file:
      # system_prompt_path: prompts/repair_system.md
```

Inline values take precedence over their `*_path` file counterparts.

### 3. Replace the user prompt template

For full control over what the model sees each iteration:

```yaml
    repair:
      user_template_path: prompts/repair_user.md
```

The template supports `{{placeholder}}` substitution. Available placeholders:

| Placeholder | Contents |
|---|---|
| `{{workflow}}` | Workflow name |
| `{{description}}` | Workflow description |
| `{{target_model}}` | Model being migrated to |
| `{{iteration}}` | Current iteration number |
| `{{metrics}}` | JSON: baseline vs. current-target metrics |
| `{{failure_clusters}}` | JSON: `[{kind, key, count}, ...]` |
| `{{failing_examples}}` | JSON: sampled `{index, type, input, raw_output, gold, predicted, score, wrong_fields, judge_rationale}` (type ∈ schema_error/refusal/misclassification/field_error/low_score/failed_check) |
| `{{correct_examples}}` | JSON: per-class correct/high-scoring rows `{input, raw_output, label, score}` |
| `{{attempt_history}}` | JSON: prior edits and how they scored |
| `{{cluster_trajectory}}` | JSON: per-cluster counts across iterations |
| `{{readonly_context_files}}` | JSON: `files.context` contents (reference only) |
| `{{editable_files}}` | JSON: `{path: current_content}` |

Declare `files.context` in `driftless.yml` to show the optimizer read-only
surrounding code (for example the output parser, or pre/post-processing) without
making it editable — useful so it can interpret why rows pass or fail:

```yaml
files:
  editable: [prompts/system.txt]
  context: [src/parse_output.py]
```

`failing_examples` and `correct_examples` carry the **real** input line and the
raw output the workflow wrote (truncated for long values), so the optimizer can
see *why* a row failed and what working rows look like — not just label pairs.

Unknown placeholders are left intact (literal `{{...}}` is safe). Your template
must instruct the model to return JSON of the form the parser expects:

```json
{"rationale": "...", "files": {"<editable path>": "<full new content>"}}
```

Paths are resolved relative to the repo root; a missing file raises a clear
error.

## Writing a custom generator

A generator is any object with a `generate(context) -> list[Patch]` method.

```python
from driftless.engine import Patch, PatchContext, PatchGenerator


class RuleBasedGenerator:
    """Example: tighten the JSON instruction when schema errors dominate."""

    def generate(self, context: PatchContext) -> list[Patch]:
        schema_failing = any(c.kind == "schema_error" for c in context.clusters)
        if not schema_failing:
            return []

        patches = []
        for path, content in context.editable_files.items():
            if not path.endswith((".md", ".txt")):
                continue
            new = content + (
                "\n\nIMPORTANT: Respond with a single valid JSON object only. "
                "No prose, no code fences."
            )
            patches.append(Patch(files={path: new}, rationale="tighten JSON format", kind="rule"))
        return patches
```

### What `PatchContext` gives you

```python
@dataclass
class PatchContext:
    workflow: Workflow            # full contract entry (incl. repair, thresholds)
    workflow_name: str
    target_model: str
    iteration: int
    editable_files: dict[str, str]  # path -> CURRENT content (only editable files)
    baseline: Metrics             # current model on the tuning split
    current: Metrics              # best candidate so far on the tuning split
    clusters: list[FailureCluster]  # kind: schema_error | refusal | misclassification | field_error | low_score | failed_check
    rows: list[RecordRow]         # per-record: predicted, gold, is_refusal, ...
    cwd: Path                     # repo root, for resolving relative file paths
```

### Returning patches

A `Patch` maps **editable** file paths to their **full new content**:

```python
Patch(files={"prompts/support_classifier.md": "<new content>"}, rationale="...", kind="...")
```

- Return multiple patches to give the engine options; it scores each and keeps
  the best. Return `[]` to propose nothing this iteration (the loop stops).
- You may return partial content edits as long as the value is the complete new
  file content (the engine overwrites the whole file).

### Wiring it in

`run_migration` takes a `generator` argument:

```python
from driftless.engine import run_migration
from driftless.contract import load_contract

contract = load_contract()
wf = contract.workflow("support_classifier")
result = run_migration(
    "support_classifier", wf, "gpt-5-mini",
    generator=RuleBasedGenerator(),
)
```

To expose it through the CLI, extend `build_generator` in
`driftless/generators.py` with a new `kind`, then pass `--generator <kind>`
to `driftless migrate`.

### Adapting an LLM-backed generator

If you have existing LLM repair logic, the easiest path is to reuse
`LLMPatchGenerator` and only customize the prompts (see above), or inject your
own completion function:

```python
from driftless.generators import LLMPatchGenerator

def my_complete(system: str, user: str, temperature: float) -> str:
    # call your model / gateway, return the raw text response
    ...

gen = LLMPatchGenerator(complete_fn=my_complete, num_candidates=2)
```

`LLMPatchGenerator` handles prompt construction (respecting the contract's
`repair:` block), temperature variation across candidates, tolerant JSON
parsing, and scoping the result to editable files.

## Safety guarantees

These hold regardless of what a generator returns:

- **Edit scope.** `validate_patch_scope` rejects any patch touching a file not
  listed in `files.editable`. A generator cannot modify business logic, schemas,
  or read-only files.
- **Sandboxing.** All trial edits are applied in a backup/restore sandbox; files
  are written to disk only on a holdout-validated `pass`.
- **Holdout gate.** A candidate must pass thresholds on data it never tuned
  against before it is committed.
- **No auto-merge.** The product opens PRs/issues; humans review and merge.

Design your generator to *propose* freely — the engine is responsible for
accepting or rejecting.

## Testing your generator

Because the loop runs the real workflow, you can test a generator end-to-end
against a tiny fixture workflow without any network access:

```python
from driftless.engine import run_migration, MigrationStatus

def test_my_generator(tmp_path):
    wf = make_fixture_workflow(tmp_path)  # a runnable command + tiny eval set
    result = run_migration("demo", wf, "weak", generator=MyGenerator(), cwd=tmp_path)
    assert result.status == MigrationStatus.PASS
```

For LLM-backed generators, inject a fake `complete_fn` so no API is called:

```python
def fake_complete(system, user, temperature):
    return '{"files": {"prompt.txt": "STRICT: echo the exact label."}}'

gen = LLMPatchGenerator(complete_fn=fake_complete)
```

See `tests/test_engine.py` and `tests/test_generators.py` for complete,
runnable examples (including a fixture workflow whose target-model behavior
depends on the edited prompt).
