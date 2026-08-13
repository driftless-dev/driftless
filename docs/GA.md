# General-availability criteria

Driftless `0.3.x` is a **public alpha**. This page records what “general
release / 1.0” means for this project so the claim is not confused with a
hosted SaaS bot.

## Supported 1.0 surface

1.0 means the **CLI and composite GitHub Action**, run in a repository the
customer controls:

- Contract, compare, migrate, refine, plan, poll, report, view, open-pr.
- `init-ci` generated workflows plus `driftless-dev/driftless@vX.Y.Z`.
- Bundled examples, including a key-free **blocked** path (`--generator none`)
  and a key-free **passing** path (`--generator fixture`).
- Customer-owned eval, thresholds, credentials, and sandboxing.

It does **not** mean a hosted GitHub App, hosted catalog service, hosted
dashboard, or a Driftless-operated sandbox for arbitrary agent tools. Those
remain out of scope rather than unfinished 1.0 features. See
[`LIMITS.md`](./LIMITS.md).

## Closed for this line

- Packaging, Action pin, Trusted Publishing, battletest, coverage gate, mypy.
- Honest limits, cost guidance, and eval-confidence caveats.
- Existing-repository adoption path: `scan` → `configure --apply` → validate /
  calibrate / compare → repair → `init-ci`.
- Reproducible bundled success via `--generator fixture` (first published in
  `0.3.4`).
- Contributor and operator docs: `CONTRIBUTING.md`, `.env.example`.
- Scheduled live optimizer eval fails on `driftless-dev/driftless` when no
  provider secrets are configured.

## Still required before flipping to 1.0

- Design-partner feedback on harnesses that are not the bundled classifier,
  RAG, and tool-agent shapes.
- A short history of green live-eval nightlies on the canonical repository.
- Version/docs hygiene at the moment of the 1.0 tag (`LAUNCH_CHECK`, Action
  pin, changelog).
- PyPI classifier change from Alpha to Production/Stable as part of that tag,
  not before.

Until then, keep calling the published line **public alpha**.
