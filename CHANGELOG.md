# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Fixed

### Removed

---

## [0.2.14] - 2026-07-01

### Added

- **P1.1 Google/Gemini catalog refresh** — `fetch_provider_models`,
  `fetch_provider_pricing`, and `fetch_provider_deprecations` now support
  `google` via the Gemini `/models` API (`GEMINI_API_KEY` or `GOOGLE_API_KEY`);
  the scheduled `refresh-catalog.yml` job merges Google discoveries alongside
  OpenAI and Anthropic.

---

## [0.2.13] - 2026-07-01

### Added

- **P1.1 catalog deprecation refresh** — `tools/fetch_provider_deprecations.py`
  scrapes provider deprecation pages and diffs `/models` listings to suggest
  lifecycle updates for existing catalog entries; the scheduled
  `refresh-catalog.yml` job merges these alongside model discoveries and pricing.

### Changed

- **`llm-plan-act.yml`** — scheduled runs stay dry-run; manual dispatch can opt
  in to `--create` for real PRs/issues.

---

## [0.2.12] - 2026-07-01

### Changed

- **P6.1 init-ci label audit hardening** — scaffolds `audit-labels --fail` before
  migrate/refine steps and passes `--strict-label-audit` to those commands; dogfood
  workflows updated to match.

---

## [0.2.11] - 2026-07-01

### Added

- **P1.1 catalog pricing refresh** — `tools/fetch_provider_pricing.py` pulls
  USD/1M token prices from LiteLLM's public table (or a JSON overlay) and
  emits pricing-only updates for existing catalog models; the scheduled
  `refresh-catalog.yml` job merges pricing alongside model discoveries.

---

## [0.2.10] - 2026-07-01

### Added

- **P5.2 endpoint retry/backoff** — `run.endpoint_retries` (0–10) and
  `run.endpoint_retry_backoff_seconds` retry transient HTTP (429/502/503/504)
  and network errors with exponential backoff per input record.

---

## [0.2.9] - 2026-07-01

### Added

- **P5.2 endpoint concurrency** — optional `run.endpoint_concurrency` (1–32,
  default 1) runs endpoint POSTs in parallel via `ThreadPoolExecutor`; output
  line order always matches the input file.

---

## [0.2.8] - 2026-07-01

### Added

- **P1.1 provider model discovery** — `tools/fetch_provider_models.py` queries
  OpenAI and Anthropic `/models` APIs and emits new catalog entries only (never
  overwrites lifecycle on existing ids). The scheduled `refresh-catalog.yml`
  job merges discoveries when API keys are configured.

---

## [0.2.7] - 2026-07-01

### Added

- **P0.3 per-class support floors** — warn when any class has fewer than five gold
  examples on a split (`assess_class_support`); surfaced on `migrate` (tuning +
  holdout), `compare` (baseline + target), CLI "Confidence caveats", and saved
  compare JSON.

---

## [0.2.6] - 2026-07-01

### Added

- **P0.3 multi-seed tuning selection** — optional `migration.split_seed_count`
  (1–5) averages tuning-split metrics across shuffle seeds when scoring repair
  candidates; holdout validation still uses the primary `--seed` only.

---

## [0.2.5] - 2026-07-01

### Added

- **`init-ci` label-audit workflow** — scaffold `driftless-label-audit.yml` (or
  `-all` matrix) with `audit-labels --fail` on eval dataset path changes.
- **`init-ci` judge-check workflow** — scaffold `driftless-judge-check.yml` when
  `eval.judge.calibration_path` is set; uses `--enforce` when gate thresholds
  are configured.

---

## [0.2.4] - 2026-07-01

### Fixed

- **`judge-check` gate output under CI** — emit gate status via plain stdout so Rich
  TTY highlighting (when `GITHUB_ACTIONS=true`) does not break publish workflow tests.

---

## [0.2.3] - 2026-07-01

### Fixed

- **`judge-check` gate output** — print gate status with Rich markup disabled so
  publish CI can assert on `max_mae` / `min_correlation` lines reliably.

---

## [0.2.2] - 2026-07-01

### Added

- **`driftless judge-check`** — measure judge↔human agreement on a calibration set;
  `--enforce` applies the same gates as `migrate` / `compare`.
