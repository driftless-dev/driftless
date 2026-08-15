# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

- **New-user docs** — README, getting started, hosted docs, and the blog index
  lead with a plain-language first run, a short glossary, and an explanation of
  the demo `FAIL min_f1` line. Specialist CLI/policy pages stay, but are no
  longer the front door.

### Fixed

---

## [0.3.4] - 2026-08-12

### Added

- **`--generator fixture`** — key-free passing repair for bundled examples
  (`support-classifier`, `rag-qa`, `tool-agent`), so the published CLI can
  reproduce a successful migration without provider credentials.
- **Contributor and operator docs** — `CONTRIBUTING.md`, `.env.example`,
  eval-confidence guidance, and explicit 1.0 / GA criteria (CLI + Action, not
  a hosted bot).

### Changed

- **Hosted site adoption copy** — landing and docs match `configure --apply`,
  inferred `init-ci` setup, and Action pin `v0.3.4`.
- **Landing page story** — hero has one primary CTA; scenario cards match their
  markup; outcomes show reproducible `--generator none` / `--generator fixture`
  paths; PR #4 is captioned as historical proof.
- **Supported-surface limits** — hosted GitHub App, catalog SaaS, and agent
  sandboxing are documented as out of scope rather than unfinished GA work.
- **Live optimizer gate** — scheduled runs on `driftless-dev/driftless` fail
  when no provider secrets are configured, instead of skipping green.
- **Publish cold-install** — after installing the wheel from PyPI, copy the
  bundled classifier example and run `migrate --generator fixture`.

### Fixed

- **Wheel metadata** — cap `hatchling` below 1.30 so sdist/wheel emit
  Metadata-Version 2.4, which released twine and PyPI accept.

---

## [0.3.3] - 2026-08-02

### Changed

- **Richer `configure` inference** — scaffolds fill description from
  `pyproject.toml` / README (or a humanized workflow name), prefer cheaper
  same-provider catalog targets when no lifecycle replacement exists, and mark
  common `src/` / `evals/` / `tests/` trees readonly.

### Fixed

- **Publish cold-install verification** — assert the installed package version via
  import (and ANSI-stripped CLI output) so Rich digit highlighting under
  `GITHUB_ACTIONS` cannot false-fail the post-publish gate; `release-check
  --remote` prefers `python3`.
- **Adoption battletest fixture** — includes `pyproject.toml` so `init-ci`
  exercises application setup inference without `--setup-command`.

---

## [0.3.2] - 2026-07-31

### Added

- **Release-candidate governance** — release metadata and in-repository Action
  pins are checked in CI, and publish verification covers every supported Python
  version before artifacts can reach PyPI.
- **Cold-user adoption guidance** — bundled examples, command selection,
  existing-repository setup, and public testbed reproduction now follow one
  documented path.
- **Enforceable comparisons and adoption battletest** — `compare --enforce`
  provides CI exit semantics, while a clean-wheel fixture exercises the full
  existing-repository journey before publication.

### Changed

- **Non-mutating automation previews** — `plan --act` and `poll --act` evaluate
  and report candidate repairs without writing editable files unless `--create`
  is explicitly supplied.
- **Composite Action input handling** — Action inputs now cross into Bash through
  environment variables, with command validation and non-evaluating argument
  parsing.
- **Safer CI defaults** — generated refinement is manual unless
  `--refine-on-push` is explicit, and `--setup-command` installs customer
  application dependencies before provider-backed work.
- **Guided contract adoption** — `configure --apply` safely creates or appends
  workflows, while `init` is neutral and unresolved placeholders block execution.

### Fixed

- **GA automation branch safety** — multi-trigger plan/poll runs now branch from
  and return to the original base, reject unknown local/remote retry branches,
  persist poll debounce state on the base branch, and skip migrations for
  already-open deterministic artifacts.
- **Repair prompt path containment** — configured system and user prompt files
  can no longer escape the repository, including through symlinks.
- **Generated plan workflow** — `init-ci --plan` now includes `--create`, so its
  scheduled workflow actually opens the PR or issue promised by the scaffold.
- **Failed PR recovery** — a branch newly pushed by Driftless is removed when PR
  creation fails, and the matching local retry branch is cleaned up only when
  remote cleanup succeeds.
- **Generated migration delivery** — blocked migrations continue to
  `open-pr`, create their evidence issue, then restore the failing job status.
- **Grading-aware generated CI** — score and judge workflows no longer receive
  classification-only label-audit steps or malformed GitHub expressions.

---

## [0.3.1] - 2026-07-26

### Added

- **Hosted public-alpha site deployment** — GitHub Pages now publishes the
  committed landing page, documentation, blog, and run viewer from `site/`.

### Changed

- **Cold-user documentation path** — PyPI-safe absolute links, explicit
  public-alpha framing, CI adoption guidance, and proof reproducibility notes
  now match across the README and hosted site.
- **Dependabot self-reference policy** — automated Action updates ignore this
  repository's own release pin instead of treating floating `v1` as an upgrade.

### Fixed

- **No-change refinement automation** — `poll --act` records a processed dataset
  without opening a misleading model-migration issue when refinement makes no
  changes.
- **GitHub artifact reliability** — config preparation rolls back on pre-commit
  failure, generated branches resist sanitized-name collisions, and dedupe
  fails closed when GitHub queries are unavailable.

---

## [0.3.0] - 2026-07-25

This minor release contains a breaking contract-schema correction. Existing
contracts that use `migration.allow_*` must migrate to exact `files.editable`
paths before upgrading. See the [0.3 upgrade guide](docs/UPGRADING.md).

