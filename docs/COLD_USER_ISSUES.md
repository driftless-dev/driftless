# Cold-User Issues

Working list of friction found by walking the published docs as a first-time
user. Documented commands on PyPI `0.3.4` succeed; these items are the places
someone would stall if they followed the CLI more than Getting Started.

Update status here when an item is fixed. Add new rows from later walkthroughs
instead of opening a second list.

Last walkthrough: 2026-08-15 against **driftless 0.3.4** from PyPI, fresh venv,
no provider keys. Later the same day: `config_file` PRs, `plan`, `audit-labels`,
`refine`, `--generator llm` without a key, `init-ci` on Actions, merge of PR #3,
`poll`, endpoint harness, `judge-check`, 0.2 upgrade, `init-ci --plan`, and a
live OpenAI eval whose harness actually calls the model (CU-21–CU-24).

## How to re-run

```bash
python3 -m venv /tmp/driftless-newuser-venv
/tmp/driftless-newuser-venv/bin/pip install driftless
export PATH="/tmp/driftless-newuser-venv/bin:$PATH"

# Golden path
driftless copy-example support-classifier --out-dir /tmp/driftless-classifier-demo
cd /tmp/driftless-classifier-demo
driftless validate -w support_classifier
driftless compare -w support_classifier --to gpt-4o-mini
driftless migrate -w support_classifier --to gpt-4o-mini --generator none   # exit 1
driftless report -w support_classifier
driftless open-pr -w support_classifier
driftless migrate -w support_classifier --to gpt-4o-mini --generator fixture
driftless report -w support_classifier
driftless open-pr -w support_classifier

# Existing-repo path: copy tests/fixtures/adoption-app, delete driftless.yml
driftless scan
driftless configure incident_brief --apply
driftless validate -w incident_brief
driftless compare -w incident_brief --to gpt-4o-mini
```

Same compare → `--generator none` (blocked) → `--generator fixture` (pass)
shape also holds for `copy-example rag-qa` (`-w rag_qa`) and
`copy-example tool-agent` (`-w support_agent`).

## Open

| ID | Severity | Issue | Status |
|---|---|---|---|
| CU-1 | High | `copy-example` next-step hint uses `-w <workflow>` instead of the real name | fixed |
| CU-2 | High | `scan` does not hand off to `configure` when the model is still active | fixed |
| CU-3 | Medium | `copy-example --help` and no-args error omit `support-classifier` | fixed |
| CU-4 | Medium | `scan` does not suggest a workflow name for `configure` | fixed |
| CU-5 | Medium | `view` on a busy port dumps a traceback | fixed |
| CU-6 | Low | CLI `--help` one-liner is narrower than the product copy | fixed |
| CU-7 | High | Passing env-var PR does not change the model ID and does not say so | fixed |
| CU-8 | Low | Created PRs are ready-for-review; docs and historical proof show drafts | fixed |
| CU-9 | Medium | Blocked issue stays open after the passing PR is created | fixed |
| CU-10 | High | `open-pr --create` does not print the issue or PR URL | fixed |
| CU-11 | High | `config_file` PR does not update `driftless.yml` or the example harness | fixed |
| CU-12 | High | Generated CI migrate defaults to `--generator llm` and then `open-pr` fails | fixed |
| CU-13 | High | Bundled classifier cannot demonstrate `refine` (prompt is ignored for gpt-4) | fixed |
| CU-14 | Medium | After a label change, `refine` exits 0 and suggests holdout thresholds of 0.97 | fixed |
| CU-15 | Low | `plan` Retires column shows `-319d` for an already-retired model | fixed |
| CU-16 | High | Default `poll` gate is 5 rows; the 4-row demo can never fire | fixed |
| CU-17 | Low | `poll` fetch lines print raw `[dim]...[/]` tags | fixed |
| CU-18 | High | `judge-check` dumps a traceback; hint mentions `--generator` | fixed |
| CU-19 | Medium | `judge-check` requires an API key before it checks the calibration file | fixed |
| CU-20 | High | Live `--generator llm` cannot pass the bundled classifier (fixture can) | fixed |
| CU-21 | High | `eval.split.tuning: 100%` still holds out one row | fixed |
| CU-22 | High | `migrate` can PASS while `compare` on the same files FAILs | fixed |
| CU-23 | Medium | BLOCKED scorecard shows tuning F1 1.000 and hides the holdout failure | fixed |
| CU-24 | Medium | LLM repair invents labels from predictions, not gold | fixed |

