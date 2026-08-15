# Support Classifier (live)

Same four tickets as `support-classifier`, but this harness **calls OpenAI**.
You need `OPENAI_API_KEY`. Each `compare` / `migrate` run spends a little
money and is not deterministic.

For the key-free tour, use `support-classifier` instead.

```bash
pip install 'driftless[llm]'
export OPENAI_API_KEY=...
driftless copy-example support-classifier-live --out-dir driftless-classifier-live
cd driftless-classifier-live
driftless validate -w support_classifier_live
driftless compare -w support_classifier_live --to gpt-4o-mini
driftless migrate -w support_classifier_live --to gpt-4o-mini --generator llm
```

`--generator fixture` has no patch here. `--generator none` analyzes without
editing the prompt. Scores depend on the models that day; do not expect the
fixed `1.000 → 0.000` table from the simulator.

Without a key, `validate` / `compare` exit with `OPENAI_API_KEY is not set`.
