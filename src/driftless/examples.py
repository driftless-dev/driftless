"""Bundled example project helpers."""

from __future__ import annotations

from pathlib import Path
from shutil import copytree

import yaml

from .errors import DriftlessError


def examples_root() -> Path:
    """Return the bundled examples directory."""
    bundled = Path(__file__).resolve().parent / "examples"
    if bundled.is_dir():
        return bundled
    # Editable install: repo-root examples/
    return Path(__file__).resolve().parents[2] / "examples"


def available_examples() -> list[str]:
    root = examples_root()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))


def example_help_names() -> str:
    names = available_examples()
    return ", ".join(names) if names else "support-classifier, support-classifier-live, rag-qa, tool-agent"


def workflow_names_in(project: Path) -> list[str]:
    """Workflow keys from a copied example's contract, if readable."""
    for name in ("driftless.yml", "driftless.yaml"):
        path = project / name
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            return []
        if isinstance(data, dict) and isinstance(data.get("workflows"), dict):
            return [str(key) for key in data["workflows"]]
    return []


def copy_example(name: str, out_dir: Path, *, force: bool = False) -> Path:
    """Copy a bundled example project to ``out_dir``."""
    root = examples_root()
    source = root / name
    if not source.is_dir():
        choices = ", ".join(available_examples()) or "(none found)"
        raise DriftlessError(
            f"unknown example {name!r}",
            hint=f"available examples: {choices}",
        )
    if out_dir.exists() and not force:
        raise DriftlessError(
            f"{out_dir} already exists",
            hint="choose another --out-dir or pass --force to overwrite",
        )
    return copytree(source, out_dir, dirs_exist_ok=force)

