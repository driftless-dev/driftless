# Contributing

Thanks for helping with Driftless. This repository is a Python CLI plus a
composite GitHub Action. The supported product surface is that CLI and Action
running in a repository you control — not a hosted bot.

## Development setup

Python 3.10+ is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,llm]"
```

Copy [`.env.example`](./.env.example) to `.env` and export only the variables
you need. Driftless does not load `.env` automatically.

## Checks

Run these from the repository root before opening a PR:

```bash
mypy
pytest
./scripts/release-check.sh
```

The full pytest run needs permission to bind a local HTTP server for the run
viewer test. Coverage must stay at or above the floor in `pyproject.toml`.

Optional, when you have provider keys:

```bash
export DRIFTLESS_LIVE_EVAL=1
pytest tests/test_migration_live.py -v -k openai
```

## Dependency policy

Driftless is a library-style CLI. `pyproject.toml` publishes version *ranges*,
not a lockfile. That keeps consumer installs from inheriting our transitive
pins.

- Dependabot updates pip and GitHub Actions weekly.
- CI installs those ranges on Python 3.10, 3.11, and 3.12.
- Do not add `uv.lock`, `poetry.lock`, or a root `requirements.txt` unless the
  release process changes to pin a dedicated application image.

## Docs and site

User-facing docs live in `docs/` and are summarized on the hosted site under
`site/`. If you change `docs/blog/*.md`, regenerate committed HTML:

```bash
python scripts/build_blog.py
```

CI fails when `site/blog` is stale.

## Pull requests

- Keep the change scoped to one concern.
- Match surrounding style; do not reformat unrelated files.
- Update `CHANGELOG.md` under `[Unreleased]` for user-visible changes.
- Do not commit secrets, `.env`, or `.driftless/` run artifacts.

Security reports belong in private GitHub advisories, not public issues. See
[`SECURITY.md`](./SECURITY.md).

Release mechanics are in [`docs/RELEASE.md`](./docs/RELEASE.md).
