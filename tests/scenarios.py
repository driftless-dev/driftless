"""Shared, self-contained migration scenario used by the regression harness.

Both the deterministic engine regression (`test_migration_regression.py`) and
the live optimizer eval (`test_migration_live.py`) build the *same* gradeable
scenario, so they measure the same thing: can a known model regression be
repaired back to passing quality?

The scenario mirrors the testbed: a support-ticket classifier whose target model
regresses two independent, prompt-fixable ways -- markdown-fenced JSON (schema
errors) and refund->billing drift -- so a successful migration must make two
distinct, cluster-driven edits. The "app" is stdlib-only and deterministic; the
model is simulated, so the *workflow* needs no network. Only the live test's
generator calls a real LLM.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from driftless.contract import Workflow
from driftless.engine import Patch

# Keyword signals. Order matters (refund before billing). Kept in sync with the
# copy embedded in APP_PY below; the baseline F1==1.0 assertion guards drift.
KEYWORDS = [
    ("refund", ["refund", "money back", "money-back", "reimburse", "chargeback"]),
    ("technical", ["error", "crash", "bug", "broken", "slow", "login", "outage"]),
    ("account", ["password", "account", "profile", "email", "username", "2fa"]),
    ("billing", ["invoice", "charged", "billing", "payment", "subscription", "price"]),
]


def base_category(text: str) -> str:
    lowered = text.lower()
    for category, kws in KEYWORDS:
        if any(k in lowered for k in kws):
            return category
    return "technical"


# 6 tickets per class, authored so base_category() is unambiguous.
TICKETS = [
    "My invoice this month is wrong",
    "I was charged twice for the same thing",
    "I have a billing question about my plan",
    "My payment did not go through",
    "Please cancel my subscription",
    "The price went up unexpectedly",
    "The app throws an error on startup",
    "It crashes every time I open it",
    "There is a bug in the export feature",
    "The dashboard is completely broken",
    "Everything is really slow today",
    "I cannot login to the portal",
    "I forgot my password",
    "How do I update my profile",
    "I need to change my email",
    "My username is showing incorrectly",
    "Help me enable 2fa",
    "I want to close my account",
    "I want a refund for this order",
    "Please give me my money back",
    "Can you reimburse me for the outage",
    "I am requesting a chargeback",
    "I need a money-back on my purchase",
    "Refund the duplicate transaction",
]

# The starting (broken) prompt: deliberately omits the raw-JSON instruction and
# the refund-vs-billing rule, so the target model regresses until repaired.
INITIAL_PROMPT = (
    "You classify support tickets into one of: billing, technical, account, refund.\n"
    'Return the result as JSON, for example {"label": "billing"}.\n'
)

SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["label"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "label": {"type": "string", "enum": ["billing", "technical", "account", "refund"]},
    },
}

# stdlib-only "application". The model is simulated; behavior depends on the
# (editable) prompt, reproducing a realistic, fixable migration regression.
# ``SHUFFLE`` (toggled by build_scenario) emits outputs in reversed order to
# prove id-based alignment grades correctly regardless of output ordering.
APP_PY = '''\
import json, os, pathlib

SHUFFLE = False  # SHUFFLE_FLAG

KEYWORDS = [
    ("refund", ["refund", "money back", "money-back", "reimburse", "chargeback"]),
    ("technical", ["error", "crash", "bug", "broken", "slow", "login", "outage"]),
    ("account", ["password", "account", "profile", "email", "username", "2fa"]),
    ("billing", ["invoice", "charged", "billing", "payment", "subscription", "price"]),
]


def base(text):
    t = text.lower()
    for cat, kws in KEYWORDS:
        if any(k in t for k in kws):
            return cat
    return "technical"


model = os.environ["MODEL"]
prompt = pathlib.Path("prompts/system.txt").read_text(encoding="utf-8").lower()
is_target = model.startswith("new")
fences_ok = any(k in prompt for k in ["raw json", "no markdown", "json only"])
refund_ok = any(k in prompt for k in ["money-back", "money back", "not billing", "refund requests"])

lines = [l for l in pathlib.Path("inputs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
out_lines = []
for line in lines:
    rec = json.loads(line)
    cat = base(rec["text"])
    if is_target and cat == "refund" and not refund_ok:
        cat = "billing"  # refund -> billing drift
    raw = json.dumps({"label": cat})
    if is_target and not fences_ok:
        raw = "```json\\n" + raw + "\\n```"  # fence drift -> parse failure
    try:
        label = json.loads(raw)["label"]
    except Exception:
        label = None
    out_lines.append(json.dumps({"id": rec["id"], "label": label}))
if SHUFFLE:
    out_lines = out_lines[::-1]  # outputs returned out of input order
pathlib.Path("out.jsonl").write_text("\\n".join(out_lines) + "\\n", encoding="utf-8")
'''


def build_scenario(
    tmp_path: Path, *, current: str = "old-model", shuffle_outputs: bool = False
) -> Workflow:
    """Materialize the scenario into ``tmp_path`` and return its Workflow."""
    app_py = APP_PY
    if shuffle_outputs:
        app_py = app_py.replace("SHUFFLE = False  # SHUFFLE_FLAG", "SHUFFLE = True")
    (tmp_path / "app.py").write_text(app_py, encoding="utf-8")
    (tmp_path / "schema.json").write_text(json.dumps(SCHEMA, indent=2), encoding="utf-8")
    (tmp_path / "prompts").mkdir(exist_ok=True)
    (tmp_path / "prompts" / "system.txt").write_text(INITIAL_PROMPT, encoding="utf-8")

    inputs = [{"id": f"t{i:02d}", "text": t} for i, t in enumerate(TICKETS)]
    (tmp_path / "inputs.jsonl").write_text(
        "\n".join(json.dumps(x) for x in inputs) + "\n", encoding="utf-8"
    )
    (tmp_path / "labels.jsonl").write_text(
        "\n".join(json.dumps({"id": x["id"], "label": base_category(x["text"])}) for x in inputs)
        + "\n",
        encoding="utf-8",
    )

    return Workflow.model_validate(
        {
            "description": "Support ticket classifier (regression scenario).",
            "run": {
                "command": f"{sys.executable} app.py",
                "input_path": "inputs.jsonl",
                "output_path": "out.jsonl",
            },
            "model": {
                "current": current,
                "env_var": "MODEL",
                "target_candidates": ["new-model"],
            },
            "files": {
                "editable": ["prompts/system.txt"],
                "readonly": ["app.py", "schema.json"],
            },
            "eval": {
                "labels_path": "labels.jsonl",
                "schema_path": "schema.json",
                "label_field": "label",
                "id_field": "id",
                "split": {"tuning": "60%", "holdout": "40%"},
            },
            "thresholds": {"min_f1": 0.9, "max_schema_error_rate": 0.02},
            "migration": {"max_iterations": 6, "holdout_required": True},
        }
    )


class ScriptedRepair:
    """A deterministic, cluster-reactive generator standing in for the LLM.

    It fixes exactly one observed failure cluster per call (raw-JSON first, then
    the refund rule), so a successful run must iterate -- exercising the engine's
    clustering, candidate selection, and holdout gating just like the real loop.
    """

    PATH = "prompts/system.txt"

    def generate(self, context):
        content = context.editable_files[self.PATH]
        low = content.lower()
        new = content
        if any(c.kind == "schema_error" for c in context.clusters) and "raw json" not in low:
            new = content + "Return raw JSON only; do not use markdown code fences.\n"
        elif (
            any(c.kind == "misclassification" and "refund" in c.key for c in context.clusters)
            and "money-back" not in low
        ):
            new = content + "Money-back/refund requests must be classified as refund, not billing.\n"
        if new == content:
            return []
        return [Patch(files={self.PATH: new}, rationale="scripted cluster fix", kind="scripted")]


# --------------------------------------------------------------------------- #
# Data-change scenario: the *dataset* drifts, not the model.
#
# The model is well-behaved and held fixed; what changes is the customer's
# labeling policy. "Charge-reversal" tickets used to be `billing`; the updated
# dataset re-labels them as `refund`. The current prompt doesn't encode the new
# rule, so quality dips on the new labels until a clarification recovers it.
# This guards the `refine` / dataset-change dependency type the way the scenario
# above guards model migration -- a genuine label delta, no model regression.
# --------------------------------------------------------------------------- #

# Unambiguous rows (4 per base class) + an ambiguous "charge-reversal" group
# (8 rows) that the updated dataset now labels `refund` rather than `billing`.
DATA_CHANGE_ROWS = [
    # billing
    ("My invoice this month is wrong", "billing"),
    ("I was charged twice for the same thing", "billing"),
    ("My payment did not go through", "billing"),
    ("Please cancel my subscription", "billing"),
    # technical
    ("The app throws an error on startup", "technical"),
    ("It crashes every time I open it", "technical"),
    ("There is a bug in the export feature", "technical"),
    ("The dashboard is completely broken", "technical"),
    # account
    ("I forgot my password", "account"),
    ("How do I update my profile", "account"),
    ("I need to change my email", "account"),
    ("Help me enable 2fa", "account"),
    # refund (explicit, unchanged)
    ("I want a refund for this order", "refund"),
    ("Please give me my money back", "refund"),
    ("Can you reimburse me for the outage", "refund"),
    ("I am requesting a chargeback", "refund"),
    # charge-reversal: NEW policy -> refund (was billing before the data change)
    ("Please reverse this charge", "refund"),
    ("I want the charge reversed", "refund"),
    ("Can you reverse the charge on my card", "refund"),
    ("Reverse the charge I did not authorize", "refund"),
    ("Reverse this charge immediately", "refund"),
    ("I need this charge reversed today", "refund"),
    ("Kindly reverse the charge applied", "refund"),
    ("Reverse the charge from yesterday", "refund"),
]

# A healthy starting prompt for the *old* world: it handles every base class but
# is silent on the new charge-reversal rule (which is the whole point).
DATA_CHANGE_INITIAL_PROMPT = (
    "You classify support tickets into one of: billing, technical, account, refund.\n"
    'Return raw JSON only, for example {"label": "billing"}.\n'
)

# stdlib-only, deterministic, well-behaved model. Behavior is identical across
# models (no `is_target` gating): charge-reversal tickets are graded against the
# prompt rule, so a prompt edit -- not a model swap -- is what recovers quality.
DATA_CHANGE_APP_PY = '''\
import json, os, pathlib

BILLING = ["invoice", "charged", "billing", "payment", "subscription", "price"]
TECHNICAL = ["error", "crash", "bug", "broken", "slow", "login", "outage"]
ACCOUNT = ["password", "account", "profile", "email", "username", "2fa"]
REFUND = ["refund", "money back", "money-back", "reimburse", "chargeback"]

prompt = pathlib.Path("prompts/system.txt").read_text(encoding="utf-8").lower()
reversal_is_refund = "charge-reversal" in prompt

os.environ["MODEL"]  # model is read but the well-behaved model ignores it

lines = [l for l in pathlib.Path("inputs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
out_lines = []
for line in lines:
    rec = json.loads(line)
    t = rec["text"].lower()
    if "reverse" in t and "charge" in t:
        label = "refund" if reversal_is_refund else "billing"
    elif any(k in t for k in REFUND):
        label = "refund"
    elif any(k in t for k in BILLING):
        label = "billing"
    elif any(k in t for k in ACCOUNT):
        label = "account"
    else:
        label = "technical"
    out_lines.append(json.dumps({"id": rec["id"], "label": label}))
pathlib.Path("out.jsonl").write_text("\\n".join(out_lines) + "\\n", encoding="utf-8")
'''


def build_data_change_scenario(tmp_path: Path, *, current: str = "stable-model") -> Workflow:
    """Materialize the dataset-change scenario into ``tmp_path``.

    The labels reflect the *updated* dataset (charge-reversal -> refund); the
    starting prompt predates the policy change, so the workflow under-performs
    until refined.
    """
    (tmp_path / "app.py").write_text(DATA_CHANGE_APP_PY, encoding="utf-8")
    (tmp_path / "schema.json").write_text(json.dumps(SCHEMA, indent=2), encoding="utf-8")
    (tmp_path / "prompts").mkdir(exist_ok=True)
    (tmp_path / "prompts" / "system.txt").write_text(DATA_CHANGE_INITIAL_PROMPT, encoding="utf-8")

    inputs = [{"id": f"d{i:02d}", "text": text} for i, (text, _) in enumerate(DATA_CHANGE_ROWS)]
    (tmp_path / "inputs.jsonl").write_text(
        "\n".join(json.dumps(x) for x in inputs) + "\n", encoding="utf-8"
    )
    (tmp_path / "labels.jsonl").write_text(
        "\n".join(
            json.dumps({"id": f"d{i:02d}", "label": label})
            for i, (_, label) in enumerate(DATA_CHANGE_ROWS)
        )
        + "\n",
        encoding="utf-8",
    )

    return Workflow.model_validate(
        {
            "description": "Support ticket classifier (data-change scenario).",
            "run": {
                "command": f"{sys.executable} app.py",
                "input_path": "inputs.jsonl",
                "output_path": "out.jsonl",
            },
            "model": {
                "current": current,
                "env_var": "MODEL",
                "target_candidates": ["stable-model-v2"],
            },
            "files": {
                "editable": ["prompts/system.txt"],
                "readonly": ["app.py", "schema.json"],
            },
            "eval": {
                "labels_path": "labels.jsonl",
                "schema_path": "schema.json",
                "label_field": "label",
                "id_field": "id",
                "split": {"tuning": "60%", "holdout": "40%"},
            },
            "thresholds": {"min_f1": 0.9, "max_schema_error_rate": 0.02},
            "migration": {"max_iterations": 6, "holdout_required": True},
        }
    )


class DataChangeRepair:
    """Scripted generator for the data-change scenario.

    Reacts to the misclassification cluster the new labels produce by encoding
    the updated policy (charge-reversal -> refund) into the editable prompt.
    """

    PATH = "prompts/system.txt"

    def generate(self, context):
        content = context.editable_files[self.PATH]
        if "charge-reversal" in content.lower():
            return []
        if not any(c.kind == "misclassification" for c in context.clusters):
            return []
        new = content + (
            "Charge-reversal requests (asking to reverse a charge) are refunds, "
            "not billing.\n"
        )
        return [
            Patch(
                files={self.PATH: new},
                rationale="data-change: encode updated refund policy",
                kind="scripted",
            )
        ]


# --------------------------------------------------------------------------- #
# Verbosity-drift scenario: the target model prefixes prose before JSON.
# --------------------------------------------------------------------------- #

VERBOSITY_TICKETS = TICKETS[:8]  # two per class — enough to grade, fast to run

VERBOSITY_INITIAL_PROMPT = (
    "You classify support tickets into one of: billing, technical, account, refund.\n"
    'Return raw JSON only, for example {"label": "billing"}.\n'
)

VERBOSITY_APP_PY = '''\
import json, os, pathlib

KEYWORDS = [
    ("refund", ["refund", "money back", "money-back", "reimburse", "chargeback"]),
    ("technical", ["error", "crash", "bug", "broken", "slow", "login", "outage"]),
    ("account", ["password", "account", "profile", "email", "username", "2fa"]),
    ("billing", ["invoice", "charged", "billing", "payment", "subscription", "price"]),
]


def base(text):
    t = text.lower()
    for cat, kws in KEYWORDS:
        if any(k in t for k in kws):
            return cat
    return "technical"


model = os.environ["MODEL"]
prompt = pathlib.Path("prompts/system.txt").read_text(encoding="utf-8").lower()
is_target = model.startswith("new")
preamble_ok = "no preamble" in prompt or "json only" in prompt and "no prose" in prompt

lines = [l for l in pathlib.Path("inputs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
out_lines = []
for line in lines:
    rec = json.loads(line)
    cat = base(rec["text"])
    raw = json.dumps({"label": cat})
    if is_target and not preamble_ok:
        raw = "Sure! Here is the classification: " + raw
    try:
        label = json.loads(raw)["label"]
    except Exception:
        label = None
    out_lines.append(json.dumps({"id": rec["id"], "label": label}))
pathlib.Path("out.jsonl").write_text("\\n".join(out_lines) + "\\n", encoding="utf-8")
'''


def build_verbosity_scenario(tmp_path: Path, *, current: str = "old-model") -> Workflow:
    """Target model adds a prose preamble before JSON until the prompt forbids it."""
    (tmp_path / "app.py").write_text(VERBOSITY_APP_PY, encoding="utf-8")
    (tmp_path / "schema.json").write_text(json.dumps(SCHEMA, indent=2), encoding="utf-8")
    (tmp_path / "prompts").mkdir(exist_ok=True)
    (tmp_path / "prompts" / "system.txt").write_text(VERBOSITY_INITIAL_PROMPT, encoding="utf-8")

    inputs = [{"id": f"v{i:02d}", "text": t} for i, t in enumerate(VERBOSITY_TICKETS)]
    (tmp_path / "inputs.jsonl").write_text(
        "\n".join(json.dumps(x) for x in inputs) + "\n", encoding="utf-8"
    )
    (tmp_path / "labels.jsonl").write_text(
        "\n".join(json.dumps({"id": x["id"], "label": base_category(x["text"])}) for x in inputs)
        + "\n",
        encoding="utf-8",
    )

    return Workflow.model_validate(
        {
            "description": "Support ticket classifier (verbosity-drift scenario).",
            "run": {
                "command": f"{sys.executable} app.py",
                "input_path": "inputs.jsonl",
                "output_path": "out.jsonl",
            },
            "model": {
                "current": current,
                "env_var": "MODEL",
                "target_candidates": ["new-model"],
            },
            "files": {
                "editable": ["prompts/system.txt"],
                "readonly": ["app.py", "schema.json"],
            },
            "eval": {
                "labels_path": "labels.jsonl",
                "schema_path": "schema.json",
                "label_field": "label",
                "id_field": "id",
                "split": {"tuning": "60%", "holdout": "40%"},
            },
            "thresholds": {"min_f1": 0.9, "max_schema_error_rate": 0.02},
            "migration": {"max_iterations": 4, "holdout_required": True},
        }
    )


class VerbosityRepair:
    """Fix prose-before-JSON drift by tightening output-format instructions."""

    PATH = "prompts/system.txt"

    def generate(self, context):
        content = context.editable_files[self.PATH]
        low = content.lower()
        if "no preamble" in low:
            return []
        if not any(c.kind == "schema_error" for c in context.clusters):
            return []
        new = content + "Respond with JSON only; no preamble or prose before the object.\n"
        return [Patch(files={self.PATH: new}, rationale="verbosity: forbid preamble", kind="scripted")]


# --------------------------------------------------------------------------- #
# Label-hallucination scenario: target model invents out-of-enum labels.
# --------------------------------------------------------------------------- #

HALLUCINATION_TICKETS = VERBOSITY_TICKETS

HALLUCINATION_INITIAL_PROMPT = (
    "You classify support tickets.\n"
    'Return raw JSON only, for example {"label": "billing"}.\n'
)

HALLUCINATION_APP_PY = '''\
import json, os, pathlib

KEYWORDS = [
    ("refund", ["refund", "money back", "money-back", "reimburse", "chargeback"]),
    ("technical", ["error", "crash", "bug", "broken", "slow", "login", "outage"]),
    ("account", ["password", "account", "profile", "email", "username", "2fa"]),
    ("billing", ["invoice", "charged", "billing", "payment", "subscription", "price"]),
]


def base(text):
    t = text.lower()
    for cat, kws in KEYWORDS:
        if any(k in t for k in kws):
            return cat
    return "technical"


model = os.environ["MODEL"]
prompt = pathlib.Path("prompts/system.txt").read_text(encoding="utf-8").lower()
is_target = model.startswith("new")
closed_ok = "only these labels" in prompt or "closed set" in prompt

lines = [l for l in pathlib.Path("inputs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
out_lines = []
for line in lines:
    rec = json.loads(line)
    cat = base(rec["text"])
    if is_target and not closed_ok:
        cat = "general"  # hallucinated label -> schema enum violation
    out_lines.append(json.dumps({"id": rec["id"], "label": cat}))
pathlib.Path("out.jsonl").write_text("\\n".join(out_lines) + "\\n", encoding="utf-8")
'''


def build_hallucination_scenario(tmp_path: Path, *, current: str = "old-model") -> Workflow:
    """Target model emits labels outside the schema enum until the prompt forbids it."""
    (tmp_path / "app.py").write_text(HALLUCINATION_APP_PY, encoding="utf-8")
    (tmp_path / "schema.json").write_text(json.dumps(SCHEMA, indent=2), encoding="utf-8")
    (tmp_path / "prompts").mkdir(exist_ok=True)
    (tmp_path / "prompts" / "system.txt").write_text(HALLUCINATION_INITIAL_PROMPT, encoding="utf-8")

    inputs = [{"id": f"h{i:02d}", "text": t} for i, t in enumerate(HALLUCINATION_TICKETS)]
    (tmp_path / "inputs.jsonl").write_text(
        "\n".join(json.dumps(x) for x in inputs) + "\n", encoding="utf-8"
    )
    (tmp_path / "labels.jsonl").write_text(
        "\n".join(json.dumps({"id": x["id"], "label": base_category(x["text"])}) for x in inputs)
        + "\n",
        encoding="utf-8",
    )

    return Workflow.model_validate(
        {
            "description": "Support ticket classifier (label-hallucination scenario).",
            "run": {
                "command": f"{sys.executable} app.py",
                "input_path": "inputs.jsonl",
                "output_path": "out.jsonl",
            },
            "model": {
                "current": current,
                "env_var": "MODEL",
                "target_candidates": ["new-model"],
            },
            "files": {
                "editable": ["prompts/system.txt"],
                "readonly": ["app.py", "schema.json"],
            },
            "eval": {
                "labels_path": "labels.jsonl",
                "schema_path": "schema.json",
                "label_field": "label",
                "id_field": "id",
                "split": {"tuning": "60%", "holdout": "40%"},
            },
            "thresholds": {"min_f1": 0.9, "max_schema_error_rate": 0.02},
            "migration": {"max_iterations": 4, "holdout_required": True},
        }
    )


class HallucinationRepair:
    """Constrain the label space so the model stops inventing enum values."""

    PATH = "prompts/system.txt"

    def generate(self, context):
        content = context.editable_files[self.PATH]
        if "only these labels" in content.lower():
            return []
        if not any(c.kind == "schema_error" for c in context.clusters):
            return []
        new = content + (
            "Use ONLY these labels (closed set): billing, technical, account, refund. "
            "Never invent labels like general or support.\n"
        )
        return [
            Patch(files={self.PATH: new}, rationale="hallucination: closed label set", kind="scripted")
        ]


# --------------------------------------------------------------------------- #
# Multi-field extraction scenario: category + priority slot filling.
# --------------------------------------------------------------------------- #

EXTRACTION_ROWS = [
    ("My invoice this month is wrong", "billing", "high"),
    ("I was charged twice for the same thing", "billing", "high"),
    ("The app throws an error on startup", "technical", "low"),
    ("It crashes every time I open it", "technical", "low"),
    ("I forgot my password", "account", "low"),
    ("How do I update my profile", "account", "low"),
    ("I want a refund for this order", "refund", "high"),
    ("Please give me my money back", "refund", "high"),
]

EXTRACTION_INITIAL_PROMPT = (
    "Extract support ticket category and priority.\n"
    'Return raw JSON with keys "category" and "priority".\n'
)

EXTRACTION_APP_PY = '''\
import json, os, pathlib

BILLING = ["invoice", "charged", "billing", "payment", "subscription", "price"]
TECHNICAL = ["error", "crash", "bug", "broken", "slow", "login", "outage"]
ACCOUNT = ["password", "account", "profile", "email", "username", "2fa"]
REFUND = ["refund", "money back", "money-back", "reimburse", "chargeback"]

prompt = pathlib.Path("prompts/system.txt").read_text(encoding="utf-8").lower()
is_target = os.environ["MODEL"].startswith("new")
priority_ok = "refund" in prompt and "high priority" in prompt

lines = [l for l in pathlib.Path("inputs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
out_lines = []
for line in lines:
    rec = json.loads(line)
    t = rec["text"].lower()
    if any(k in t for k in REFUND):
        category = "refund"
    elif any(k in t for k in BILLING):
        category = "billing"
    elif any(k in t for k in ACCOUNT):
        category = "account"
    else:
        category = "technical"
    if is_target and not priority_ok:
        priority = "low"
    elif category in ("refund", "billing"):
        priority = "high"
    else:
        priority = "low"
    out_lines.append(json.dumps({"id": rec["id"], "category": category, "priority": priority}))
pathlib.Path("out.jsonl").write_text("\\n".join(out_lines) + "\\n", encoding="utf-8")
'''


def build_extraction_scenario(tmp_path: Path, *, current: str = "old-model") -> Workflow:
    """Multi-field extraction migration: target model under-assigns priority."""
    (tmp_path / "app.py").write_text(EXTRACTION_APP_PY, encoding="utf-8")
    (tmp_path / "prompts").mkdir(exist_ok=True)
    (tmp_path / "prompts" / "system.txt").write_text(EXTRACTION_INITIAL_PROMPT, encoding="utf-8")

    inputs = [{"id": f"e{i:02d}", "text": text} for i, (text, _, _) in enumerate(EXTRACTION_ROWS)]
    (tmp_path / "inputs.jsonl").write_text(
        "\n".join(json.dumps(x) for x in inputs) + "\n", encoding="utf-8"
    )
    (tmp_path / "labels.jsonl").write_text(
        "\n".join(
            json.dumps({"id": f"e{i:02d}", "category": cat, "priority": pri})
            for i, (_, cat, pri) in enumerate(EXTRACTION_ROWS)
        )
        + "\n",
        encoding="utf-8",
    )

    return Workflow.model_validate(
        {
            "description": "Ticket extraction (category + priority).",
            "run": {
                "command": f"{sys.executable} app.py",
                "input_path": "inputs.jsonl",
                "output_path": "out.jsonl",
            },
            "model": {
                "current": current,
                "env_var": "MODEL",
                "target_candidates": ["new-model"],
            },
            "files": {
                "editable": ["prompts/system.txt"],
                "readonly": ["app.py"],
            },
            "eval": {
                "labels_path": "labels.jsonl",
                "id_field": "id",
                "fields": ["category", "priority"],
                "split": {"tuning": "60%", "holdout": "40%"},
            },
            "thresholds": {"min_f1": 0.9},
            "migration": {"max_iterations": 4, "holdout_required": True},
        }
    )


class ExtractionRepair:
    """Encode the priority rubric the target model lost on migration."""

    PATH = "prompts/system.txt"

    def generate(self, context):
        content = context.editable_files[self.PATH]
        if "high priority" in content.lower():
            return []
        if not any("priority" in c.key for c in context.clusters):
            return []
        new = content + (
            "Refund and billing tickets are high priority; technical and account "
            "tickets are low priority.\n"
        )
        return [Patch(files={self.PATH: new}, rationale="extraction: priority rubric", kind="scripted")]

