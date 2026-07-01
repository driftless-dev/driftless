import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import fetch_provider_pricing as fpp  # noqa: E402


def _catalog(tmp_path: Path, models: list[dict]) -> Path:
    p = tmp_path / "cat.json"
    p.write_text(json.dumps({"models": models}), encoding="utf-8")
    return p


def test_litellm_lookup_openai_exact():
    table = {
        "gpt-4o": {
            "input_cost_per_token": 2.5e-6,
            "output_cost_per_token": 1e-5,
            "litellm_provider": "openai",
        }
    }
    pricing = fpp._litellm_lookup(table, "gpt-4o", "openai")
    assert pricing == {"input_per_1m": 2.5, "output_per_1m": 10.0}


def test_litellm_lookup_anthropic_prefix_match():
    table = {
        "claude-3-haiku-20240307": {
            "input_cost_per_token": 2.5e-7,
            "output_cost_per_token": 1.25e-6,
            "litellm_provider": "anthropic",
        }
    }
    pricing = fpp._litellm_lookup(table, "claude-3-haiku-20240307", "anthropic")
    assert pricing == {"input_per_1m": 0.25, "output_per_1m": 1.25}


def test_pricing_updates_skip_unchanged_and_unknown(tmp_path: Path):
    cat = _catalog(
        tmp_path,
        [
            {
                "model": "gpt-4o",
                "provider": "openai",
                "pricing": {"input_per_1m": 2.5, "output_per_1m": 10.0},
            },
            {"model": "gpt-4o-mini", "provider": "openai", "pricing": None},
            {"model": "missing-model", "provider": "openai"},
        ],
    )
    table = {
        "gpt-4o": {
            "input_cost_per_token": 2.5e-6,
            "output_cost_per_token": 1e-5,
            "litellm_provider": "openai",
        },
        "gpt-4o-mini": {
            "input_cost_per_token": 1.5e-7,
            "output_cost_per_token": 6e-7,
            "litellm_provider": "openai",
        },
    }
    updates = fpp.pricing_updates_from_litellm(
        catalog_path=cat, providers=["openai"], table=table
    )
    assert len(updates) == 1
    assert updates[0]["model"] == "gpt-4o-mini"
    assert updates[0]["pricing"]["input_per_1m"] == pytest.approx(0.15)


def test_overlay_nested_format(tmp_path: Path):
    cat = _catalog(
        tmp_path,
        [{"model": "gpt-4o", "provider": "openai", "pricing": {"input_per_1m": 1.0, "output_per_1m": 2.0}}],
    )
    overlay = tmp_path / "overlay.json"
    overlay.write_text(
        json.dumps({"openai": {"gpt-4o": {"input_per_1m": 2.5, "output_per_1m": 10.0}}}),
        encoding="utf-8",
    )
    updates = fpp.pricing_updates_from_overlay(
        catalog_path=cat, overlay_path=overlay, providers=["openai"]
    )
    assert len(updates) == 1
    assert updates[0]["pricing"]["output_per_1m"] == 10.0


def test_cli_writes_output(tmp_path: Path, monkeypatch):
    cat = _catalog(tmp_path, [{"model": "gpt-4o", "provider": "openai"}])
    out = tmp_path / "updates.json"
    monkeypatch.setattr(
        fpp,
        "fetch_pricing_updates",
        lambda **kw: [{"model": "gpt-4o", "provider": "openai", "pricing": {"input_per_1m": 1.0, "output_per_1m": 2.0}}],
    )
    assert (
        fpp.main(
            ["--source", "litellm", "--provider", "openai", "--catalog", str(cat), "-o", str(out)]
        )
        == 0
    )
    assert json.loads(out.read_text())[0]["model"] == "gpt-4o"