### CU-1 — `copy-example` prints a placeholder workflow name

**Status:** fixed. After copy, the CLI reads the example `driftless.yml` and
prints `driftless validate -w support_classifier` (or `rag_qa` /
`support_agent`). `plan` next-step uses the first actionable workflow and
candidate instead of `-w <workflow> --to <model>`.

After a successful copy, the CLI says:

```text
Next:
  cd driftless-classifier-demo
  driftless validate -w <workflow>
```

A user who only follows the terminal does not learn that the name is
`support_classifier` (or `rag_qa` / `support_agent`). The copied example README
has the name; the CLI hint does not.

**Where:** `src/driftless/cli.py` (`copy_example`), hardcoded
`driftless validate -w <workflow>`.

`plan` has the same placeholder in its next-step line:
`driftless migrate -w <workflow> --to <model>`.

**Fix:** Print the workflow name from the copied `driftless.yml`. Fall back to
`<workflow>` only if the contract is missing or has several workflows and none
is obvious.

### CU-2 — `scan` stops after “no deprecated models”

**Status:** fixed. Active-model scans still print a next step:
`driftless configure <suggested> --apply`.

On the incident-brief adoption fixture, `scan` finds `gpt-4o` / `BRIEF_MODEL`
and then prints **No deprecated or retired models detected.** It never says to
run `configure`. That is the landing-page cost-reduction case: the model is
active, and the user still wants a cheaper target gated.

`configure <name>` is only mentioned when `at_risk` models exist.

**Where:** `src/driftless/cli.py` (`scan`).

**Fix:** Always print a next step, for example
`driftless configure <name> --apply`, including when every detected model is
active. Pair with CU-4 so `<name>` is not invented.

### CU-3 — Example discovery hides the golden path

**Status:** fixed. `--help` lists `support-classifier`, `rag-qa`, and
`tool-agent`. No-args prints `available examples: ...` instead of a Typer
missing-argument dump.

- `driftless copy-example --help` says “such as rag-qa or tool-agent” and does
  not mention `support-classifier`.
- `driftless copy-example` with no args is a Typer missing-argument error and
  does not list available examples.

**Where:** `src/driftless/cli.py` (`copy_example` argument help);
`src/driftless/examples.py` (`available_examples`).

**Fix:** List all bundled names in `--help`. On a missing `name`, print
`available examples: support-classifier, rag-qa, tool-agent`.

### CU-4 — User must invent the `configure` workflow name

**Status:** fixed. `scan` suggests a slug from the package name, env var, or
detected file. `configure` without a name uses the same suggestion
(`incident-brief` → `incident_brief`).

`configure` requires a workflow argument. `scan` does not propose one from the
detected files (`brief.py`, `BRIEF_MODEL`, package name `incident-brief`). The
walkthrough only succeeded because the test fixture already used
`incident_brief`.

**Where:** `src/driftless/cli.py` (`scan`, `configure`);
`src/driftless/configure.py`.

**Fix:** Suggest a slug from the package name, primary env var, or detected
file (and show it in the scan next-step line from CU-2).

### CU-5 — `view` traceback when the port is taken

**Status:** fixed. A busy port raises `port N is in use` with a `--port`
hint instead of an `OSError` traceback.

`driftless view -w support_classifier --no-open --port <busy>` raises
`OSError: Address already in use` as a raw traceback. The viewer itself works
on a free port (`/runs.html` returned 200).

**Where:** `src/driftless/cli.py` (`view`) only catches `DriftlessError`;
`src/driftless/view.py` (`serve_runs`).

**Fix:** Catch the bind error and print `port N is in use; try --port M`.

### CU-6 — CLI help vs site wording

**Status:** fixed. `driftless --help` now leads with “Keep models, prompts,
and eval data in sync.”

`driftless --help` says “Dependabot for LLM models…”. The landing page and
README talk about keeping models, prompts, and eval data in sync. Not a
blocker; the first command a new user runs undersells the product.

