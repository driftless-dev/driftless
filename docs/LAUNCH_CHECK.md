# Launch Check

Last full suite and hosted cold-user UX checks: 2026-08-12.

This records the local checks used to keep the public-alpha release line ready
for technical early adopters. Commands should be run from the repository root
unless noted. `0.3.4` is the first published wheel that includes
`--generator fixture`.

## Suite

| Check | Result |
|---|---|
| `python -m mypy` | Pass: no issues in 28 source files. |
| `python -m pytest` | Pass: 389 passed, 16 skipped, coverage 85.83%. |
| `./scripts/release-check.sh` | Pass: version `0.3.4`, changelog, Action default, and workflow pins aligned. |
| `python -m build` | Pass: built sdist and wheel for `0.3.4`. |
| Example `validate` / `compare` | Pass: classifier, RAG, and agent fixtures match the expected gated-compare shape. |
| `--generator fixture` | Pass: bundled classifier, RAG, and agent examples migrate to `PASS` without provider keys. |
| `python scripts/check_site_links.py` | Pass: all local links and fragments are valid. |

The full pytest run needs permission to bind a local HTTP server for the run
viewer test.

## Hosted UX Checks

The 2026-08-12 pass regenerated all eight blog pages and verified:

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
env PYTHONPATH=../../src ../../.venv/bin/python -m driftless.cli migrate -w support_classifier --to gpt-4o-mini --generator fixture
```

Expected compare shape: baseline F1 `1.000`, target F1 `0.000`, cheaper target,
`FAIL min_f1`. Expected fixture migrate: `PASS`.

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

The `0.3.4` sdist and wheel include:

- `examples/support-classifier`
- `examples/rag-qa`
- `examples/tool-agent`

Generated example outputs such as `examples/**/evals/outputs.jsonl` are ignored
and are not included in the wheel.
