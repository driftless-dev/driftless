# Known Limits

Driftless is a command-line tool plus a GitHub Action that you run in a
repository you control. These are the supported-surface boundaries, not a list
of unfinished hosted products. See [`GA.md`](./GA.md) for what 1.0 will and will
not include.

**Holdout** means eval rows kept back for a final check. The repair loop does
not tune on them.

## Supported surface: CLI + customer CI

The GitHub-native path is the composite Action plus `init-ci` generated
workflows. There is no hosted GitHub App that schedules and runs migrations for
you. That is out of scope for this product line: Driftless executes
`run.command` from your contract, so execution stays in infrastructure you
review and sandbox.

## Embedding Migration Is Out of Scope

RAG examples keep the retrieval index fixed. Driftless can repair answer prompts,
retrieval rewrite prompts, routing prompts, and config files you mark editable.
It does not re-embed documents or rebuild vector indexes.

## Agent Tools Should Be Local or Sandboxed

The tool-agent example uses fake local tools over fixture data. Hosted execution
of arbitrary side-effecting tools needs sandboxing first. For now, run agent
evals locally or in your own CI environment where you control secrets and side
effects.

## Provider Data Is Bundled or Refreshed by CI

The model lifecycle/catalog data ships with the package and can be refreshed by
repo tooling. Driftless does not use a hosted always-fresh catalog service.

## LLM Repair and Judge Modes Can Cost Money

`validate` and `compare` run your workflow. `migrate`, LLM repair generation, and
`eval.judge` may call provider APIs depending on your config. Use small tuning
sets, holdout splits, and clear iteration limits before trying large workflows.

`--generator fixture` is a key-free reproduction aid for bundled examples only.
It is not a substitute for `--generator llm` on a customer workflow.

## Small Evals Are Noisy

If your eval set is tiny, a passing result can be split noise. Prefer meaningful
holdouts, enough examples per class or scenario, and multi-split/seed guidance
for high-risk changes. See [`CONFIDENCE.md`](./CONFIDENCE.md).

## The Customer Owns "Good"

Driftless orchestrates the loop. Your workflow defines the scorer, labels,
judge rubric, cost fields, parser, and release thresholds. Adoption in an
existing repository is self-serve once those pieces exist; Driftless will not
invent a reliable eval for you. Follow the checklist in
[`GETTING_STARTED.md`](./GETTING_STARTED.md#adopt-driftless-in-an-existing-repository).
