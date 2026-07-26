# Command Chooser

Use this when you know what you want to learn, but not which Driftless command
to run.

| User situation | Command |
|---|---|
| Try the golden-path bundled example. | `driftless copy-example support-classifier` |
| Copy a RAG or tool-agent example. | `driftless copy-example rag-qa` or `driftless copy-example tool-agent` |
| Scaffold a contract for your repo. | `driftless init` |
| Check that the contract parses and the harness runs. | `driftless validate -w <workflow>` |
| Measure whether a target model is safe before editing anything. | `driftless compare -w <workflow> --to <model>` |
| Repair prompts/config for a model switch. | `driftless migrate -w <workflow> --to <model>` |
| Re-optimize after eval data changed but the model stayed fixed. | `driftless refine -w <workflow>` |
| Find model usage and deprecation risk. | `driftless scan` |
| Let CI decide which workflows need action. | `driftless plan` |
| Run policy decisions and open PRs/issues. | `driftless plan --act --create` |
| Measure judge reliability before optimizing against an LLM judge. | `driftless judge-check -w <workflow> --enforce` |
| Find duplicate inputs with conflicting labels. | `driftless audit-labels -w <workflow> --fail` |
| Render the latest markdown migration report. | `driftless report` |
| Inspect migration attempts in the local run viewer. | `driftless view` |
| Preview the PR or issue from the latest migration result. | `driftless open-pr -w <workflow>` |
| Actually create that PR or issue. | `driftless open-pr -w <workflow> --create` |

## Rule of Thumb

- Use `validate` when setup is the question.
- Use `compare` when safety of a target model is the question.
- Use `migrate` when you want Driftless to produce prompt/config changes.
- Use `refine` when labels or eval data changed but the model did not.
- Use `plan` when CI should decide what work exists.

## Key-Free Product Tour

```bash
pip install driftless
driftless copy-example support-classifier --out-dir driftless-classifier-demo
cd driftless-classifier-demo
driftless validate -w support_classifier
driftless compare -w support_classifier --to gpt-4o-mini
```

The classifier intentionally changes from F1 `1.000` to `0.000` while cost
falls from `0.024` to `0.004`, so `min_f1` fails. Exercise the blocked path
without provider keys:

```bash
driftless migrate -w support_classifier --to gpt-4o-mini --generator none
driftless report -w support_classifier
driftless open-pr -w support_classifier
```

The migration is expected to exit non-zero. The final command is a dry run by
default.

For an existing repository, use `driftless scan`, then
`driftless configure <workflow>` before `validate` and `compare`.