### Added

- **RAG and agent workflow guide/examples** — contract patterns plus runnable
  deterministic retrieval QA and tool-agent fixtures.
- **Support classifier example** — runnable bundled gold-label classification
  fixture for launch checks and first-time users.
- **Launch check artifact** — records suite, packaging, and example command
  results for broader user-readiness review.
- **Successful PR fixture** — saved evidence-backed PR body with prompt diff,
  scorecard, thresholds, and reviewer instructions.
- **Visual proof plan** — screenshot targets and current markdown substitutes
  for README/blog launch assets.
- **Visual proof excerpts** — checked-in SVG scorecard, PR body, and run-viewer
  excerpts for README/blog drafts before browser screenshots are captured.
- **User readiness plan** — launch-readiness gaps and acceptance criteria for
  broader self-serve adoption.
- **Self-serve quickstart docs** — bundled example copying, command chooser, and
  known-limits guidance.
- **Example review artifact** — saved blocked-migration issue/report fixture for
  no-key product walkthroughs.
- **Cost and budget guidance** — practical defaults for eval sizes, RAG, agents,
  and judge-graded workflows.
- **Security baseline** — vulnerability reporting policy, Dependabot updates,
  and CodeQL scanning.
- **Live product proof** — genuine CLI output plus public GitHub PR/report and
  files-changed screenshots from the deterministic testbed migration.

### Changed

- **Unified onboarding** — README, site docs, and example guides now use one
  key-free support-classifier path with the same expected gated output.
- **Exact edit policy** — `files.editable` is now the sole deterministic repair
  boundary; generated contracts, reports, and repair docs use exact paths.
- **Public site and blog** — redesigned around dependency synchronization,
  scoped repair, holdout gating, and evidence-backed updates.
- **`validate` success guidance** — successful validation now prints likely next
  commands, including the first configured target candidate when available.
- **First-run error hints** — command-not-found and missing-label failures now
  point users at the contract fields most likely to fix them.

### Fixed

- **Workflow examples** — repository-local policy workflows no longer run on
  schedules without a root contract, and catalog refresh reports disabled PR
  permissions without failing the refresh.
- **Landing CTA contrast** — primary navigation and hero button labels remain
  visible under the landing-page link color rules.
- **Safe PR previews and creation** — dry-run PR paths no longer modify model
  configuration, and real config updates are deferred until after deduplication
  and branch creation.
- **Model-only config migrations** — successful naive swaps now propose the
  configured model file as a PR instead of incorrectly requesting an
  environment-variable update.
- **Repository path containment** — editable, context, patch, and model config
  paths that resolve outside the repository are rejected.
- **Generated branch safety** — workflow and target model identifiers are
  sanitized before being used in Git branch names.

### Removed

- **Unenforceable migration category flags** — legacy `migration.allow_*`
  options now fail with guidance to use explicit `files.editable` paths.

### Upgrade notes

- Replace every legacy `migration.allow_*` field with the complete list of
  exact repository-relative paths Driftless may modify under `files.editable`.
  Globs, directories, and file-type categories are not accepted. See the
  [before/after migration example](docs/UPGRADING.md).
---

## [0.2.15] - 2026-07-01

### Added

- **P1.1 Google deprecation changelog** — `fetch_provider_deprecations` scrapes
  the Gemini API changelog for lifecycle hints on existing catalog models.

### Fixed

- **Catalog deprecation merge** — ignore `recommended_replacement` targets that
  are not `active` in the committed catalog (avoids proposing retired models).

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

[Unreleased]: https://github.com/driftless-dev/driftless/compare/v0.3.4...HEAD
[0.3.4]: https://github.com/driftless-dev/driftless/compare/v0.3.3...v0.3.4
[0.3.3]: https://github.com/driftless-dev/driftless/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/driftless-dev/driftless/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/driftless-dev/driftless/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/driftless-dev/driftless/compare/v0.2.15...v0.3.0
[0.2.15]: https://github.com/driftless-dev/driftless/compare/v0.2.14...v0.2.15
[0.2.14]: https://github.com/driftless-dev/driftless/releases/tag/v0.2.14
[0.2.13]: https://github.com/driftless-dev/driftless/compare/v0.2.12...v0.2.13
[0.2.12]: https://github.com/driftless-dev/driftless/compare/v0.2.11...v0.2.12
[0.2.11]: https://github.com/driftless-dev/driftless/compare/v0.2.10...v0.2.11
[0.2.10]: https://github.com/driftless-dev/driftless/compare/v0.2.9...v0.2.10
[0.2.9]: https://github.com/driftless-dev/driftless/compare/v0.2.8...v0.2.9
[0.2.8]: https://github.com/driftless-dev/driftless/compare/v0.2.7...v0.2.8
[0.2.7]: https://github.com/driftless-dev/driftless/compare/v0.2.6...v0.2.7
[0.2.6]: https://github.com/driftless-dev/driftless/compare/v0.2.5...v0.2.6
[0.2.5]: https://github.com/driftless-dev/driftless/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/driftless-dev/driftless/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/driftless-dev/driftless/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/driftless-dev/driftless/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/driftless-dev/driftless/releases/tag/v0.2.1
[0.2.0]: https://github.com/driftless-dev/driftless/releases/tag/v0.2.0
[0.1.1]: https://github.com/driftless-dev/driftless/releases/tag/v0.1.1
[0.1.0]: https://github.com/driftless-dev/driftless/releases/tag/v0.1.0
