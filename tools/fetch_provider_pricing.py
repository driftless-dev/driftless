#!/usr/bin/env python3
"""Refresh catalog pricing from a structured external source (P1.1).

Conservative merge policy: only emits ``pricing`` updates for model IDs that
**already exist** in the committed catalog and only when the fetched price
differs. Never changes lifecycle status, tiers, or adds new models.

Default source is LiteLLM's public ``model_prices_and_context_window.json``
(community-maintained; human review via the catalog refresh PR is required).

Examples::

  python tools/fetch_provider_pricing.py --source litellm \\
    --provider openai --provider anthropic \\
    --catalog src/driftless/data/model_lifecycle.json -o pricing.json

  python tools/fetch_provider_pricing.py --source pricing_overlay.json \\
    --catalog src/driftless/data/model_lifecycle.json -o pricing.json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_CATALOG = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "driftless"
    / "data"
    / "model_lifecycle.json"
)

LITELLM_PRICES_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)

_PRICE_EPS = 1e-6


def _http_get_json(url: str, *, timeout: float = 60.0) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"request failed for {url}: {exc.reason}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object from {url}")
    return payload


def _load_catalog_models(catalog_path: Path) -> list[dict[str, Any]]:
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    models = data.get("models")
    if not isinstance(models, list):
        raise RuntimeError("catalog must contain a 'models' array")
    return [m for m in models if isinstance(m, dict) and isinstance(m.get("model"), str)]


def _per_million(entry: dict[str, Any]) -> dict[str, float] | None:
    inp = entry.get("input_cost_per_token")
    out = entry.get("output_cost_per_token")
    if inp is None and out is None:
        return None
    return {
        "input_per_1m": float(inp or 0) * 1_000_000,
        "output_per_1m": float(out or 0) * 1_000_000,
    }


def _litellm_provider_matches(entry: dict[str, Any], provider: str) -> bool:
    raw = entry.get("litellm_provider")
    if not isinstance(raw, str):
        return provider == "openai"
    raw = raw.lower()
    if provider == "openai":
        return raw == "openai"
    if provider == "anthropic":
        return raw in {"anthropic", "bedrock"} or "anthropic" in raw
    return False


def _litellm_lookup(
    table: dict[str, Any], model_id: str, provider: str
) -> dict[str, float] | None:
    direct = table.get(model_id)
    if isinstance(direct, dict):
        pricing = _per_million(direct)
        if pricing and _litellm_provider_matches(direct, provider):
            return pricing

    if provider != "anthropic":
        return None

    # Anthropic ids in LiteLLM are often dated suffixes; pick the shortest exact
    # ``claude-…`` key that starts with our catalog id.
    candidates: list[tuple[str, dict[str, Any]]] = []
    for key, entry in table.items():
        if not isinstance(entry, dict):
            continue
        if not (key == model_id or key.startswith(f"{model_id}-")):
            continue
        if key.startswith(("bedrock/", "eu.", "us.", "apac.", "vertex_ai/")):
            continue
        if not _litellm_provider_matches(entry, provider):
            continue
        candidates.append((key, entry))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (len(t[0]), t[0]))
    return _per_million(candidates[0][1])


def _pricing_differs(
    current: dict[str, Any] | None, new: dict[str, float]
) -> bool:
    if not current:
        return True
    for key in ("input_per_1m", "output_per_1m"):
        cur = current.get(key)
        if cur is None:
            return True
        if abs(float(cur) - new[key]) > _PRICE_EPS:
            return True
    return False


def pricing_updates_from_litellm(
    *,
    catalog_path: Path,
    providers: list[str],
    table: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if table is None:
        table = _http_get_json(LITELLM_PRICES_URL)
    allowed = set(providers)
    updates: list[dict[str, Any]] = []
    for row in _load_catalog_models(catalog_path):
        provider = row.get("provider")
        model_id = row["model"]
        if provider not in allowed:
            continue
        fetched = _litellm_lookup(table, model_id, provider)
        if fetched is None:
            continue
        current = row.get("pricing")
        if isinstance(current, dict) and not _pricing_differs(current, fetched):
            continue
        updates.append(
            {
                "model": model_id,
                "provider": provider,
                "pricing": fetched,
            }
        )
    updates.sort(key=lambda m: (m.get("provider", ""), m["model"]))
    return updates


def _load_overlay(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        out: list[dict[str, Any]] = []
        for provider, models in data.items():
            if not isinstance(models, dict):
                continue
            for model_id, pricing in models.items():
                if isinstance(pricing, dict):
                    out.append(
                        {"model": model_id, "provider": provider, "pricing": pricing}
                    )
        return out
    raise RuntimeError("overlay must be a JSON array or {provider: {model: pricing}}")


def pricing_updates_from_overlay(
    *,
    catalog_path: Path,
    overlay_path: Path,
    providers: list[str] | None = None,
) -> list[dict[str, Any]]:
    allowed = set(providers) if providers else None
    catalog_by_id = {m["model"]: m for m in _load_catalog_models(catalog_path)}
    updates: list[dict[str, Any]] = []
    for row in _load_overlay(overlay_path):
        model_id = row.get("model")
        provider = row.get("provider")
        pricing = row.get("pricing")
        if not isinstance(model_id, str) or not isinstance(provider, str):
            continue
        if allowed is not None and provider not in allowed:
            continue
        if model_id not in catalog_by_id:
            continue
        if not isinstance(pricing, dict):
            continue
        norm = {
            "input_per_1m": float(pricing["input_per_1m"]),
            "output_per_1m": float(pricing["output_per_1m"]),
        }
        current = catalog_by_id[model_id].get("pricing")
        if isinstance(current, dict) and not _pricing_differs(current, norm):
            continue
        updates.append({"model": model_id, "provider": provider, "pricing": norm})
    updates.sort(key=lambda m: (m.get("provider", ""), m["model"]))
    return updates


def fetch_pricing_updates(
    *,
    source: str,
    catalog_path: Path,
    providers: list[str],
) -> list[dict[str, Any]]:
    if source == "litellm":
        return pricing_updates_from_litellm(catalog_path=catalog_path, providers=providers)
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(f"pricing source not found: {source}")
    return pricing_updates_from_overlay(
        catalog_path=catalog_path, overlay_path=path, providers=providers
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default="litellm",
        help="litellm (default) or path to a JSON pricing overlay",
    )
    parser.add_argument(
        "--provider",
        action="append",
        choices=["openai", "anthropic"],
        help="Limit to provider(s); repeat flag (default: both)",
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Write JSON array of pricing update entries here",
    )
    args = parser.parse_args(argv)
    providers = args.provider or ["openai", "anthropic"]

    if not args.catalog.is_file():
        print(f"catalog not found: {args.catalog}", file=sys.stderr)
        return 1

    try:
        updates = fetch_pricing_updates(
            source=args.source,
            catalog_path=args.catalog,
            providers=providers,
        )
    except (RuntimeError, FileNotFoundError, ValueError, KeyError) as exc:
        print(f"pricing fetch failed: {exc}", file=sys.stderr)
        return 1

    args.output.write_text(json.dumps(updates, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(updates)} pricing update(s) to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
