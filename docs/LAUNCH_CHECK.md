# Launch Check

Last full suite run: 2026-07-26. Hosted cold-user UX checks: 2026-07-29.

This records the local checks used to keep the public-alpha release line ready
for technical early adopters. Commands should be run from the repository root
unless noted.

## Suite

| Check | Result |
|---|---|
| `env PYTHONPATH=src .venv/bin/python -m mypy` | Pass: no issues in 28 source files. |
| `env PYTHONPATH=src .venv/bin/python -m pytest` | Pass: 355 passed, 12 skipped, coverage 82.81%. |
| `./scripts/release-check.sh` | Pass: version `0.3.1`, changelog section, and Action default aligned. |
| `.venv/bin/python -m build` | Pass: built sdist and wheel for `0.3.1`. |
| `.venv/bin/python -m twine check <temporary-dist>/*` | Pass: sdist and wheel metadata valid. |
| Cold install from wheel | Pass: copied the support-classifier example, validated it, reproduced the gated comparison, ran the expected `BLOCKED` no-generator migration, rendered its report, and previewed the issue dry-run. |

The full pytest run needs permission to bind a local HTTP server for the run
viewer test.

## Hosted UX Checks

The 2026-07-29 cold-user pass regenerated all eight blog pages and verified:

- `python scripts/check_site_links.py` — pass; all local links and fragments are
  valid.
- `mypy` — pass; no issues in 28 source files.
- `node --check site/assets/runs.js` and `site/assets/app.js` — pass.
- `git diff --check` — pass.

## Example Commands

Classification:

```bash
cd examples/support-classifier
env PYTHONPATH=../../src ../../.venv/bin/python -m driftless.cli validate -w support_classifier
env PYTHONPATH=../../src ../../.venv/bin/python -m driftless.cli compare -w support_classifier --to gpt-4o-mini
```

Expected compare shape: baseline F1 `1.000`, target F1 `0.000`, cheaper target,
`FAIL min_f1`.

RAG:

```bash
cd examples/rag-qa
env PYTHONPATH=../../src ../../.venv/bin/python -m driftless.cli validate -w rag_qa
env PYTHONPATH=../../src ../../.venv/bin/python -m driftless.cli compare -w rag_qa --to gpt-4o-mini
```

Expected compare shape: baseline score `1.000`, target score `0.000`, cheaper
target, `FAIL min_score`.

Agent:

```bash
cd examples/tool-agent
env PYTHONPATH=../../src ../../.venv/bin/python -m driftless.cli validate -w support_agent
env PYTHONPATH=../../src ../../.venv/bin/python -m driftless.cli compare -w support_agent --to gpt-4o-mini
```

Expected compare shape: baseline score `1.000`, target score `0.000`, cheaper
target, `FAIL min_score`.

## Packaging

The `0.3.1` sdist and wheel include:

- `examples/support-classifier`
- `examples/rag-qa`
- `examples/tool-agent`

Generated example outputs such as `examples/**/evals/outputs.jsonl` are ignored
and are not included in the wheel.

