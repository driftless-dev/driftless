# Command Chooser

Use this when you know what you want to do, but not which Driftless command
to run.

If you just installed Driftless, start with
`copy-example support-classifier` and the
[getting started](./GETTING_STARTED.md) walkthrough. You do not need an API key
for that path.

`-w` is `--workflow` (the name in `driftless.yml`). `open-pr` is a dry run
unless you pass `--create`.

## Setup and Discovery

| User situation | Command | Important behavior |
|---|---|---|
| Show the installed release or command help. | `driftless --version`, `driftless --help`, or `driftless <command> --help` | Help is the authoritative option list for the installed wheel. |
| Try the golden-path bundled example. | `driftless copy-example support-classifier --out-dir <dir>` | Also accepts `rag-qa` and `tool-agent`; `--force` overwrites an existing destination. |
| Scaffold a neutral contract manually. | `driftless init [--path driftless.yml]` | Contains explicit placeholders and refuses to run until they are resolved. |
| Find probable LLM usage and lifecycle risk. | `driftless scan [path]` | Use `--no-files` for a shorter result. Discovery does not edit the repo. |
| Turn a detected workflow into a contract. | `driftless configure <workflow> [path] --apply` | Always writes a reviewable draft; `--apply` safely creates/appends root `driftless.yml`. |
| Scaffold migration-trigger policy. | `driftless init-policy` | Writes `.driftless/policy.yml`; use `--path` or `--force` when needed. |
| Generate GitHub Actions after local validation. | `driftless init-ci --setup-command '<install command>'` | Review generated files before committing. Refinement is manual unless `--refine-on-push` is explicit. |

## Validate, Measure, and Repair

| User situation | Command | Important behavior |
|---|---|---|
| Check parsing and run the harness. | `driftless validate -w <workflow>` | Omit `-w` for all workflows; `--no-run` checks configuration without executing the harness. |
| Establish a baseline and starting thresholds. | `driftless calibrate -w <workflow>` | `--margin` adjusts suggested headroom. Suggestions still require human review. |
| Measure a target before editing files. | `driftless compare -w <workflow> --to <model> [--enforce]` | Default is informational; `--enforce` exits non-zero when gates fail. |
| Repair exact editable paths for a model switch. | `driftless migrate -w <workflow> --to <model>` | Default `--generator llm` needs provider credentials. `--generator none` makes no repair. `--generator fixture` reproduces the known-good bundled-example patch without keys. |
| Re-optimize after eval data changes with the model pinned. | `driftless refine -w <workflow>` | Same repair/cost caveats as `migrate`, but no `--to` model. |
| Check classification labels before optimization. | `driftless audit-labels -w <workflow>` | `--fail` exits non-zero on conflicts; tune near-duplicate matching with `--near-threshold`. |
| Check an LLM judge against human calibration. | `driftless judge-check -w <workflow>` | `--enforce` exits non-zero when configured MAE/correlation gates fail. |

## Automation and Data Changes

| User situation | Command | Important behavior |
|---|---|---|
| Preview policy-triggered work. | `driftless plan` | Reads `.driftless/policy.yml`; `--no-opportunistic` limits optional cost/quality/new-model proposals. |
| Execute policy decisions. | `driftless plan --act` | Migration/refine runs may require provider credentials. GitHub operations remain previews unless `--create` is added. |
| Detect external eval-dataset changes. | `driftless poll` | Fetches configured external data by default; use `--no-fetch` to compare local state only. The default gate is 5 changed rows, or the full dataset if it is smaller. |
| Refine after meaningful external data changes. | `driftless poll --act` | May incur repair cost; add `--create` only when PR/issue side effects are intended. |

## Evidence and Delivery

| User situation | Command | Important behavior |
|---|---|---|
| Render saved migration reports. | `driftless report [-w <workflow>]` | `--raw` prints markdown rather than rich terminal rendering. |
| Inspect charts, attempts, and diffs locally. | `driftless view [-w <workflow>]` | Uses port `8777` by default; `--port` changes it and `--no-open` suppresses browser launch. |
| Preview a PR or issue. | `driftless open-pr -w <workflow>` | Dry run by default; inspect the evidence and diff before creating anything. |
| Create the PR or issue. | `driftless open-pr -w <workflow> --create` | Requires git/GitHub access. Use `--no-push` or `--no-dedupe` only when you understand the delivery implications. |

## Rule of Thumb

- Use `validate` when setup is the question.
- Use `compare` when safety of a target model is the question.
- Use `migrate` when you want Driftless to produce prompt/config changes.
- Use `refine` when labels or eval data changed but the model did not.
- Use `plan` when CI should decide what work exists.
- Use `poll` when the eval dataset is external rather than changed in git.
- Use `report`/`view` to review evidence; use `open-pr` only for delivery.

## Key-Free Product Tour

```bash
pip install driftless
driftless copy-example support-classifier --out-dir driftless-classifier-demo
cd driftless-classifier-demo
driftless validate -w support_classifier
driftless compare -w support_classifier --to gpt-4o-mini
```

The classifier intentionally changes from F1 `1.000` to `0.000` while cost
falls from `0.024` to `0.004`, so `min_f1` fails. Exercise the blocked path
without provider keys:

```bash
driftless migrate -w support_classifier --to gpt-4o-mini --generator none
driftless report -w support_classifier
driftless open-pr -w support_classifier
```

The migration is expected to exit non-zero. The final command is a dry run by
default.

To reproduce a passing bundled repair without keys:

```bash
driftless migrate -w support_classifier --to gpt-4o-mini --generator fixture
```

For an existing repository, use `driftless scan`, then
`driftless configure <workflow> --apply`. Review the inferred contract and
complete any remaining placeholders before `validate`, `compare`, or
`init-ci`.

