# Support Classifier Example

This is a tiny deterministic classification workflow for trying Driftless with
gold labels and macro-F1 scoring. It classifies support tickets into fixed
categories and deliberately makes the target model drift unless the prompt is
tightened.

```bash
driftless validate -w support_classifier
driftless compare -w support_classifier --to gpt-4o-mini
```

