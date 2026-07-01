"""Scaffolding templates for `driftless init`."""

from __future__ import annotations

CONTRACT_TEMPLATE = """\
# driftless contract
# Docs: describe each model-dependent workflow once, then let driftless
# orchestrate it under different models.
version: 1

workflows:
  support_classifier:
    description: "Routes support tickets into billing, technical, account, or refund categories."

    # How to run the REAL workflow. driftless runs your command; it does not
    # reimplement your preprocessing/parsing/postprocessing.
    run:
      command: npm run eval:support-classifier
      input_path: evals/support_classifier.inputs.jsonl
      output_path: .driftless/results/support_classifier.outputs.jsonl
      # Prefer a CLI command. Alternatively, point at an HTTP endpoint that
      # classifies one input record per POST (mutually exclusive with command):
      #   endpoint: https://internal.example.com/classify
      #   model_param: model   # request-body key the model id is injected under
      # The JSON response per record is written as the output record. Set
      # DRIFTLESS_ENDPOINT_TOKEN to send an Authorization: Bearer header.

    # Which model is used and how to override it (env_var is the common case).
    model:
      provider: openai
      env_var: SUPPORT_CLASSIFIER_MODEL
      current: gpt-4o-mini
      target_candidates:
        - gpt-5-mini
        - gpt-5-nano
      # Set true if your code routes models provider-agnostically (LiteLLM /
      # OpenRouter / a gateway), so cross-provider targets are safe.
      # portable: false

    # Edit scope. The migration engine may ONLY touch editable files.
    files:
      editable:
        - prompts/support_classifier.md
        - prompts/support_classifier_examples.yml
      readonly:
        - src/classifySupportTicket.ts
        - schemas/support_classifier.schema.json
      # Read-only code shown to the optimizer for CONTEXT (e.g. the output
      # parser), so it writes patches that conform to how outputs are graded.
      # context:
      #   - src/parseSupportClassifierOutput.ts

    eval:
      labels_path: evals/support_classifier.labels.jsonl
      schema_path: schemas/support_classifier.schema.json
      split:
        tuning: 70%
        holdout: 30%
      # Cost tracking (enables max_cost_increase). Prefer an explicit per-record
      # cost field; otherwise emit token counts and cost is derived from the
      # built-in model price catalog.
      # cost_field: cost_usd
      # prompt_tokens_field: prompt_tokens
      # completion_tokens_field: completion_tokens
      #
      # Not a classifier? Pick ONE grading mode below instead of label_field
      # (works for any task -- summarization, codegen, extraction, RAG, agents):
      #
      # 1) Customer-supplied grade -- your command emits its own per-record grade
      #    (then gate with thresholds.min_score):
      # score_field: quality      # numeric per-record score -> mean score
      # pass_field: passed        # boolean per-record pass/fail -> pass-rate
      #
      # 2) Structured extraction -- per-field precision/recall/F1 vs. the gold
      #    record (needs id_field + labels_path; gated by thresholds.min_f1):
      # fields: [name, amount, due_date]
      #
      # 3) LLM-as-judge (free-form) -- a model grades each output against a rubric;
      #    mean score is gated by thresholds.min_score:
      # judge:
      #   rubric: |
      #     Award full marks if the summary is faithful and concise.
      #   scale_max: 5            # rubric is 1..5; normalized to 0..1
      #   # pass_threshold: 0.6   # optional: a row "passes" at >= this (0..1)
      #   # input_field: text     # optional: which input field to show the judge
      #   # output_field: summary # optional: judge a field of JSON output (else raw text)
      #   # calibration_path: evals/judge_calibration.jsonl  # human scores -> agreement check
      #   # max_mae: 0.15          # optional gate: refuse run when judge MAE exceeds this (0..1)
      #   # min_correlation: 0.80  # optional gate: refuse run when Pearson r is below this
      #
      # Eval dataset lives OUTSIDE the repo? Let `driftless poll` refresh it on a
      # schedule before checking for changes (in-repo data needs none of this --
      # git is the change detector). DRIFTLESS_DATASOURCE_TOKEN -> Bearer auth.
      # data_source:
      #   command: "python scripts/pull_labels.py"   # your script writes the files
      #   # inputs_url: https://store.example.com/inputs.jsonl   # or a plain GET
      #   # labels_url: https://store.example.com/labels.jsonl

    # Thresholds are OPTIONAL. With none set, the bar is "don't regress vs. the
    # current baseline" (run `driftless calibrate -w <name>` for suggestions).
    thresholds:
      min_f1: 0.91
      min_precision: 0.94
      # min_score: 0.9          # for eval.score_field / eval.pass_field grading
      max_schema_error_rate: 0.01
      max_cost_increase: 0
      max_latency_increase: 0.10
      # regression_tolerance: 0.02  # band used when no absolute bar is set

    migration:
      allow_prompt_edits: true
      allow_example_edits: true
      allow_config_edits: true
      allow_schema_edits: false
      allow_business_logic_edits: false
      max_iterations: 8
      holdout_required: true

    # Optional: customize how the LLM repair generator is prompted.
    # repair:
    #   guidance: |
    #     Refund tickets must never be labeled "billing".
    #     Keep the JSON on a single line.
    #   # system_prompt: "Full replacement system prompt..."
    #   # system_prompt_path: prompts/repair_system.md
    #   # user_template_path: prompts/repair_user.md   # supports {{failure_clusters}}, {{editable_files}}, etc.
"""


POLICY_TEMPLATE = """\
# driftless policy -- the "dependabot.yml" layer: *when* should a migration be
# proposed, and *how loudly*? Lives at .driftless/policy.yml. Every field here
# matches a default, so an empty file behaves exactly like no file. `plan` reads
# this; the engine still decides whether a candidate actually passes your eval.

# Forced trigger: a model on its way out. Always surfaces something (a passing
# migration -> PR, a blocked one -> issue) because there's a deadline.
deprecation:
  enabled: true
  warn_before_days: 90   # start surfacing this many days before retirement (null = always)
  action: pr

# Opportunistic triggers: only open a PR when the candidate passes your eval AND
# materially wins. Off or conservative by default to keep the bot quiet.
cost:
  enabled: true
  min_savings_pct: 0.20    # require >= 20% cheaper
  max_quality_drop: 0.01   # tolerate <= 1 F1 point of regression
  action: pr

quality:
  enabled: false           # opt-in: quality-chasing is noisier
  min_gain: 0.02           # require >= 2 F1 points of improvement
  action: pr

new_model:
  enabled: false           # "newer" alone isn't a reason; must also win on cost/quality
  min_savings_pct: 0.0
  min_gain: 0.0
  action: pr

# Dataset-drift trigger for the external-data `poll` -> refine. Don't fire on
# whitespace/reordering or a row or two; require a substantive change, and
# debounce continuous feedback ingestion.
data_change:
  enabled: true
  min_changed_rows: 5        # fire at >= this many added/removed/changed rows (1 = any)
  min_changed_fraction: 0.0  # ...or this fraction of the dataset (0 = off)
  min_days_between: null      # debounce: don't re-fire within N days (null = off)
  action: pr

# Don't chase models released within this many days (let them stabilize). Forced
# deprecation triggers ignore this. null = off.
cooldown_days: 14

# Candidate allow/deny globs (matched against the candidate model id).
candidates:
  allow: ["*"]
  deny: ["*-preview", "*-exp*", "*-alpha*"]

# Snooze specific candidates or moves (globs): a model id ("gpt-4o*") or a
# "current->candidate" pair ("gpt-4o-mini->gpt-4o").
ignore: []
"""
