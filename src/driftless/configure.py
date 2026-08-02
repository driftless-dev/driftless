"""Scaffold a migration-ready workflow contract from scan detections.

This is the "make migration-ready" onboarding step. We don't clobber an
existing curated ``driftless.yml`` (which would lose comments); instead we
generate a workflow snippet, prefilled from detections where possible, and save
it for the user to drop in.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from .errors import DriftlessError
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


def _first_relative(path: Path, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        matches = sorted(candidate for candidate in path.glob(pattern) if candidate.is_file())
        if matches:
            return matches[0].relative_to(path).as_posix()
    return None


def _detect_repo_shape(path: Path, name: str) -> dict[str, Any]:
    """Best-effort harness, dataset, prompt, and grading hints."""
    runner = _first_relative(
        path,
        (
            f"evals/run_{name}.py",
            "evals/run_eval.py",
            "evals/*eval*.py",
        ),
    )
    command = f"python3 {runner}" if runner else (
        f"TODO: command that runs {name} (reads its model from the env var below)"
    )
    input_path = _first_relative(
        path,
        (
            f"evals/{name}.inputs.jsonl",
            "evals/cases.jsonl",
            "evals/inputs.jsonl",
            "evals/*.jsonl",
        ),
    ) or f"evals/{name}.inputs.jsonl"
    output_path = "evals/outputs.jsonl" if runner else (
        f".driftless/results/{name}.outputs.jsonl"
    )
    editable = _first_relative(
        path,
        (
            f"prompts/{name}.md",
            "prompts/system.md",
            "prompts/*.md",
            "prompts/*.txt",
        ),
    ) or f"prompts/{name}.md"

    runner_text = ""
    if runner:
        runner_text = (path / runner).read_text(encoding="utf-8", errors="ignore")
    score_graded = any(
        marker in runner_text
        for marker in ('"score"', "'score'", '"passed"', "'passed'")
    )
    return {
        "command": command,
        "input_path": input_path,
        "output_path": output_path,
        "editable": editable,
        "score_graded": score_graded,
    }


def build_workflow_scaffold(name: str, path: Path) -> tuple[str, str | None]:
    """Build a YAML snippet for ``name``; return (snippet, detected_model)."""
    model, provider, env_var, replacement = _detect_primary(path)
    shape = _detect_repo_shape(path, name)

    target_candidates = [replacement] if replacement else ["<target-model>"]

    if shape["score_graded"]:
        eval_spec = {
            "id_field": "id",
            "score_field": "score",
            "cost_field": "cost",
        }
        thresholds = {
            "min_score": 0.90,
            "max_schema_error_rate": 0.01,
            "max_cost_increase": 0,
        }
    else:
        eval_spec = {
            "labels_path": f"evals/{name}.labels.jsonl",
            "schema_path": f"schemas/{name}.schema.json",
        }
        thresholds = {
            "min_f1": 0.90,
            "max_schema_error_rate": 0.01,
            "max_cost_increase": 0,
        }

    workflow = {
        "description": f"TODO: describe what {name} does.",
        "run": {
            "command": shape["command"],
            "input_path": shape["input_path"],
            "output_path": shape["output_path"],
        },
        "model": {
            "provider": provider or "<provider>",
            "env_var": env_var or f"{name.upper()}_MODEL",
            "current": model or "<current-model>",
            "target_candidates": target_candidates,
        },
        "files": {
            "editable": [shape["editable"]],
            "readonly": [],
        },
        "eval": eval_spec,
        "thresholds": thresholds,
        "migration": {
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


def placeholder_paths(value: Any, prefix: str = "") -> list[str]:
    """Return dotted paths containing unresolved scaffold placeholders."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            found.extend(placeholder_paths(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(placeholder_paths(item, f"{prefix}[{index}]"))
    elif isinstance(value, str):
        stripped = value.strip()
        if "TODO" in stripped or (stripped.startswith("<") and stripped.endswith(">")):
            found.append(prefix)
    return found


def apply_scaffold(
    name: str,
    snippet: str,
    *,
    contract_path: Path,
) -> Path:
    """Safely add a generated workflow without rewriting existing comments."""
    contract_path = contract_path.resolve()
    generated = yaml.safe_load(snippet)
    workflow = generated["workflows"][name]

    if not contract_path.exists():
        contract_path.parent.mkdir(parents=True, exist_ok=True)
        contract_path.write_text(snippet.replace("workflows:", "version: 1\nworkflows:", 1), encoding="utf-8")
        return contract_path

    text = contract_path.read_text(encoding="utf-8")
    try:
        current = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise DriftlessError(
            f"cannot apply scaffold to invalid YAML: {contract_path}",
            hint=str(exc),
        ) from exc
    if not isinstance(current, dict):
        raise DriftlessError(f"contract must be a YAML mapping: {contract_path}")
    workflows = current.get("workflows")
    if workflows is None:
        workflows = {}
    if not isinstance(workflows, dict):
        raise DriftlessError("contract workflows must be a mapping")
    if name in workflows:
        raise DriftlessError(
            f"workflow {name!r} already exists in {contract_path}",
            hint="edit the existing workflow or choose a different name",
        )

    block = yaml.safe_dump(
        {name: workflow},
        sort_keys=False,
        default_flow_style=False,
    )
    indented = "\n".join(f"  {line}" if line else line for line in block.rstrip().splitlines())

    lines = text.rstrip().splitlines()
    inline_index = next(
        (index for index, line in enumerate(lines) if line.strip() == "workflows: {}"),
        None,
    )
    if inline_index is not None:
        lines[inline_index] = f"{lines[inline_index].split('workflows:')[0]}workflows:"
        updated = "\n".join(lines) + "\n" + indented + "\n"
    elif "workflows" not in current:
        updated = text.rstrip() + "\n\nworkflows:\n" + indented + "\n"
    else:
        updated = text.rstrip() + "\n" + indented + "\n"

    contract_path.write_text(updated, encoding="utf-8")
    return contract_path
