# Known Limits

Driftless is ready for local use, CI use, and design-partner feedback. These are
the boundaries to understand before broad rollout.

## No Hosted Bot Yet

The current GitHub-native path is the composite Action plus `init-ci` generated
workflows. There is no hosted GitHub App that schedules and runs migrations for
you.

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
repo tooling. Driftless does not yet use a hosted always-fresh catalog service.

## LLM Repair and Judge Modes Can Cost Money

`validate` and `compare` run your workflow. `migrate`, LLM repair generation, and
`eval.judge` may call provider APIs depending on your config. Use small tuning
sets, holdout splits, and clear iteration limits before trying large workflows.

## Small Evals Are Noisy

If your eval set is tiny, a passing result can be split noise. Prefer meaningful
holdouts, enough examples per class or scenario, and multi-split/seed guidance
for high-risk changes.

## The Customer Owns "Good"

Driftless orchestrates the loop. Your workflow defines the scorer, labels,
judge rubric, cost fields, parser, and release thresholds.

