# Upgrading Driftless

## Upgrade to 0.3.0

Version 0.3.0 removes the legacy `migration.allow_*` fields. This is a
breaking contract-schema change: Driftless now rejects contracts containing
any of these fields instead of treating broad file categories as edit
authorization.

Before upgrading, open each `driftless.yml` and replace all `migration.allow_*`
settings with the complete exact-path allowlist in `files.editable`.

Before:

```yaml
files:
  context:
    - evals/gold.jsonl

migration:
  allow_prompt_edits: true
  allow_example_edits: false
  allow_config_edits: true
  allow_schema_edits: false
  allow_code_edits: false
  allow_business_logic_edits: false
  max_iterations: 3
```

After:

```yaml
files:
  editable:
    - prompts/support.txt
    - config/model.yaml
  context:
    - evals/gold.jsonl

migration:
  max_iterations: 3
```

`files.editable` is the entire edit policy:

- List every file Driftless may modify as an exact, repository-relative path.
- Do not list directories, globs such as `prompts/*.txt`, or file categories.
- Keep read-only optimizer inputs in `files.context`; that does not authorize
  edits.
- Omit any file that must never be changed. Driftless rejects a generated patch
  if it touches a path not listed in `files.editable`.

Run validation after updating each contract:

```bash
driftless validate -w <workflow>
```

Then update package and Action pins:

```bash
pip install "driftless==0.3.3"
```

```yaml
- uses: driftless-dev/driftless@v0.3.3
  with:
    version: "==0.3.3"
    command: validate
    workflow: <workflow>
```
