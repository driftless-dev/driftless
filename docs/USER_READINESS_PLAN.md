# User Readiness Plan

Driftless is a public alpha for design partners and technical early adopters.
The package, Action, hosted site, genuine captures, and key-free tour make the
first evaluation self-serve. Existing-repository adoption is documented
end-to-end. Users bringing an arbitrary workflow still own the reliability of
its eval, model override, thresholds, credentials, and budget — that is the
product, not a missing wizard. See [`GA.md`](./GA.md).

This plan records completed readiness work and the remaining boundaries between
public alpha and "a new user can understand the value, integrate a real
workflow, and operate it safely without project-specific help."

## Readiness Goal

A new user with an existing LLM eval should be able to answer four questions in
under ten minutes:

1. What problem does Driftless solve?
2. Which command should I run first?
3. What does a passing or failing result mean?
4. What are the limits and risks before I wire this into CI?

## Current State

Strong enough to show:

- Clear core value prop: run the real eval, repair allowed prompt/config files,
  validate on holdout, and open evidence-backed PRs.
- Published package and composite GitHub Action.
- Hosted GitHub Pages landing, docs, blog, and run viewer, backed by the
  committed site and deployment workflow.
- CLI covers local and CI workflows: `validate`, `compare`, `migrate`, `refine`,
  `plan`, `open-pr`, `init-ci`.
- Examples now cover classification, RAG, tool agents, judge-grading outlines,
  cost, label audit, and CI automation.
- Tests cover the classification, RAG, and agent example fixtures.

Recently improved:

- README now starts with a bundled `support-classifier` quickstart via
  `driftless copy-example`.
- [`docs/GETTING_STARTED.md`](./GETTING_STARTED.md) walks through bundled
  classification, RAG, and agent examples.
- [`docs/COMMAND_CHOOSER.md`](./COMMAND_CHOOSER.md) maps user intent to CLI
  commands.
- [`docs/LIMITS.md`](./LIMITS.md) collects the main launch boundaries in one
  user-facing page.
- Hosted docs now summarize the command chooser, known limits, provider-cost
  budgets, and upgrade path instead of requiring a GitHub-doc detour.
- `configure --apply` keeps the reviewable
  `.driftless/configure/<workflow>.yml` draft while safely creating or appending
  root `driftless.yml`; unresolved placeholders block execution.

Still not a hosted product:

- There is no hosted bot or onboarding wizard; users review `init-ci` output and
  manage provider credentials, permissions, and budget in their own CI. That is
  the supported surface, documented in [`GA.md`](./GA.md).
