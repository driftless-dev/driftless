from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def planner_is_safe() -> bool:
    planner = (ROOT / "prompts" / "planner.md").read_text().lower()
    tools = (ROOT / "prompts" / "tool_descriptions.md").read_text().lower()
    return (
        "lookup_order before refund" in planner
        and "check_policy before refund_payment" in planner
        and "refund_payment requires eligibility" in tools
        and "include the tool trace" in planner
    )


class ToolBox:
    def __init__(self, orders: dict[str, dict[str, Any]], policies: dict[str, Any]) -> None:
        self.orders = orders
        self.policies = policies

    def lookup_order(self, order_id: str) -> dict[str, Any]:
        return self.orders[order_id]

    def check_policy(self, order: dict[str, Any]) -> dict[str, Any]:
        window = self.policies["refund_window_days"]
        eligible = order["days_since_purchase"] <= window and order["status"] == "delivered"
        return {"eligible": eligible, "window_days": window}

    def refund_payment(self, order: dict[str, Any], policy: dict[str, Any]) -> str:
        if not policy["eligible"]:
            raise ValueError("refund_payment requires eligibility from check_policy")
        return f"refund-{order['order_id']}"

    def send_invoice(self, order: dict[str, Any]) -> str:
        return f"invoice-{order['order_id']}"

    def reset_password(self, account_email: str) -> str:
        return f"reset-link:{account_email}"


def safe_plan(case: dict[str, Any], tools: ToolBox) -> dict[str, Any]:
    task = case["task"]
    trace: list[str] = []
    errors: list[str] = []

    if task == "refund":
        order = tools.lookup_order(case["order_id"])
        trace.append("lookup_order")
        policy = tools.check_policy(order)
        trace.append("check_policy")
        if policy["eligible"]:
            refund_id = tools.refund_payment(order, policy)
            trace.append("refund_payment")
            final = f"Refund issued for {order['order_id']} ({refund_id})."
        else:
            final = f"Refund not issued for {order['order_id']}; outside the {policy['window_days']}-day window."
    elif task == "invoice":
        order = tools.lookup_order(case["order_id"])
        trace.append("lookup_order")
        invoice_id = tools.send_invoice(order)
        trace.append("send_invoice")
        final = f"Invoice sent for {order['order_id']} ({invoice_id})."
    elif task == "password_reset":
        token = tools.reset_password(case["account_email"])
        trace.append("reset_password")
        final = f"Password reset sent to {case['account_email']} ({token})."
    else:
        errors.append("unknown_task")
        final = "I could not determine the requested action."

    return {"final": final, "tools": trace, "tool_errors": errors}


def weak_plan(case: dict[str, Any]) -> dict[str, Any]:
    task = case["task"]
    if task == "refund":
        return {
            "final": "I can issue the refund now.",
            "tools": ["refund_payment"],
            "tool_errors": ["missing_lookup_order", "missing_check_policy"],
        }
    if task == "invoice":
        return {
            "final": "The invoice should be available in the billing portal.",
            "tools": [],
            "tool_errors": ["missing_lookup_order", "missing_send_invoice"],
        }
    if task == "password_reset":
        return {
            "final": "Ask an administrator to reset the password.",
            "tools": [],
            "tool_errors": ["missing_reset_password"],
        }
    return {"final": "I could not determine the requested action.", "tools": [], "tool_errors": ["unknown_task"]}


def score(row: dict[str, Any], gold: dict[str, Any]) -> float:
    if row["tool_errors"]:
        return 0.0
    if row["tools"] != gold["expected_tools"]:
        return 0.0
    final = row["final"].lower()
    hits = sum(1 for term in gold["required_terms"] if term.lower() in final)
    return round(hits / len(gold["required_terms"]), 3)


def main() -> None:
    model = os.environ.get("MODEL", "gpt-4")
    cases = load_jsonl(ROOT / "evals" / "cases.jsonl")
    gold_by_id = {row["id"]: row for row in load_jsonl(ROOT / "evals" / "gold.jsonl")}
    orders = {row["order_id"]: row for row in load_jsonl(ROOT / "data" / "orders.jsonl")}
    policies = load_json(ROOT / "data" / "policies.json")
    tools = ToolBox(orders, policies)
    safe = planner_is_safe()

    rows = []
    for case in cases:
        if "mini" in model and not safe:
            row = weak_plan(case)
        else:
            row = safe_plan(case, tools)
        row.update(
            {
                "id": case["id"],
                "score": score(row, gold_by_id[case["id"]]),
                "cost": 0.006 if "mini" in model else 0.024,
            }
        )
        rows.append(row)

    out = ROOT / "evals" / "outputs.jsonl"
    out.write_text("\n".join(json.dumps(row) for row in rows) + "\n")


if __name__ == "__main__":
    main()

