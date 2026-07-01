# Release process

How we cut a **driftless** release: changelog, version bump, git tag, GitHub
Release, and PyPI publish.

**Version source of truth:** `src/driftless/__init__.py` → `__version__`.
Hatch reads it at build time (`pyproject.toml` → `[tool.hatch.version]`).

**PyPI publish (normal path):** pushing a **GitHub Release** runs
`.github/workflows/publish.yml` via [Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
(OIDC — no long-lived API token in CI).

---

## Semver

| Bump | When |
|---|---|
| **MAJOR** (`1.0.0`) | Breaking CLI flags, contract schema breaks, or behavior changes that invalidate existing `driftless.yml` files without migration notes. |
| **MINOR** (`0.2.0`) | New commands, new optional contract fields, new triggers — backward compatible. |
| **PATCH** (`0.1.1`) | Bug fixes, docs-only packaging fixes, dependency ceiling tweaks. |

Pre-1.0: treat **MINOR** as the default for user-visible features; **PATCH** for
fixes and internal improvements.

---

## Checklist (every release)

### 1. Prepare on a branch

```bash
git checkout -b release/0.2.0
```

1. **Changelog** — move items from `[Unreleased]` into a dated section in
   [`CHANGELOG.md`](../CHANGELOG.md):

   ```markdown
   ## [0.2.0] - 2026-07-15

   ### Added
   - ...
   ```

   Update the comparison links at the bottom of the file.

2. **Version** — bump `__version__` in `src/driftless/__init__.py` only.

3. **Verify locally:**

   ```bash
  pip install -e ".[dev]"
  ./scripts/release-check.sh
  mypy
  pytest
   python -m build
   twine check dist/*
   ```

4. Open a PR titled `Release 0.2.0`, get review, merge to `main`.

### 2. Tag and GitHub Release

After merge to `main`:

```bash
git checkout main && git pull
git tag -a v0.2.0 -m "driftless 0.2.0"
git push origin v0.2.0
```

Then on GitHub: **Releases → Draft a new release**

- **Choose tag:** `v0.2.0` (must match `__version__` with a `v` prefix)
- **Title:** `driftless 0.2.0`
- **Description:** paste the `## [0.2.0]` section from `CHANGELOG.md`
- **Publish release** (not draft — `publish.yml` listens for `release: published`)

The **Publish to PyPI** workflow builds sdist + wheel, runs checks, and uploads.

### 3. Verify PyPI

Wait ~1–2 minutes, then:

```bash
pip install "driftless==0.2.0"
driftless --version
pipx install driftless==0.2.0   # optional smoke test
```

Confirm https://pypi.org/project/driftless/ shows the new version.

### 4. Post-release

On `main`, add a fresh `[Unreleased]` stub at the top of `CHANGELOG.md` if you
cleared it entirely, and start collecting notes for the next release.

---

## One-time: Trusted Publishing on PyPI

For CI publish without API tokens:

1. Create the `driftless` project on PyPI (done for 0.1.0).
2. **Project → Publishing** → add a trusted publisher:
   - **PyPI project name:** `driftless`
   - **Owner / repo:** your GitHub org/repo
   - **Workflow name:** `publish.yml`
   - **Environment name:** `pypi` (matches the workflow `environment:` key)
3. In GitHub repo **Settings → Environments**, create environment `pypi` (optional
   protection rules / required reviewers for production releases).

---

## Manual PyPI upload (emergency only)

If Trusted Publishing is misconfigured and a release is blocked:

```bash
# Never commit tokens; use env vars or `twine login`
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-...   # scoped token with upload scope only

pip install build twine
rm -rf dist && python -m build && twine check dist/*
twine upload dist/*
```

Prefer fixing Trusted Publishing and re-running the workflow from a new patch
release rather than making manual uploads routine.

---

## `scripts/release-check.sh`

Run before tagging. Fails if:

- `__version__` is missing or invalid semver
- `CHANGELOG.md` has no `## [X.Y.Z]` section for the current version
- (with `--tag vX.Y.Z`) the git tag argument doesn't match `__version__`

```bash
./scripts/release-check.sh
./scripts/release-check.sh --tag v0.2.0
```

---

## GitHub Action consumers

After a release, users can pin the composite Action by release tag
(`action.yml` lives at the repo root — no `/action` path segment):

```yaml
- uses: driftless-dev/driftless@v0.2.11
  with:
    command: scan
```

Or pin the PyPI package in the Action input:

```yaml
- uses: driftless-dev/driftless@v0.2.11
  with:
    version: "==0.2.11"
    command: migrate
```

Optionally maintain a floating **`v1`** tag on the latest stable minor release
(point it at the current release tag after each publish):

```bash
git tag -f v1 v0.2.11 && git push origin v1 --force
```

Update [`action.yml`](../action.yml) default `version` input when cutting releases.

---

## What triggers what

| Event | Result |
|---|---|
| PR merge with version bump only | Nothing published |
| `git tag vX.Y.Z` + push | Tag exists; no PyPI until GitHub Release |
| GitHub Release **published** | `publish.yml` → build + PyPI upload |
| GitHub Release **draft** | No publish |

---

## 0.1.0 note

`0.1.0` was uploaded manually before Trusted Publishing was wired. Tags and
GitHub Release for `v0.1.0` can be added retroactively for a clean history; PyPI
already hosts that version.

---

## Maintainer: live optimizer eval (P0.1)

The **migration-regression** workflow runs deterministic regression on every
push/PR and a **live** LLM optimizer eval nightly (or on manual dispatch). The
live job costs tokens and is opt-in via repository secrets.

### Required secrets

In **Settings → Secrets and variables → Actions**, add:

| Secret | Used by |
|---|---|
| `OPENAI_API_KEY` | Live eval matrix job (`provider: openai`) |
| `ANTHROPIC_API_KEY` | Live eval matrix job (`provider: anthropic`) |

If a secret is missing, that provider job exits cleanly with a warning (CI stays
green). On scheduled or manual runs, the **secrets-preflight** job writes a
summary table to the workflow run so you can see which keys are configured.
When both are set, nightly runs append to
`.driftless/regression-metrics.jsonl` and check against
`tests/fixtures/live_eval_baseline.json` with `--require-all`.

### Local reproduction

```bash
export DRIFTLESS_LIVE_EVAL=1
export OPENAI_API_KEY=...
pytest tests/test_migration_live.py -v -k openai
python scripts/check_live_eval_metrics.py --provider openai --require-all
```

After a few stable nightly runs, tighten floors in `live_eval_baseline.json`
(iterations ceiling, min F1/score).
