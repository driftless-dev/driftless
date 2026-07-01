#!/usr/bin/env python3
"""Fetch model IDs from provider /models APIs for catalog refresh (P1.1).

Conservative merge policy: only emits entries for model IDs returned by the
provider that are **not** already in the committed catalog. Never overwrites
lifecycle fields on existing entries — human review handles deprecations.

Outputs a JSON array suitable for ``refresh_catalog.py --updates``.

Examples::

  OPENAI_API_KEY=... python tools/fetch_provider_models.py \\
    --provider openai --catalog src/driftless/data/model_lifecycle.json \\
    -o updates.json

  python tools/fetch_provider_models.py --provider openai --provider anthropic \\
    --catalog src/driftless/data/model_lifecycle.json -o updates.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

DEFAULT_CATALOG = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "driftless"
    / "data"
    / "model_lifecycle.json"
)

OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"
ANTHROPIC_VERSION = "2023-06-01"

# Chat / embedding / reasoning ids we care about; skip infra (TTS, image, fine-tunes).
_OPENAI_KEEP_PREFIXES = ("gpt-", "o1", "o3", "o4", "text-embedding-", "chatgpt-")
_OPENAI_SKIP_PREFIXES = ("ft:", "tts-", "whisper-", "dall-e", "omni-moderation")


def _http_get_json(url: str, headers: dict[str, str], *, timeout: float = 30.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"request failed for {url}: {exc.reason}") from exc


def _openai_model_ids(api_key: str) -> list[str]:
    payload = _http_get_json(
        OPENAI_MODELS_URL,
        {"Authorization": f"Bearer {api_key}"},
    )
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise RuntimeError("OpenAI /models response missing 'data' array")
    ids: list[str] = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            ids.append(row["id"])
    return ids


def _anthropic_model_ids(api_key: str) -> list[str]:
    payload = _http_get_json(
        ANTHROPIC_MODELS_URL,
        {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        },
    )
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise RuntimeError("Anthropic /models response missing 'data' array")
    ids: list[str] = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            ids.append(row["id"])
    return ids


def _keep_openai(model_id: str) -> bool:
    if any(model_id.startswith(p) for p in _OPENAI_SKIP_PREFIXES):
        return False
    return any(model_id.startswith(p) for p in _OPENAI_KEEP_PREFIXES)


def _keep_anthropic(model_id: str) -> bool:
    return model_id.startswith("claude-")


def _load_known_ids(catalog_path: Path) -> dict[str, set[str]]:
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    by_provider: dict[str, set[str]] = {}
    for m in data.get("models", []):
        if not isinstance(m, dict):
            continue
        model_id = m.get("model")
        provider = m.get("provider")
        if isinstance(model_id, str) and isinstance(provider, str):
            by_provider.setdefault(provider, set()).add(model_id)
    return by_provider


def discover_new_models(
    *,
    provider: str,
    catalog_path: Path,
    fetch_ids: Callable[[str], list[str]],
    keep: Callable[[str], bool],
    api_key: str,
) -> list[dict[str, Any]]:
    known = _load_known_ids(catalog_path).get(provider, set())
    seen: set[str] = set()
    updates: list[dict[str, Any]] = []
    for model_id in fetch_ids(api_key):
        if model_id in known or model_id in seen or not keep(model_id):
            continue
        seen.add(model_id)
        updates.append(
            {
                "model": model_id,
                "provider": provider,
                "status": "active",
                "retirement_date": None,
                "recommended_replacement": None,
            }
        )
    updates.sort(key=lambda m: m["model"])
    return updates


def fetch_updates(
    providers: list[str],
    *,
    catalog_path: Path,
    openai_key: str | None = None,
    anthropic_key: str | None = None,
) -> list[dict[str, Any]]:
    """Return merged catalog update entries for the requested providers."""
    all_updates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for provider in providers:
        if provider == "openai":
            key = openai_key or os.environ.get("OPENAI_API_KEY")
            if not key:
                print("skip openai: OPENAI_API_KEY not set", file=sys.stderr)
                continue
            batch = discover_new_models(
                provider="openai",
                catalog_path=catalog_path,
                fetch_ids=_openai_model_ids,
                keep=_keep_openai,
                api_key=key,
            )
        elif provider == "anthropic":
            key = anthropic_key or os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                print("skip anthropic: ANTHROPIC_API_KEY not set", file=sys.stderr)
                continue
            batch = discover_new_models(
                provider="anthropic",
                catalog_path=catalog_path,
                fetch_ids=_anthropic_model_ids,
                keep=_keep_anthropic,
                api_key=key,
            )
        else:
            raise ValueError(f"unknown provider {provider!r} (expected openai or anthropic)")

        for entry in batch:
            mid = entry["model"]
            if mid not in seen_ids:
                seen_ids.add(mid)
                all_updates.append(entry)

    return all_updates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        action="append",
        choices=["openai", "anthropic"],
        required=True,
        help="Provider to query (repeatable)",
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Write JSON array of new model entries here",
    )
    args = parser.parse_args(argv)

    if not args.catalog.is_file():
        print(f"catalog not found: {args.catalog}", file=sys.stderr)
        return 1

    try:
        updates = fetch_updates(args.provider, catalog_path=args.catalog)
    except (RuntimeError, ValueError) as exc:
        print(f"fetch failed: {exc}", file=sys.stderr)
        return 1

    args.output.write_text(json.dumps(updates, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(updates)} new model(s) to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
