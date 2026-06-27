#!/usr/bin/env python3
"""Validate, normalize, and update the model lifecycle catalog.

This is the maintenance plumbing behind P1.1: turn "author the data" into
"review a diff." It does three jobs:

* ``--validate`` — schema/consistency gate (run in CI on every push).
* ``--check``    — assert the committed file is already normalized (CI gate so
                   diffs stay deterministic and reviewable).
* ``--write``    — normalize in place, optionally merging upstream ``--updates``
                   (a JSON array of model entries a scraper produced). A
                   scheduled job runs this and opens a PR when the file changes.

Real provider scraping is intentionally out of scope here: it's brittle and
provider-specific. This tool is the deterministic, testable spine that such a
scraper plugs into via ``--updates``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

DEFAULT_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "driftless"
    / "data"
    / "model_lifecycle.json"
)

VALID_STATUSES = {"active", "deprecated", "retired"}
VALID_TIERS = {"frontier", "balanced", "economy", "reasoning"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Canonical key order for a model entry (extra keys are appended, sorted).
_MODEL_KEYS = [
    "model",
    "provider",
    "status",
    "retirement_date",
    "recommended_replacement",
    "release_date",
    "capability_tier",
    "pricing",
]
_PRICING_KEYS = ["input_per_1m", "output_per_1m"]


def load_raw(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def _validate_date(label: str, value: Any, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not _DATE_RE.match(value):
        errors.append(f"{label}: invalid date {value!r} (expected YYYY-MM-DD)")


def _validate_pricing(label: str, pricing: Any, errors: list[str]) -> None:
    if pricing is None:
        return
    if not isinstance(pricing, dict):
        errors.append(f"{label}: pricing must be an object or null")
        return
    for key in _PRICING_KEYS:
        if key not in pricing:
            errors.append(f"{label}: pricing missing '{key}'")
            continue
        val = pricing[key]
        if not isinstance(val, (int, float)) or val < 0:
            errors.append(f"{label}: pricing.{key} must be a non-negative number")


def validate(data: dict[str, Any]) -> list[str]:
    """Return a list of human-readable errors (empty means valid)."""
    errors: list[str] = []
    if not isinstance(data, dict) or "models" not in data:
        return ["catalog must be an object with a 'models' array"]
    models = data["models"]
    if not isinstance(models, list) or not models:
        return ["'models' must be a non-empty array"]

    seen: set[str] = set()
    known: set[str] = set()
    for m in models:
        if isinstance(m, dict) and isinstance(m.get("model"), str):
            known.add(m["model"])

    for i, m in enumerate(models):
        label = f"models[{i}]"
        if not isinstance(m, dict):
            errors.append(f"{label}: must be an object")
            continue
        for req in ("model", "provider", "status"):
            if not isinstance(m.get(req), str) or not m[req].strip():
                errors.append(f"{label}: '{req}' is required and must be a non-empty string")
        model_id = m.get("model")
        if isinstance(model_id, str):
            label = f"models[{model_id}]"
            if model_id in seen:
                errors.append(f"{label}: duplicate model id")
            seen.add(model_id)
        if m.get("status") not in VALID_STATUSES:
            errors.append(
                f"{label}: status {m.get('status')!r} not in {sorted(VALID_STATUSES)}"
            )
        tier = m.get("capability_tier")
        if tier is not None and tier not in VALID_TIERS:
            errors.append(f"{label}: capability_tier {tier!r} not in {sorted(VALID_TIERS)}")
        _validate_date(f"{label}.retirement_date", m.get("retirement_date"), errors)
        _validate_date(f"{label}.release_date", m.get("release_date"), errors)
        _validate_pricing(label, m.get("pricing"), errors)
        repl = m.get("recommended_replacement")
        if repl is not None and repl not in known:
            errors.append(
                f"{label}: recommended_replacement {repl!r} is not a known model"
            )
    return errors


# --------------------------------------------------------------------------- #
# Normalization + serialization
# --------------------------------------------------------------------------- #
def _canonical_entry(m: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _MODEL_KEYS:
        if key in m:
            out[key] = m[key]
    for key in sorted(k for k in m if k not in _MODEL_KEYS):
        out[key] = m[key]
    if isinstance(out.get("pricing"), dict):
        pricing = out["pricing"]
        out["pricing"] = {k: pricing[k] for k in _PRICING_KEYS if k in pricing}
        for k in sorted(x for x in pricing if x not in _PRICING_KEYS):
            out["pricing"][k] = pricing[k]
    return out


def normalize(data: dict[str, Any]) -> dict[str, Any]:
    """Sort models by (provider, model) and canonicalize key order."""
    models = [_canonical_entry(m) for m in data["models"]]
    models.sort(key=lambda m: (m.get("provider", ""), m.get("model", "")))
    out = {"_meta": data.get("_meta", {}), "models": models}
    return out


def serialize(data: dict[str, Any]) -> str:
    """Deterministic text: pretty ``_meta``, one compact model object per line."""
    meta_block = json.dumps(data.get("_meta", {}), indent=2).replace("\n", "\n  ")
    lines = ["{", f'  "_meta": {meta_block},', '  "models": [']
    models = data["models"]
    for i, m in enumerate(models):
        suffix = "," if i < len(models) - 1 else ""
        lines.append("    " + json.dumps(m, separators=(", ", ": ")) + suffix)
    lines.append("  ]")
    lines.append("}")
    return "\n".join(lines) + "\n"


def merge(data: dict[str, Any], updates: list[dict[str, Any]]) -> dict[str, Any]:
    """Upsert ``updates`` into the catalog by model id."""
    by_id = {m["model"]: dict(m) for m in data["models"] if "model" in m}
    for upd in updates:
        mid = upd.get("model")
        if not mid:
            continue
        by_id[mid] = {**by_id.get(mid, {}), **upd}
    return {"_meta": data.get("_meta", {}), "models": list(by_id.values())}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--updates", type=Path, help="JSON array of model entries to merge")
    parser.add_argument("--stamp-date", help="set _meta.as_of (YYYY-MM-DD) on write")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate", action="store_true", help="schema gate only")
    mode.add_argument("--check", action="store_true", help="assert file is normalized")
    mode.add_argument("--write", action="store_true", help="normalize (and merge) in place")
    args = parser.parse_args(argv)

    data = load_raw(args.path)

    errors = validate(data)
    if errors:
        print("Catalog validation failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    if args.validate:
        print(f"OK: {len(data['models'])} models valid.")
        return 0

    if args.write and args.updates:
        updates = json.loads(args.updates.read_text(encoding="utf-8"))
        data = merge(data, updates)
        errors = validate(data)
        if errors:
            print("Merged catalog is invalid:", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            return 1

    if args.write and args.stamp_date:
        data.setdefault("_meta", {})["as_of"] = args.stamp_date

    normalized_text = serialize(normalize(data))

    if args.check:
        current = args.path.read_text(encoding="utf-8")
        if current != normalized_text:
            print(
                "Catalog is not normalized. Run: python tools/refresh_catalog.py --write",
                file=sys.stderr,
            )
            return 1
        print("OK: catalog is normalized.")
        return 0

    if args.write:
        args.path.write_text(normalized_text, encoding="utf-8")
        print(f"Wrote {len(normalize(data)['models'])} models to {args.path}.")
        return 0

    # Default: behave like --validate.
    print(f"OK: {len(data['models'])} models valid. (use --write/--check/--validate)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
