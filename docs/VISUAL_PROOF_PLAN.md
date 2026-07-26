# Visual Proof Plan

Status: genuine CLI and GitHub screenshots captured on 2026-07-25, alongside
browser captures of the landing page and run viewer.

Use this before publishing README images or blog posts externally. The primary
proof now comes from executed commands and a real public testbed PR; SVGs remain
only as clearly labeled historical design excerpts.

The public testbed PR and the bundled saved success fixture are separate
artifacts. PR #4 used the 290-label public testbed and testbed-specific
deterministic patch tooling that is not shipped as a Driftless generator. The
saved fixture in `EXAMPLE_SUCCESS_PR.md` uses the bundled four-row demo and
different metrics.

## Current Proof

| Surface | Current artifact |
|---|---|
| Landing comparison | [`docs/visuals/landing-compare.png`](./visuals/landing-compare.png), aligned with the cold-install `compare` result in [`docs/LAUNCH_CHECK.md`](./LAUNCH_CHECK.md). |
| Compare scorecard | [`docs/visuals/compare-terminal.png`](./visuals/compare-terminal.png), captured from executed golden-path CLI output. |
| Blocked report / issue body | [`docs/EXAMPLE_REVIEW_ARTIFACT.md`](./EXAMPLE_REVIEW_ARTIFACT.md) captures the blocked issue path. |
| Successful PR body | [`docs/visuals/github-migration-pr.png`](./visuals/github-migration-pr.png), captured directly from [public draft PR #4](https://github.com/driftless-dev/support-classifier-svc/pull/4). |
| Successful PR diff | [`docs/visuals/github-migration-diff.png`](./visuals/github-migration-diff.png), captured from the PR files view. |
| Run viewer | [`docs/visuals/run-viewer.png`](./visuals/run-viewer.png), captured from `site/runs.html#sample`. |

## Visual Excerpts

These SVG sources predate the live proof and are retained only as design
excerpts. Do not present them as screenshots.

![Compare scorecard excerpt](./visuals/compare-scorecard.svg)

![Successful PR artifact excerpt](./visuals/successful-pr-artifact.svg)

![Run viewer excerpt](./visuals/run-viewer-excerpt.svg)

## Reproduction

### 1. Compare Scorecard

Command:

```bash
cd examples/support-classifier
env PYTHONPATH=../../src ../../.venv/bin/python -m driftless.cli compare -w support_classifier --to gpt-4o-mini
```

Capture:

- Terminal window showing the scorecard table.
- Keep `F1 1.000 -> 0.000`, `Total cost 0.024 -> 0.004`, and `FAIL min_f1`
  visible.

Use in:

- README quickstart.
- Blog post 1.
- Blog post 3.

### 2. Migration Report / PR Body

The current capture comes directly from public-testbed [draft PR
#4](https://github.com/driftless-dev/support-classifier-svc/pull/4). Its body was
generated from the saved migration result and includes `Result`, `Proposed
Diffs`, and `Holdout Validation`. It is historical proof of that testbed run,
not output that the published CLI can regenerate deterministically: rerunning
with the shipped LLM generator requires credentials and may produce a different
result.

Use in:

- README evidence section.
- Blog post 1.
- Blog post 3.

### 3. Run Viewer

Command:

```bash
cd site
python3 -m http.server 8787
```

Open:

```text
http://127.0.0.1:8787/runs.html#sample
```

Capture:

- Top summary card with status.
- Primary metric chart.
- Failure-cluster chart.
- Scorecard and attempt log.

Use in:

- Blog post 6.
- Blog post 7.
- Blog post 8.

### 4. GitHub PR / Issue Body

The public testbed PR is now the canonical passing-path proof:

- [Draft PR #4](https://github.com/driftless-dev/support-classifier-svc/pull/4)
- [Artifact distinction and reproduction limits](./EXAMPLE_SUCCESS_PR.md)
- The blocked issue path remains documented in
  [`docs/EXAMPLE_REVIEW_ARTIFACT.md`](./EXAMPLE_REVIEW_ARTIFACT.md).

Use in:

- README documentation section.
- Blog post 3.
- Blog post 4.

## Acceptance Criteria

- Scorecard screenshot from `compare`.
- Migration/report screenshot or markdown-rendered excerpt.
- Run viewer screenshot.
- Real GitHub PR body and files-changed screenshots.
- Blog posts 1, 3, 7, and 8 each link to or include at least one relevant
  visual.
