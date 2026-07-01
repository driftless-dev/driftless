# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`driftless judge-check`** — measure judge↔human agreement on a calibration set;
  `--enforce` applies the same gates as `migrate` / `compare`.
- **`driftless audit-labels`** — find duplicate/near-duplicate inputs with disagreeing
  gold labels before ``refine`` / ``migrate`` stall on label noise.
- Live eval CI: `--require-all` baseline check, metrics job summary, explicit metrics path.

### Changed

### Fixed

### Removed

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

[Unreleased]: https://github.com/driftless-dev/driftless/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/driftless-dev/driftless/releases/tag/v0.2.1
[0.2.0]: https://github.com/driftless-dev/driftless/releases/tag/v0.2.0
[0.1.1]: https://github.com/driftless-dev/driftless/releases/tag/v0.1.1
[0.1.0]: https://github.com/driftless-dev/driftless/releases/tag/v0.1.0