- **`driftless audit-labels`** — find duplicate/near-duplicate inputs with disagreeing
  gold labels; `--fail` for CI.
- **Judge trust hardening** — optional `max_mae` / `min_correlation` gates on
  judge-graded workflows; judge reliability and scoring evidence in migration reports.
- **P0.1 expansion** — judge-graded regression scenario; live eval CI baseline
  checks with `--require-all` and job summaries.
- **`open-pr --create` integration tests** — mocked git/gh execution path coverage.
- **`migrate` / `refine` label-audit preflight** — warn on label conflicts by default;
  `--strict-label-audit` blocks; `--skip-label-audit` to silence.

### Changed

- Live eval workflow sets `DRIFTLESS_REGRESSION_METRICS` explicitly.

---

## [0.2.1] - 2026-07-01

### Fixed

- Harness error hints include stderr/stdout when CI progress mode streams
  subprocess output (fixes CI and publish workflow failures).

---

## [0.2.0] - 2026-07-01

### Added

- **`driftless init-ci`** — scaffold GitHub Actions workflows (scan, migrate,
  refine, optional poll/plan) wired to the published composite Action.
- **CI hygiene** — `mypy` lint job and a **78%** pytest coverage gate.
- **Site** — updated landing page and docs.

### Changed

- In-repo workflows dogfood `uses: driftless-dev/driftless@v0.2.0` (composite
  Action at repo root; no `/action` path segment).
- Composite Action default `version` input pins `==0.2.0`; documents `poll` and
  `plan` commands.

---

## [0.1.1] - 2026-06-27

Patch release to validate PyPI Trusted Publishing from GitHub Releases.

### Fixed

- CLI tests use `tmp_path` instead of `CliRunner.isolated_filesystem` so CI passes
  across Typer/Click versions.

### Changed

- Repository and documentation URLs point at `driftless-dev/driftless`.

---

## [0.1.0] - 2026-06-27

First public release on [PyPI](https://pypi.org/project/driftless/0.1.0/).

### Added

- **`driftless` CLI** — `scan`, `configure`, `validate`, `compare`, `migrate`,
  `refine`, `poll`, `plan`, `report`, `open-pr`, `view`, and policy scaffolding.
- **Migration engine** — holdout-gated prompt repair, crash isolation,
  minimal-change tie-breaker, stall-escalation, and `AttemptRecord` trajectory
  logging.
- **Dataset-change path** — `refine` + `poll` for eval drift; suggested threshold
  refresh after label changes.
- **Run viewer** — `driftless view` and bundled `site/runs.html` for iteration
  metrics, cluster trends, and per-candidate prompt diffs.
- **GitHub Action** — composite `action.yml` wrapping the CLI for CI workflows.
- **Testbed** — `support-classifier-svc` with model-migration and dataset-change
  scenarios (290-ticket eval set, offline simulator + real-model validation paths).
- **Docs** — project overview, repair algorithm spec, 2×2 migration methodology,
  Poetry + Dependabot product framing.

[Unreleased]: https://github.com/driftless-dev/driftless/compare/v0.2.14...HEAD
[0.2.14]: https://github.com/driftless-dev/driftless/compare/v0.2.13...v0.2.14
[0.2.13]: https://github.com/driftless-dev/driftless/releases/tag/v0.2.13
[0.2.12]: https://github.com/driftless-dev/driftless/compare/v0.2.12...v0.2.13
[0.2.4]: https://github.com/driftless-dev/driftless/compare/v0.2.4...v0.2.5
[0.2.3]: https://github.com/driftless-dev/driftless/compare/v0.2.3...v0.2.4
[0.2.2]: https://github.com/driftless-dev/driftless/compare/v0.2.2...v0.2.3
[0.2.1]: https://github.com/driftless-dev/driftless/releases/tag/v0.2.1
[0.2.0]: https://github.com/driftless-dev/driftless/compare/v0.2.0...v0.2.1
[0.1.1]: https://github.com/driftless-dev/driftless/releases/tag/v0.1.1
[0.1.0]: https://github.com/driftless-dev/driftless/releases/tag/v0.1.0
