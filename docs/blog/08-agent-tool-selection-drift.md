# Tool-calling support agent: new planner, same tools

**Status:** publishable draft — uses the in-repo deterministic
[`examples/tool-agent`](../../examples/tool-agent) fixture and includes a
run-viewer capture.

## The use case

You run a support-style agent that must use tools — look up an order, check a
policy, create a ticket — before it answers the user. Success is not only a
polite final message. The agent must call the right tools in a safe order, avoid
side-effecting actions until it has enough information, and not invent an answer
when a tool was required.

You swap the planner model for something cheaper or newer. Final answers still
*look* fine in a chat playground. In eval, behavior breaks: the agent skips a
required lookup, calls a write tool too early, or refuses and apologizes instead
of using the tool you already exposed. Spot-checking final text misses all of
that. Without a tool trace on each eval row, you cannot tell whether the failure
was planning, tool choice, or generation — so the team either over-edits the
wrong prompt or concludes "agents are too flaky to migrate."

The use case is migrating the **agent workflow** with the same evidence bar as a
classifier: run the full loop under the candidate model, score final behavior
*and* the trace, and repair only the planner / tool-description files you mark
editable.

**What driftless does here:** run the whole agent workflow under the candidate
model, score the final behavior and trace, and repair only those editable files.

Artifact reference:
[`EXAMPLE_SUCCESS_PR.md`](../EXAMPLE_SUCCESS_PR.md) shows the evidence shape and
separates public testbed PR #4 from the different bundled saved success fixture;
the agent fixture uses the same report and `open-pr` path.

![Browser capture of the Driftless run viewer](../visuals/run-viewer.png)

If you only remember one rule: **agent migration needs trace evidence.** Final
answers are not enough. Emit the tools selected, tool errors, and final answer so
the repair loop can see whether the failure was planning, tool choice, or
generation.

---

## The app

The fixture is local and side-effect-free:

| Piece | Path |
|-------|------|
| Contract | `examples/tool-agent/driftless.yml` |
| Eval command | `python3 -m app.eval_agent` |
| Fake tool data | `data/orders.jsonl`, `data/policies.json` |
| Eval cases | `evals/cases.jsonl` |
| Gold trace expectations | `evals/gold.jsonl` |
| Editable prompts | `prompts/planner.md`, `prompts/tool_descriptions.md` |

The tools are plain Python functions over fixture data:

- `lookup_order`
- `check_policy`
- `refund_payment`
- `send_invoice`
- `reset_password`

No real refunds, emails, or account changes happen. That is intentional. Local
and CI examples should prove the workflow shape before anyone talks about hosted
agent execution.

---

## Reproduce the naive regression

From the repo root:

```bash
cd examples/tool-agent
driftless validate -w support_agent
driftless compare -w support_agent --to gpt-4o-mini
```

Actual local output from the fixture:

```text
Running gpt-4 (baseline) and gpt-4o-mini (target)...

┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┓
┃ Metric            ┃ Current ┃ Target (orig files) ┃
┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━┩
│ F1                │     n/a │                 n/a │
│ Precision         │     n/a │                 n/a │
│ Recall            │     n/a │                 n/a │
│ Accuracy          │     n/a │                 n/a │
│ Score / pass-rate │   1.000 │               0.000 │
│ Schema error rate │    0.0% │                0.0% │
│ Refusal rate      │    0.0% │                0.0% │
│ Total cost        │   0.096 │               0.024 │
└───────────────────┴─────────┴─────────────────────┘

Thresholds (target vs contract):
  FAIL min_score: 0.000 >= 0.85
  PASS max_cost_increase: -75.0% <= +20%
```

Again, cheaper is not enough. The candidate fails because it does not follow the
tool protocol.

---

## Score the trace, not just the prose

Each output row carries both final answer and trajectory:

```jsonl
{"id":"a001","final":"Refund issued for ord-1001...","tools":["lookup_order","check_policy","refund_payment"],"tool_errors":[],"score":1.0,"cost":0.024}
```

The evaluator gives zero credit when:

- a required tool is missing;
- tools are called in the wrong order;
- a side-effecting tool runs without policy eligibility;
- `tool_errors` is non-empty.

That makes the eval useful for migration. A candidate that says "refund issued"
without `lookup_order` and `check_policy` should fail before it reaches
production.

---

## The contract boundary

The important part of `driftless.yml` is the edit scope:

```yaml
files:
  editable:
    - prompts/planner.md
    - prompts/tool_descriptions.md
  readonly:
    - app/
    - data/orders.jsonl
    - data/policies.json
    - evals/cases.jsonl
    - evals/gold.jsonl
```

Driftless can clarify planner instructions and tool descriptions. It cannot edit
the tool simulator, fixture data, or scoring rules.

That boundary keeps the migration reviewable:

| Surface | Driftless role |
|---------|----------------|
| Planner prompt | Editable |
| Tool descriptions | Editable |
| Tool implementations | Read-only |
| Fixture data | Read-only |
| Eval scorer | Owned by the app |
| Hosted agent sandbox | Out of scope for this example |

---

## What a repair should learn

The baseline planner is intentionally vague:

```markdown
Choose tools that seem directly related to the customer request.

For refunds, use the refund tool when the customer asks for money back. Keep the
answer short and helpful.
```

For the cheaper model to pass, the planner/tool docs need to say the operational
rules directly:

- call `lookup_order` before refund decisions;
- call `check_policy` before `refund_payment`;
- do not call `refund_payment` unless eligibility is confirmed;
- include the tool trace in each result.

Those are prompt/tool-description changes, not application rewrites.

---

## Honest limits

- Keep first examples local or inside CI.
- Use fake or sandboxed tools for migration tests.
- Do not let a hosted runner execute arbitrary side-effecting tools without a
  sandbox.
- Add budgets before scaling: agent eval is records times tool calls times repair
  attempts.

Agentic workflows fit Driftless because the app remains the unit under test. The
tool's job is to make model swaps reviewable: same cases, same fake tools, same
score, clearer planner/tool prompts.
