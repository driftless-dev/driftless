"""Scaffold a migration-ready workflow contract from scan detections.

This is the "make migration-ready" onboarding step. We don't clobber an
existing curated ``driftless.yml`` (which would lose comments); instead we
generate a workflow snippet, prefilled from detections where possible, and save
it for the user to drop in.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import yaml

from .lifecycle import load_lifecycle
from .scanner import scan_repo


def _detect_primary(path: Path) -> tuple[str | None, str | None, str | None, str | None]:
    """Return (model, provider, env_var, recommended_replacement) best-effort.

    Prefers an at-risk model so the scaffold targets the most urgent migration.
    """
    lifecycle = load_lifecycle()
    result = scan_repo(path, lifecycle=lifecycle)

    model_counts = Counter(f.model for f in result.findings if f.kind == "model_id" and f.model)
    env_counts = Counter(f.env_var for f in result.findings if f.env_var)
    provider_counts = Counter(f.provider for f in result.findings if f.provider)

    chosen_model = None
    # Prefer an at-risk model, then the most common model.
    at_risk = [m for m in model_counts if (info := lifecycle.lookup(m)) and info.at_risk]
    if at_risk:
        chosen_model = sorted(at_risk, key=lambda m: -model_counts[m])[0]
    elif model_counts:
        chosen_model = model_counts.most_common(1)[0][0]

    info = lifecycle.lookup(chosen_model) if chosen_model else None
    provider = (info.provider if info else None) or (
        provider_counts.most_common(1)[0][0] if provider_counts else None
    )
    env_var = env_counts.most_common(1)[0][0] if env_counts else None
    replacement = info.recommended_replacement if info else None
    return chosen_model, provider, env_var, replacement


def build_workflow_scaffold(name: str, path: Path) -> tuple[str, str | None]:
    """Build a YAML snippet for ``name``; return (snippet, detected_model)."""
    model, provider, env_var, replacement = _detect_primary(path)

    target_candidates = [replacement] if replacement else ["<target-model>"]

    workflow = {
        "description": f"TODO: describe what {name} does.",
        "run": {
            "command": f"TODO: command that runs {name} (reads its model from the env var below)",
            "input_path": f"evals/{name}.inputs.jsonl",
            "output_path": f".driftless/results/{name}.outputs.jsonl",
        },
        "model": {
            "provider": provider or "<provider>",
            "env_var": env_var or f"{name.upper()}_MODEL",
            "current": model or "<current-model>",
            "target_candidates": target_candidates,
        },
        "files": {
            "editable": [f"prompts/{name}.md"],
            "readonly": [],
        },
        "eval": {
            "labels_path": f"evals/{name}.labels.jsonl",
            "schema_path": f"schemas/{name}.schema.json",
        },
        "thresholds": {
            "min_f1": 0.90,
            "max_schema_error_rate": 0.01,
            "max_cost_increase": 0,
        },
        "migration": {
            "allow_prompt_edits": True,
            "max_iterations": 8,
            "holdout_required": True,
        },
    }

    snippet = yaml.safe_dump({"workflows": {name: workflow}}, sort_keys=False, default_flow_style=False)
    return snippet, model


def save_scaffold(name: str, snippet: str, *, cwd: Path | None = None) -> Path:
    cwd = (cwd or Path.cwd()).resolve()
    out_dir = cwd / ".driftless" / "configure"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}.yml"
    out_path.write_text(snippet, encoding="utf-8")
    return out_path