**Where:** `src/driftless/cli.py` (`app` help string).

**Fix:** Align the one-liner with the README / hosted docs lede.

### CU-7 — Passing PR does not actually change the model

**Status:** fixed. A passing `open-pr` now includes `model.current` in
`driftless.yml` and states how runtime is selected (env var and/or
`config_file`). The classifier example also ships `config/llm.yml`.

Live PR: https://github.com/alexminnaar/driftless-cold-user-pr-test/pull/2

Title: `chore: migrate support_classifier from gpt-4 to gpt-4o-mini`.
Files changed: only `prompts/classifier.md`. `driftless.yml` on the PR branch
still has `model.current: gpt-4`. The example selects the model via `env_var:
MODEL`, so `open-pr` has no config file to edit.

The env-var “update it in your deployment configuration” note is only added
when a migration succeeds with **no** file changes. A prompt repair hides that
note, so a reviewer can merge a “model migration” that never bumps the model.

**Where:** `src/driftless/github.py` (`build_pr_plan`, `apply_model_change`);
bundled `examples/support-classifier/driftless.yml` has `env_var` only.

**Fix:** Either update `model.current` in `driftless.yml` on a passing
migration, or always state in the PR body that the runtime model is still an
env var / deploy setting. The golden-path example should include a
`config_file` if the intended proof is “the PR changes the model.”

