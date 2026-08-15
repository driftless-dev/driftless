# Support Classifier Example

This is the smallest bundled example: a tiny ticket classifier with gold
labels. It needs no API key.

```bash
pip install driftless
driftless copy-example support-classifier --out-dir driftless-classifier-demo
cd driftless-classifier-demo
driftless validate -w support_classifier
driftless compare -w support_classifier --to gpt-4o-mini
```

`compare` should fail: F1 goes from `1.000` to `0.000` while cost goes from
`0.024` to `0.004`. Read `FAIL min_f1: 0.000 >= 0.9` as “scored 0.000, needed
0.9.” The cheaper model is not safe to ship.

```bash
driftless migrate -w support_classifier --to gpt-4o-mini --generator none
# Expected: BLOCKED. Then:
driftless migrate -w support_classifier --to gpt-4o-mini --generator fixture
# Expected: PASS — bundled patch, still no API key.
```

`--generator fixture` is only for this simulator. `--generator llm` is
refused here because the harness does not call a model. For a live OpenAI
eval, use `copy-example support-classifier-live`.

`poll` treats a rewrite of every row in this 4-row set as a meaningful
dataset change (the default 5-row gate is capped at dataset size).

A passing `open-pr` updates `model.current` in `driftless.yml` and
`config/llm.yml`. The harness reads `MODEL` when Driftless sets it, and
the config file otherwise.

The names accepted by `copy-example` are `support-classifier`,
`support-classifier-live`, `rag-qa`, and `tool-agent`.
