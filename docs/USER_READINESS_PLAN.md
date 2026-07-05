# User Readiness Plan

Driftless is ready to show to design partners and technical early adopters. It
is not yet ready to be treated as fully self-serve for users arriving cold from a
README, package page, or blog post.

This plan tracks the missing pieces between "impressive prototype/product alpha"
and "a new user can understand the value, try it, and know what to do next."

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
- CLI covers local and CI workflows: `validate`, `compare`, `migrate`, `refine`,
  `plan`, `open-pr`, `init-ci`.
- Examples now cover classification, RAG, tool agents, judge-grading outlines,
  cost, label audit, and CI automation.
- Tests cover the RAG and agent example fixtures.

Recently improved:

- README now starts with a bundled `rag-qa` quickstart via
  `driftless copy-example`.
- [`docs/GETTING_STARTED.md`](./GETTING_STARTED.md) walks through bundled RAG
  and agent examples.
- [`docs/COMMAND_CHOOSER.md`](./COMMAND_CHOOSER.md) maps user intent to CLI
  commands.
- [`docs/LIMITS.md`](./LIMITS.md) collects the main launch boundaries in one
  user-facing page.

Still not fully self-serve:

- Screenshots are missing for the scorecard, report, run viewer, and PR body.
- There is a saved blocked-review fixture, but not yet a canonical public PR
  showing successful prompt/config diffs.

## P0 Before Wider Launch

### 1. Golden quickstart

Status: implemented in [`docs/GETTING_STARTED.md`](./GETTING_STARTED.md) and the
README via `driftless copy-example`.

Create a short "Try Driftless in 5 minutes" path using a bundled fixture.
Recommended fixture: `examples/rag-qa`, because it demonstrates non-classifier
scoring, cost, and prompt/config-only migration scope without provider keys.

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

Status: still open.

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

## P1 Shortly After

### 5. One complete example PR

Status: partially implemented via
[`docs/EXAMPLE_REVIEW_ARTIFACT.md`](./EXAMPLE_REVIEW_ARTIFACT.md), which captures
the blocked issue/report path. A successful PR with prompt/config diffs is still
open.

Create or capture a canonical evidence-backed PR.

Acceptance criteria:

- Public PR or saved fixture shows prompt/config diff, scorecard, thresholds,
  report body, and reviewer instructions.
- README and blog posts link to it.

### 6. Release/version polish

Status: implemented. Version references are aligned to the `0.2.15` release
line, and `scripts/release-check.sh` verifies that `action.yml` matches
`src/driftless/__init__.py`.

Make version references boringly consistent.

Acceptance criteria:

- README, site docs, blog drafts, and Action examples all reference the current
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

## P2 Product Confidence

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

These do not block showing the project to early users:

- Hosted dashboard.
- Hosted catalog service.
- GitHub App/bot.
- Embedding-model migration.
- Full agent sandboxing, as long as examples and CI usage stay local and
  side-effect-free.
- Statistical significance reporting.

## Suggested Order

1. Golden quickstart.
2. Command chooser.
3. Known limits page.
4. Screenshots for README/blog.
5. One complete example PR.
6. Version polish and full launch check.
