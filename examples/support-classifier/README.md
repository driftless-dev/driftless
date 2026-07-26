# Support Classifier Example

This is the golden-path bundled example: a tiny deterministic classification
workflow with gold labels, macro-F1 scoring, and cost tracking. It requires no
provider keys.

```bash
pip install driftless
driftless copy-example support-classifier --out-dir driftless-classifier-demo
cd driftless-classifier-demo
driftless validate -w support_classifier
driftless compare -w support_classifier --to gpt-4o-mini
```

The classifier output deliberately drifts: F1 falls from `1.000` to `0.000`
while cost falls from `0.024` to `0.004`. The resulting
`FAIL min_f1: 0.000 >= 0.9` demonstrates that a cheaper model is not necessarily
safe to ship.

Continue through the blocked path without provider credentials:

```bash
driftless migrate -w support_classifier --to gpt-4o-mini --generator none
driftless report -w support_classifier
driftless open-pr -w support_classifier
```

`migrate` is expected to exit non-zero with `BLOCKED`. Run the remaining
commands afterward. `open-pr` is a dry run unless `--create` is supplied.

The three names accepted by `copy-example` are `support-classifier`, `rag-qa`,
and `tool-agent`.