Follow-up (same day): adding `config_file: config/llm.yml` produced
[PR #3](https://github.com/alexminnaar/driftless-cold-user-pr-test/pull/3),
which does change `config/llm.yml` from `gpt-4` to `gpt-4o`. That is the
intended `config_file` path. Remaining gaps are CU-11.

### CU-8 — PR is not a draft

**Status:** fixed. Passing migration PRs open as drafts (`gh pr create --draft`).

`PullRequestPlan.draft` defaults to `False` and `build_pr_plan` never sets it.
The live PR opened as ready-for-review. The landing page, historical testbed
PR #4, and “draft PR” language suggest reviewers get a draft.

**Where:** `src/driftless/github.py` (`build_pr_plan`).

**Fix:** Open migration PRs as drafts unless the user opts out, or drop the
draft language from the site.

### CU-9 — Blocked issue is not closed or linked when the PR lands

**Status:** fixed. A passing `--create` PR mentions `Supersedes #N` and
comments + closes the matching `migration blocked` issue.

Same walkthrough created
[issue #1](https://github.com/alexminnaar/driftless-cold-user-pr-test/issues/1)
(`Do not migrate`) and then
[PR #2](https://github.com/alexminnaar/driftless-cold-user-pr-test/pull/2)
(`Approve migration`). The issue stayed open. The PR does not reference it.

A new user following Getting Started (`--generator none` then `fixture`) ends
with contradictory open artifacts.

**Where:** `src/driftless/github.py` (`execute_plan`).

**Fix:** On a passing `--create`, close or comment on the matching blocked
issue and mention it in the PR body.

### CU-10 — `--create` swallows the GitHub URL

**Status:** fixed. `issue created` / `PR created` now append the URL from
`gh` stdout.

`gh issue create` / `gh pr create` stdout is captured. The CLI prints
`issue created` / `PR created` and no URL. A first-time user has to hunt on
GitHub.

**Where:** `src/driftless/github.py` (`_run`, `execute_plan`).

**Fix:** Print the URL from `gh` stdout (or `gh pr view --json url` afterward).

### CU-11 — `config_file` PR does not update the contract or the example app

**Status:** fixed. Passing PRs update `model.current` in the contract and
the configured `config_file`. The bundled harness reads `config/llm.yml`
when `MODEL` is unset. The PR body says which knobs changed.

Live PR: https://github.com/alexminnaar/driftless-cold-user-pr-test/pull/3

After adding `config/llm.yml` + `model.config_file` / `config_path` as Getting
Started describes:

- `migrate --to gpt-4o --generator none` returns `MODEL_CHANGE_ONLY` and does
  **not** write the config file.
- `open-pr --create` then writes `config/llm.yml` (`gpt-4` → `gpt-4o`) and
  opens a one-file PR.
- `driftless.yml` on that branch still has `model.current: gpt-4`.
- The bundled harness reads `MODEL`, not `config/llm.yml`. Merging the PR
  changes a file the example never reads.

The PR body also says “Updated model ID only. No prompt/config changes were
required” while the only commit is a config-file edit.

**Where:** `src/driftless/github.py` (`apply_model_change` is open-pr-only);
`examples/support-classifier/app/eval_classifier.py` (env var only).

**Fix:** Update `model.current` in the contract on a passing migration, or
make the example harness read `config/llm.yml`. Say in the PR body which
runtime knob actually changed.

Confirmed after merge (2026-08-15): PR #3 was merged to main.
`config/llm.yml` is `gpt-4o`. `validate` still reports `current model gpt-4`.
`plan` still exits 1 with **PR (critical)** for `gpt-4 -> gpt-4o`. `scan`
still flags `gpt-4` as at-risk (from `driftless.yml` and the harness default)
alongside the new `gpt-4o` in the config file. The Dependabot-style loop did
not close.

### CU-12 — Generated CI migrate needs a key, then `open-pr` fails loudly

**Status:** fixed. Generated migrate accepts a `generator` input (default
`llm`, documented as needing a key). `open-pr` is skipped when migrate
did not write a result file.

`init-ci` on the copy-example repo writes a migrate workflow whose args are
only `--strict-label-audit`. Default generator is `llm`.

As generated, Actions run
https://github.com/alexminnaar/driftless-cold-user-pr-test/actions/runs/31906665929
failed:

1. `migrate`: `no LLM provider API key found for patch generation`
2. `open-pr --create` still ran (`continue-on-error` on migrate) and failed
   with `no migration result` because the key error happens before a result
   file is written.

`init-ci` does tell the user to add `OPENAI_API_KEY`. A user coming from the
key-free demo still hits a red X. Adding `--generator fixture` to `args`
made the same workflow pass
(https://github.com/alexminnaar/driftless-cold-user-pr-test/actions/runs/31906754734);
`open-pr` then correctly skipped the already-open PR #2.

**Where:** `src/driftless/init_ci.py` (`render_migrate_workflow`); Action
defaults `generator` to `llm`.

**Fix:** Document that generated migrate is paid, or accept `--generator` as
a workflow input. Skip `open-pr` when migrate did not write a result.

### CU-13 — Bundled classifier cannot demonstrate `refine`

**Status:** fixed. The current-model path now follows the prompt's label
list, so `billing` → `refund` is recoverable by editing the prompt (or
`refine`). Mini models still need a closed taxonomy plus an exact-output
instruction.

`app/eval_classifier.py` previously only consulted the prompt when the model name
contains `mini`. `refine` pins `model.current` (`gpt-4`), so prompt edits
cannot change the score.

After changing gold `billing` → `refund`:

- Current F1 dropped to `0.500`.
- `refine --generator none` and `--generator fixture` both returned
  `NO_CHANGE` (fixture still cannot beat a harness that ignores the prompt).
- A paid `--generator llm` run would hit the same wall on this example.

**Where:** `examples/support-classifier/app/eval_classifier.py`.

**Fix:** Make the current-model path depend on the prompt, or ship a refine
demo whose labels actually drive the harness. The label-change blog path is
not reproducible from `copy-example` without keys *or* a harness change.

### CU-14 — `refine` looks successful after quality dropped

**Status:** fixed. `NO_CHANGE` below the contract bar exits 1 with a
warning. Suggested thresholds use the weaker of tuning and holdout.

Same label-change run: F1 `1.000 → 0.500`, status `NO_CHANGE`, exit 0.
Suggested thresholds were taken from the **holdout** (the changed row was in
tuning) and still proposed `min_f1: 0.97`.

A new user can read that as “refine worked; paste these thresholds” while
the updated dataset no longer meets them.

**Where:** `src/driftless/cli.py` (`refine`); threshold suggestion uses
holdout metrics.

**Fix:** Exit non-zero or warn when the current prompt scores below the old
bar on the new data. Suggest thresholds from the full set, or show tuning
and holdout side by side.

### CU-15 — `plan` Retires column is easy to misread

**Status:** fixed. Past dates print `retired 319d ago` instead of `-319d`.

For `gpt-4` (retired 2025-09-30, walkthrough date 2026-08-15) the table
showed `Retires: -319d`. The Why line (“retired 319d ago”) is clear; the
column is not.

**Where:** `src/driftless/cli.py` (`plan` table).

**Fix:** Print `retired 319d ago` (or `retired`) in the column.

### CU-16 — Default `poll` gate is larger than the demo dataset

**Status:** fixed. `min_changed_rows` is capped at the dataset size, so
rewriting all 4 demo labels fires. A 1-row edit on that set still stays
quiet.

`DataChangePolicy.min_changed_rows` defaults to **5**. The bundled classifier
has **4** gold rows.

After recording a baseline, flipping every gold label still printed
`No meaningful dataset changes. Nothing to refine.` Setting
`.driftless/policy.yml` to `min_changed_rows: 1` then reported
`+0 / -0 / ~4 of 4` and exited 1 (the CI gate).

A new user who follows the demo and then tries `poll` will never see a
dataset-change trigger unless they add rows or change the policy. The
`init-policy` template comments the same default of 5.

**Where:** `src/driftless/policy.py` (`DataChangePolicy`);
`examples/support-classifier/evals/gold.jsonl`.

**Fix:** Lower the demo policy, mention the gate next to `poll` in Getting
Started, or ship a poll example with ≥5 rows.

`poll --act --generator none` after that trigger ran refine and reported
`no_change -> nothing to open` (same harness limit as CU-13). `data_source.command`
(`cp evals/external/gold.jsonl evals/gold.jsonl`) did fetch correctly.

### CU-17 — `poll` fetch lines leak Rich markup

**Status:** fixed. Fetch lines render with Rich markup on, so `[dim]` is
styling rather than literal text.

With `data_source.command` set, `poll` printed:

```text
[dim]fetch support_classifier: ran data_source.command: cp
evals/external/gold.jsonl evals/gold.jsonl[/]
```

The tags are passed to `console.print(..., markup=False)`, so they show up
as literal text.

**Where:** `src/driftless/cli.py` (`poll` fetch loop).

**Fix:** Drop the `[dim]...[/]` wrappers when markup is off, or print with
markup on.

### CU-18 — `judge-check` traceback and the wrong hint

**Status:** fixed. `build_judge` is inside the `DriftlessError` handler. The
missing-key hint no longer mentions `--generator`.

On a judge-graded workflow with no provider key, `judge-check` raised an
uncaught `DriftlessError` traceback instead of the usual `error:` / `hint:`
lines. The hint is copied from patch generation:

```text
set OPENAI_API_KEY or ANTHROPIC_API_KEY, pass --generator none,
or use --generator fixture with a bundled example
```

`--generator` is not a `judge-check` option. A new user following the RAG
judge docs hits a stack trace.

`judge-check` on the classifier (not judge-graded) is fine:
`error: 'support_classifier' is not judge-graded`.

**Where:** `src/driftless/cli.py` (`judge_check` calls `build_judge` outside
the `DriftlessError` handler); `src/driftless/generators.py`
(`_resolve_provider`).

**Fix:** Catch `DriftlessError` around `build_judge`. Use a judge-specific
hint (set a key; this command cannot use `fixture`).

### CU-19 — Calibration-file errors are hidden by the key check

**Status:** fixed. `judge-check` validates that `calibration_path` exists
before constructing the LLM judge.

`judge-check` constructs the LLM judge before it reads
`eval.judge.calibration_path`. With the calibration file deleted, the
failure was still “no LLM provider API key found for patch generation,” not
“calibration file not found.”

**Where:** `src/driftless/cli.py` (`judge_check`);
`src/driftless/judges.py` (`build_judge` / `judge_agreement`).

**Fix:** Validate `calibration_path` exists first. Then resolve the provider.

### CU-20 — Live `--generator llm` fails on the golden-path demo

**Status:** fixed. Mini recovery accepts common “return only / one of the
following” phrasings plus the four label names, not only the fixture
sentence `use exact labels only`. Combined with CU-24 (gold labels in the
repair prompt).

2026-08-15, published `0.3.4`, OpenAI `gpt-4o` as the repair model.

`driftless migrate -w support_classifier --to gpt-4o-mini --generator llm`
on a fresh `copy-example`:

- 1-iteration / 1-candidate run: **BLOCKED**, 1 attempt, F1 stayed `0.000`.
- Default 3-iteration / 2-candidate run: **BLOCKED**, 7 attempts, 0 accepted,
  F1 stayed `0.000`.

The LLM wrote reasonable few-shot examples (and even mentioned a `general`
label). The bundled harness does not call a model. It emits `general` for
any `*mini*` model unless the prompt contains the exact phrase
`use exact labels only` plus the four category names. `--generator fixture`
injects that phrase; the live generator never discovered it.

A new user who finishes the key-free tour and then tries the documented
`--generator llm` path will see the demo stay blocked.

**Where:** `examples/support-classifier/app/eval_classifier.py`
(`prompt_is_strict`); `src/driftless/generators.py` (`LLMPatchGenerator`).

**Fix:** Make the demo harness score prompt quality in a way an LLM can
learn (or document that `llm` is not expected to pass this example). Do not
present fixture-pass and llm-repair as the same loop.

Live `judge-check` with a key **did** work: 4 calibration rows, MAE 0.410
(over a 0.25 gate), correlation 0.988. Default exit 0; `--enforce` exited 1
with a clean error (no traceback). CU-18 is the no-key path only.

On a **real** OpenAI harness (not the bundled magic-phrase eval),
`--generator llm` did accept a prompt and exit 0 — see CU-21–CU-24. CU-20
is specifically “the published demo cannot demonstrate llm repair.”

### CU-21 — `tuning: 100%` still holds out one row

**Status:** fixed. `make_splits` honors `holdout: 0%` / `tuning: 100%`.
`holdout_required: true` with an empty holdout is now an error instead of
a silent steal. The report records the actual split sizes.

`src/driftless/splits.py` previously reserved at least one holdout example:

```python
tuning_count = max(1, min(n - 1, round(n * tuning_frac)))
```

A contract with `tuning: 100%` / `holdout: 0%` on 4 labeled tickets still
tunes on 3 and holds out 1. There is no warning that the requested split
was rewritten.

In the live-API check, the held-out row was the only `shipping` example.
The repairer never saw that class.

**Where:** `src/driftless/splits.py` (`make_splits`).

**Fix:** Honor `holdout: 0%` (empty holdout). If a holdout is required,
refuse the contract instead of silently stealing a row. Print the actual
split sizes.

### CU-22 — `migrate` PASS, then `compare` FAIL on the same files

**Status:** fixed. PASS no longer claims holdout succeeded when it was
not scored. If holdout is skipped but some rows were still left out of
tuning, migrate gates on the full dataset before committing.

Live OpenAI classifier, vague prompt, `--generator llm`,
`holdout_required: false` after setting `tuning: 100%` (which still held
out one row — CU-21):

- `migrate` **PASS**, F1 0.667 → 1.000, edited `prompts/classifier.md`.
- Message: “migration passed tuning and holdout thresholds”.
- Result JSON: `"holdout": null`, `"n": 3` (shipping never scored).
- The committed prompt listed `'technical', 'app', 'billing', 'account'`
  — invented `app`, omitted `shipping`.
- Immediate `compare` on all 4 gold rows: target F1 **0.750**,
  `FAIL min_f1: 0.750 >= 0.9`. Shipping came back as
  `Category: technical`.

A user who trusts the PASS and opens a PR would ship a prompt that still
fails the contract on the full dataset.

**Where:** `src/driftless/engine.py` (PASS path + message);
`src/driftless/splits.py`; report table uses tuning metrics only.

**Fix:** Do not say holdout passed when `holdout` is null. Require every
gold class to appear in the scored split, or fail closed. After a PASS,
`compare` on the same files should not FAIL.

### CU-23 — BLOCKED scorecard hides the holdout failure

**Status:** fixed. BLOCKED/PARTIAL keep the last confirmation metrics.
The message is `tuning passed, holdout failed` when that is what
happened. The CLI table adds a Holdout (or Full dataset) column.

Same live harness, default 50/50 split, `holdout_required: true`:

- `compare` (full set): current 0.750, target 0.500, `FAIL min_f1`.
- `migrate --generator llm`: **BLOCKED**, 7 attempts, 0 accepted.
- Printed table: baseline / naive / final F1 all **1.000**.
- Result JSON: tuning was billing+account (already exact); holdout was
  shipping+technical (the failures). `"holdout": null`.

Candidates that also scored 1.000 on tuning were rejected because they
did not beat the current best and had a larger diff. The holdout that
actually blocked the run never appears in the CLI table or the result
`holdout` field.

**Where:** `src/driftless/engine.py` (blocked return omits holdout
metrics); `src/driftless/report.py`.

**Fix:** Always print holdout metrics when a holdout exists. Status
should say “tuning passed, holdout failed,” not “could not recover
quality” next to F1 1.000.

### CU-24 — LLM repair invents labels from predictions, not gold

**Status:** fixed. The repair prompt now includes `label_taxonomy` from
tuning rows plus the gold file, and the system prompt forbids inventing
or dropping classes.

On the live harness the only tuning failure was
`misclassification: technical -> app`. The repairer treated `app` as a
real category and wrote it into the prompt. Across both live runs it
also proposed `general`, `inquiry`, and `feedback`, and once dropped
the taxonomy to just `billing` + `account` (the two tuning classes).

Gold labels `billing` / `technical` / `account` / `shipping` are in
`evals/gold.jsonl` (readonly). The generator is told to preserve the
taxonomy, but it is not given the closed label set.

**Where:** `src/driftless/generators.py` (`LLMPatchGenerator` context).

**Fix:** Pass the distinct gold labels into the repair prompt as a
closed set. Reject candidates that introduce labels not in gold.

## Live GitHub artifacts (2026-08-15)

Throwaway repo:
https://github.com/alexminnaar/driftless-cold-user-pr-test

| Artifact | URL | Notes |
|---|---|---|
| Blocked issue | https://github.com/alexminnaar/driftless-cold-user-pr-test/issues/1 | Title, scorecard, unmet `min_f1`, “do not migrate” — looks right |
| Passing prompt PR | https://github.com/alexminnaar/driftless-cold-user-pr-test/pull/2 | Prompt diff + evidence look right; model ID not changed (CU-7) |
| Model-ID PR | https://github.com/alexminnaar/driftless-cold-user-pr-test/pull/3 | Merged. `config/llm.yml` is `gpt-4o`; `plan` still wants `gpt-4 → gpt-4o` (CU-11) |
| CI migrate (as generated) | https://github.com/alexminnaar/driftless-cold-user-pr-test/actions/runs/31906665929 | Failed: no API key, then `open-pr` had no result (CU-12) |
| CI migrate (fixture args) | https://github.com/alexminnaar/driftless-cold-user-pr-test/actions/runs/31906754734 | PASS; `open-pr` skipped already-open PR #2 |
| CI scan | https://github.com/alexminnaar/driftless-cold-user-pr-test/actions/runs/31906667729 | Success |
| CI label audit | https://github.com/alexminnaar/driftless-cold-user-pr-test/actions/runs/31906676938 | Success |

Commands used after `gh repo create`:

```bash
driftless validate -w support_classifier
driftless compare -w support_classifier --to gpt-4o-mini
driftless migrate -w support_classifier --to gpt-4o-mini --generator none
driftless open-pr -w support_classifier --create    # issue #1
driftless migrate -w support_classifier --to gpt-4o-mini --generator fixture
driftless open-pr -w support_classifier --create    # PR #2
```

## Verified working (do not re-open as bugs)

These matched the docs on 2026-08-15 / 0.3.4:

- `pip install driftless` from PyPI.
- Classifier / RAG / agent `validate`, `compare`, `--generator none` (BLOCKED,
  exit 1), `--generator fixture` (PASS).
- `report` and dry-run `open-pr` (issue when blocked, PR when passing).
- `open-pr --create` on a real GitHub repo: blocked path opens an issue,
  passing path opens a branch + commit + PR. See CU-7 through CU-10 for
  delivery-quality gaps.
- `configure incident_brief --apply` on the adoption fixture produced a
  loadable contract with no leftover placeholders.
- `validate` / `calibrate` / `compare` / `compare --enforce` / `migrate
  --generator none` / `init-ci` on that adopted contract.
- `--generator fixture` on a non-example workflow fails with a clear hint.
- `init` writes a scaffold and `validate` refuses unresolved `TODO` /
  `<placeholder>` values.
- `init-policy` + `plan` on the adoption fixture: no actionable triggers
  (expected; `gpt-4o` is active).
- `plan` on the classifier example (`gpt-4` is deprecated): deprecation
  trigger `gpt-4 -> gpt-4o`, naive passes, decision PR (critical).
- `plan --act --generator none`: dry-run “would open pr”.
- `plan --act --create`: deduped already-open PR #3.
- `migrate --to gpt-4o --generator none`: `MODEL_CHANGE_ONLY`; `open-pr
  --create` wrote `config/llm.yml` (CU-11).
- `audit-labels`: clean pass; planted duplicate + `--fail` exits 1 with a
  clear disagreement report.
- `refine --generator none` on unchanged labels: `NO_CHANGE`, exit 0.
- `--generator llm` with no key: clear error and hint (did not run a paid
  repair; no `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` in this environment).
- `init-ci` on the copy-example repo: scan, migrate, refine, label-audit
  workflows. Scan and label-audit succeeded on Actions.
- Merging PR #3 updates `config/llm.yml` only; `plan` / `validate` / `scan`
  still treat `gpt-4` as current (CU-11).
- `poll` records a first-seen baseline and stays quiet. Default
  `min_changed_rows: 5` ignores a 4-row label rewrite (CU-16). With the
  threshold set to 1, `poll` and `poll --act --generator none` run. A
  `data_source.command` fetch works.

- `run.endpoint`: local HTTP classify server — `validate`, `compare`
  (1.000 → 0.000), `migrate --generator fixture` (PASS), and
  `DRIFTLESS_ENDPOINT_TOKEN` on 401 all behaved as documented.
- `poll` `labels_url` fetched gold JSONL (same `[dim]` leak as CU-17).
- Legacy 0.2 `migration.allow_*` contract: `validate` rejects it with a
  pointer to `files.editable` (matches `docs/UPGRADING.md`).
- `copy-example nope` lists available examples. `--force` overwrites.
- `init-ci --plan` writes `driftless-plan-act.yml` (`plan --act --create`
  weekly).
- `validate` with two workflows in one contract runs both.
- `scripts/check_site_links.py` on the committed site: OK.

- Live `--generator llm` migrate (OpenAI): API calls succeed; bundled
  classifier stays **BLOCKED** after 7 attempts (CU-20).
- Live `judge-check` (OpenAI): scores 4 calibration rows; `--enforce`
  applies `max_mae` / `min_correlation` correctly.
- Live OpenAI harness (real `chat.completions.create`, exact-label
  parser): `validate` and `compare` work. `--generator llm` can PASS
  when it sees the failing rows — but the PASS did not hold up on
  `compare` (CU-21–CU-24; 21–23 now fixed in source).

`refine --generator llm` was not re-run; the classifier still ignores the
prompt for `gpt-4` (CU-13).

## Closed

- CU-7, CU-10, CU-11, CU-12 — GitHub delivery: contract model bump, PR URL,
  example config file, CI generator input / skip empty open-pr (source fix;
  not yet released on PyPI).
- CU-13, CU-16, CU-20, CU-24 — demo harness, poll gate, and repair taxonomy
  (source fix; not yet released on PyPI).
- CU-21, CU-22, CU-23 — split honesty and PASS/BLOCKED scorecards (source
  fix; not yet released on PyPI).
- CU-1, CU-2, CU-3, CU-4, CU-18, CU-19 — first-hour CLI: real workflow names
  after copy, scan → configure handoff, and clean `judge-check` errors
  (source fix; not yet released on PyPI).
- CU-5, CU-6, CU-8, CU-9, CU-14, CU-15, CU-17 — viewer bind error, help
  lede, draft PRs, close blocked issues, honest refine exits, Retires
  column, poll markup (source fix; not yet released on PyPI).
