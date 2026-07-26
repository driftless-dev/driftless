# Cost and Budget Guidance

Driftless runs your real workflow. That is the point, but it also means cost is
driven by the same things that make LLM evals expensive: records, models, repair
attempts, judge calls, retrieval/tool calls, and retries.

Use this guide before running `migrate`, `refine`, or judge-graded workflows on a
large eval set.

## What Drives Cost

| Driver | Why it matters |
|---|---|
| Eval rows | Every `compare` run evaluates baseline and target. |
| Repair iterations | `migrate` may run the target workflow once per candidate/iteration. |
| Candidate width | Multi-candidate generators multiply repair attempts. |
| Holdout split | Holdout protects quality, but it is another target-model eval. |
| Judge grading | `eval.judge` adds one judge call per output record per eval run. |
| RAG retrieval/generation | Retrieval plus generation can be more expensive than a single model call. |
| Agent tool loops | Tool calls, retries, and multi-step trajectories multiply runtime and cost. |
| Endpoint retries | Retry/backoff is safer operationally, but repeated calls still count. |

## Suggested Starting Budgets

These are starting points, not hard rules.

| Eval size | Good first run | Suggested contract settings |
|---|---|---|
| Tiny, <30 rows | Use for smoke tests and demos only. Do not trust pass/fail as launch evidence. | `max_iterations: 2-3`; keep `split_seed_count: 1`; expect confidence caveats. |
| Small, 30-100 rows | Good for first real workflow integration. | `max_iterations: 3-5`; tuning/holdout around `70%/30%`; use one repair candidate at a time. |
| Medium, 100-500 rows | Good default for product workflows. | `max_iterations: 4-6`; tuning/holdout around `60%/40%`; consider stricter thresholds. |
| Large, 500+ rows | Sample first, then expand after the loop proves useful. | Start with a sampled eval or lower `max_iterations`; run full holdout before PR creation. |

## Command Cost Shape

| Command | Typical cost shape |
|---|---|
| `validate` | One run of the current model, if `--run` is enabled. |
| `compare` | Current model once + target model once. |
| `migrate` | Baseline + naive target + repair candidates + holdout validation. |
| `refine` | Current model repeatedly while optimizing against changed eval data. |
| `judge-check` | One judge call per calibration row. |
| `plan` | Mostly catalog/policy work; may call compare/migrate when paired with `--act`. |

## Practical Defaults

For first adoption:

```yaml
migration:
  max_iterations: 3
  holdout_required: true
  split_seed_count: 1

eval:
  split:
    tuning: 60%
    holdout: 40%
```

For workflows where each record is expensive, start with:

```yaml
migration:
  max_iterations: 2
  holdout_required: true
```

Then increase iterations only after the first blocked/partial report shows the
repair loop is learning useful changes.

## RAG Workflows

Keep the retrieval index fixed for prompt/config migration. If the RAG pipeline
does expensive retrieval or reranking, start with a smaller eval sample and a
deterministic scorer (`score_field`) before adding an LLM judge.

Recommended sequence:

1. `validate` on the full eval.
2. `compare` on a representative sample.
3. `migrate` with low `max_iterations`.
4. Full holdout run before opening a PR.

## Agent Workflows

Keep first agent evals local or inside CI with fake/sandboxed tools. Emit trace
fields (`tools`, `tool_errors`, `steps`, `final`) and use a deterministic
`score_field` where possible.

Recommended sequence:

1. Verify the agent writes trace fields for every row.
2. Run `compare` before any repair attempt.
3. Use small `max_iterations` until tool-selection failures are clustered.
4. Add budgets before using judge scoring or multi-step live tools.

## Judge-Graded Workflows

Judge grading is powerful, but it doubles the trust problem: you are optimizing
toward another model.

Before `migrate` or `refine`:

```bash
driftless judge-check -w <workflow> --enforce
```

Use a calibration set that includes good outputs, bad outputs, unsupported
claims, format failures, and borderline cases.

## Reading Cost Rows

Driftless reports cost when your workflow emits `eval.cost_field`, or when it can
derive cost from token fields plus catalog pricing:

```yaml
eval:
  cost_field: cost
  # or:
  prompt_tokens_field: prompt_tokens
  completion_tokens_field: completion_tokens
```

Cost rows are evidence, not approval. A cheaper target still has to pass quality
thresholds.

