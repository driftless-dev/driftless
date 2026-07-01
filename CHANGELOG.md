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

[Unreleased]: https://github.com/driftless-dev/driftless/compare/v0.2.3...HEAD
[0.2.3]: https://github.com/driftless-dev/driftless/releases/tag/v0.2.3
[0.2.2]: https://github.com/driftless-dev/driftless/compare/v0.2.2...v0.2.3
[0.2.1]: https://github.com/driftless-dev/driftless/releases/tag/v0.2.1
[0.2.0]: https://github.com/driftless-dev/driftless/compare/v0.2.0...v0.2.1
[0.1.1]: https://github.com/driftless-dev/driftless/releases/tag/v0.1.1
[0.1.0]: https://github.com/driftless-dev/driftless/releases/tag/v0.1.0
