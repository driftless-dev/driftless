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

[Unreleased]: https://github.com/driftless-dev/driftless/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/driftless-dev/driftless/releases/tag/v0.1.0