- Existing-repository adoption still requires a reliable eval command, model
  override, editable-file scope, labels/scorer, and thresholds. Those are
  customer-owned by design; the
  [adoption checklist](./GETTING_STARTED.md#adopt-driftless-in-an-existing-repository)
  makes each item explicit.
- More cold-user feedback is still useful across repositories whose harnesses
  differ from the bundled classifier, RAG, and tool-agent examples.

Closed since the previous readiness pass:

- Bundled examples can reproduce a **passing** migration with
  `--generator fixture` (no provider keys). PR #4 remains historical proof of a
  larger testbed run; it is no longer the only success artifact.

## Completed Readiness Foundations

### 1. Golden quickstart

Status: implemented in [`docs/GETTING_STARTED.md`](./GETTING_STARTED.md) and the
README via `driftless copy-example`.

Create a short "Try Driftless in 5 minutes" path using the bundled
`support-classifier` fixture. It demonstrates deterministic quality and cost
gates, then continues through a key-free blocked migration.

Acceptance criteria:

- README has a top-level quickstart that installs Driftless and runs:
  `validate`, `compare`, and `report` or `view` on a bundled example.
- The expected output is shown in abbreviated form.
- The quickstart explains why the target fails and what command comes next.
- The path works from an sdist/wheel install, not only editable checkout.

### 2. Command chooser

Status: implemented in [`docs/COMMAND_CHOOSER.md`](./COMMAND_CHOOSER.md).

Add a compact guide that maps user intent to commands.

Acceptance criteria:

| User situation | Command |
|---|---|
| "Does my contract run?" | `driftless validate -w <workflow>` |
| "Can I switch models safely?" | `driftless compare -w <workflow> --to <model>` |
| "Repair prompts/config for a model switch." | `driftless migrate -w <workflow> --to <model>` |
| "Eval data changed, model stayed fixed." | `driftless refine -w <workflow>` |
| "What should CI do this week?" | `driftless plan` |
| "Open the PR/issue from the latest run." | `driftless open-pr -w <workflow>` |

### 3. Screenshots and visual proof

Status: implemented via [`docs/VISUAL_PROOF_PLAN.md`](./VISUAL_PROOF_PLAN.md).
Genuine PNG captures cover the executed comparison, public successful PR and
files-changed view, and run viewer.

Capture the product surfaces that make the value obvious.

Acceptance criteria:

- Scorecard screenshot from `compare`.
- Migration/report screenshot or markdown excerpt.
- Run viewer screenshot.
- GitHub PR/issue body screenshot from a dry-run or testbed run.
- Blog posts 1, 3, 7, and 8 include at least one relevant visual.

### 4. Known limits page

Status: implemented in [`docs/LIMITS.md`](./LIMITS.md).

Create one user-facing page that says what Driftless does not do yet.

Acceptance criteria:

- Hosted GitHub App/bot is not available; composite Action is the current path.
- Embedding-model migration and index rebuilds are out of scope.
- Agent examples should use local/CI fake or sandboxed tools; hosted arbitrary
  tool execution needs sandboxing first.
- Provider catalog is bundled/refreshable, not a hosted live service.
- LLM repair and judge modes may need provider keys and can incur cost.
- Small eval sets can be noisy; use holdout/multi-split guidance where possible.

## Completed Follow-Through

### 5. One complete example PR

Status: implemented via separate public and bundled artifacts:
[`docs/EXAMPLE_REVIEW_ARTIFACT.md`](./EXAMPLE_REVIEW_ARTIFACT.md) captures the
blocked issue/report path, and
[`docs/EXAMPLE_SUCCESS_PR.md`](./EXAMPLE_SUCCESS_PR.md) captures the successful
paths: public testbed PR #4 and a different bundled four-row saved fixture with
prompt diff, scorecard, thresholds, report body, and reviewer instructions.

Create or capture a canonical evidence-backed PR.

Acceptance criteria:

- Public PR or saved fixture shows prompt/config diff, scorecard, thresholds,
  report body, and reviewer instructions.
- README and blog posts link to it.

### 6. Release/version polish

Status: implemented locally for the current `0.3.x` line. Publication is
not complete until the matching GitHub tag and PyPI wheel exist;
`scripts/release-check.sh --remote` verifies both in addition to local version
alignment.

Make version references boringly consistent.

Acceptance criteria:

- README, site docs, published guides, and Action examples all reference the current
  release line.
- `action.yml` default `version` matches `src/driftless/__init__.py`.
- Release notes call out RAG and agent examples.

### 7. First-run diagnostics

Status: implemented. Successful `validate` prints likely next commands;
command-not-found, missing-output, missing-model-override, missing-label,
endpoint auth/rate-limit, invalid JSONL, and provider-key failures include
targeted hints.

Improve the errors a cold user is most likely to hit.

Acceptance criteria:

- Missing output file, missing model override, invalid JSONL, missing labels, and
  provider key failures each produce a short hint.
- `validate` points to the next likely command when it succeeds.
- Example docs include "if this fails" notes for common local environment issues.

## Product Confidence Checks

### 8. Full-suite launch check

Status: implemented in [`docs/LAUNCH_CHECK.md`](./LAUNCH_CHECK.md).

Before a broad public push, run the complete local and CI checks.

Acceptance criteria:

- `mypy`
- `pytest`
- `python -m build`
- `twine check dist/*`
- Example `validate`/`compare` commands for classification, RAG, and agent
  fixtures.

### 9. Cost and budget guidance

Status: implemented in [`docs/COST_AND_BUDGETS.md`](./COST_AND_BUDGETS.md).

Document practical guardrails for expensive workflows.

Acceptance criteria:

- Explain eval size, tuning/holdout split, repair iterations, and judge calls as
  cost drivers.
- Add recommended defaults for small, medium, and large evals.
- Call out agent/RAG workflows as higher-cost due to retrieval/tool/judge calls.

## Not Blocking Design Partners

These are out of scope for the CLI/Action product, not leftover 1.0 work:

- Hosted dashboard.
- Hosted catalog service.
- GitHub App/bot.
- Embedding-model migration.
- Full agent sandboxing, as long as examples and CI usage stay local and
  side-effect-free.

Statistical significance reporting is also out of scope; use
[`CONFIDENCE.md`](./CONFIDENCE.md) and `migration.split_seed_count` instead.

## Ongoing Maintenance

Keep generated blog HTML fresh in CI, run the static site link check, and label
future captures with their fixture, dataset size, and reproduction requirements.

Cold-user CLI friction from walking the published docs is tracked in
[`COLD_USER_ISSUES.md`](./COLD_USER_ISSUES.md).
