# driftless

**Poetry-style lock regeneration for prompts — delivered Dependabot-style.**

A prompt is pinned to a **model** and an **eval dataset** (like `pyproject.toml`
declares deps and `poetry.lock` pins what works). When either moves, the prompt
goes stale. driftless re-derives it through your real eval, validates on holdout,
and opens a PR with evidence.

> Also described as *Dependabot for LLM models* — same automation shape, different
> core insight: prompts are lockfiles, not just config files.

> Status: early development — [`0.1.0`](https://pypi.org/project/driftless/) on PyPI.

## Install (dev)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Quickstart

```bash
driftless init            # scaffold a driftless.yml
driftless init-policy     # scaffold .driftless/policy.yml
driftless init-ci         # scaffold GitHub Actions workflows
driftless validate -w support_classifier   # contract parses + harness runs
```

## How it works

You describe your model-dependent workflow once in `driftless.yml`: how to
run it, how to override the model, which files may be edited, and what quality
thresholds must hold. `driftless` orchestrates *your* workflow under
different models, compares results, repairs allowed files, validates on
holdout, and opens a PR with the evidence.

The customer owns the workflow. The tool orchestrates it.

Not a classifier? Choose a grading mode that fits the task — the same loop then
optimizes against it, with your team owning the definition of "good":

- **`eval.score_field` / `eval.pass_field`** — your command emits a numeric score
  or a pass/fail per record (works for any task: summarization, codegen, agents).
- **`eval.fields`** — structured extraction, scored per field with
  precision/recall/F1 against the gold record.
- **`eval.judge`** — an LLM judge grades each free-form output against a rubric
  (with an optional human-scored calibration set for a judge-agreement check).
  Run `driftless judge-check -w <workflow>` before optimizing; set
  `max_mae` / `min_correlation` in the contract to gate `migrate` / `compare`.

## CLI

| Command | Purpose |
|---|---|
| `init` | Scaffold a `driftless.yml`. |
| `init-policy` | Scaffold a `.driftless/policy.yml` (when to migrate). |
| `init-ci` | Scaffold `.github/workflows/` for scan, migrate, refine, and poll. |
| `scan` | Find probable LLM usage and at-risk models. |
| `plan` | Discover at-risk workflows and apply the migration policy (CI triage). |
| `plan --act` | Migrate + open a PR/issue for every actionable trigger (close the loop). |
| `configure <workflow>` | Turn a detected workflow into a migration-ready contract. |
| `calibrate -w <w>` | Measure the baseline and suggest starting thresholds. |
| `compare -w <w> --to <model>` | Baseline vs target scorecard. |
| `migrate -w <w> --to <model>` | Repair + validate + produce migrated files. |
| | `--strict-label-audit` warns/blocks on duplicate-label conflicts. |
| `refine -w <w>` | Re-optimize the prompt for a changed eval dataset (model pinned). |
| `poll [--act]` | Detect external eval-dataset changes and refine on a meaningful change. |
| `validate -w <w>` | Check the contract parses and the harness runs. |
| `judge-check -w <w>` | Measure judge↔human agreement on a calibration set (`--enforce` to gate). |
| `audit-labels -w <w>` | Find duplicate inputs with disagreeing gold labels (`--fail` for CI). |
| `report` | Render the latest migration report. |
| `view` | Open the optimization run viewer (charts + attempt log). |
| `open-pr -w <w>` | Open a PR (or issue) from the latest migration result. |

## Configuring *when* to migrate

`plan` reads an optional `.driftless/policy.yml` — the "dependabot.yml" layer.
Scaffold it with `driftless init-policy`; every field matches a default, so an
empty file behaves like no file. It controls which triggers are enabled
(`deprecation` is on and forced; `cost`/`quality`/`new_model` are opportunistic),
the thresholds a candidate must clear (`min_savings_pct`, `min_gain`), a
`cooldown_days` to skip freshly-released models, candidate `allow`/`deny` globs,
and an `ignore` list to snooze specific models or moves. The engine still decides
whether a candidate actually passes *your* eval — policy only decides whether to
propose it.

## GitHub-native usage

A composite GitHub Action (`action.yml`) wraps the CLI so scans and migrations
can run in CI. See `.github/workflows/` for a scheduled deprecation scan and a
manually-triggered migration that opens a PR (or an issue when blocked).

```yaml
- uses: driftless-dev/driftless@v0.2.3
  with:
    command: scan
```

## Documentation

- [Release process](./docs/RELEASE.md) — changelog, tagging, GitHub Releases, PyPI.
- [Changelog](./CHANGELOG.md) — version history.
- [Repair prompts & custom generators](./docs/repair-and-generators.md) — customize
  the LLM repair prompt or plug in your own patch generator.
- [Run viewer](./site/runs.html) — inspect optimization attempts, metrics, and diffs.
