# Launch Check

Last run: 2026-07-25

This records the local checks used before showing Driftless beyond design
partners. Commands should be run from the repository root unless noted.

## Suite

| Check | Result |
|---|---|
| `env PYTHONPATH=src .venv/bin/python -m mypy` | Pass: no issues in 28 source files. |
| `env PYTHONPATH=src .venv/bin/python -m pytest` | Pass: 345 passed, 12 skipped, coverage 82.91%. |
| `./scripts/release-check.sh` | Pass: version `0.3.0`, changelog section, and Action default aligned. |
| `.venv/bin/python -m build` | Pass: built sdist and wheel for `0.3.0`. |
| `.venv/bin/python -m twine check <temporary-dist>/*` | Pass: sdist and wheel metadata valid. |
| Cold install from wheel | Pass: copied the support-classifier example, validated it, reproduced the gated comparison, ran the expected `BLOCKED` no-generator migration, rendered its report, and previewed the issue dry-run. |

The full pytest run needs permission to bind a local HTTP server for the run
viewer test.

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

The `0.3.0` sdist and wheel include:

- `examples/support-classifier`
- `examples/rag-qa`
- `examples/tool-agent`

Generated example outputs such as `examples/**/evals/outputs.jsonl` are ignored
and are not included in the wheel.

