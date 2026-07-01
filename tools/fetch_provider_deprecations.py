#!/usr/bin/env python3
"""Suggest lifecycle updates for catalog models (P1.1 deprecation refresh).

Conservative merge policy — only emits updates for model IDs **already in** the
committed catalog, and only when the fetched signal would **increase lifecycle
severity** (``active`` → ``deprecated`` → ``retired``) or fill in a missing
``retirement_date`` / ``recommended_replacement``. Never downgrades status and
never adds new models (that remains ``fetch_provider_models.py``).

Two signal sources (both optional at runtime):

* **Deprecation docs** — lightweight HTML scrape of provider deprecation pages;
  looks for catalog model ids and nearby dates / status language.
* **Models API diff** — when API keys are set, flags ``active`` catalog models
  that no longer appear on the provider ``/models`` list (including dated
  snapshot ids).

Examples::

  python tools/fetch_provider_deprecations.py \\
    --provider openai --provider anthropic \\
    --catalog src/driftless/data/model_lifecycle.json -o deprecations.json

Human review via the catalog refresh PR is required — pages and APIs change.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import fetch_provider_models as fpm  # noqa: E402

DEFAULT_CATALOG = fpm.DEFAULT_CATALOG

OPENAI_DEPRECATIONS_URL = "https://developers.openai.com/api/docs/deprecations"
ANTHROPIC_DEPRECATIONS_URL = (
    "https://docs.anthropic.com/en/docs/about-claude/model-deprecations"
)
GOOGLE_DEPRECATIONS_URL = "https://ai.google.dev/gemini-api/docs/changelog"

_USER_AGENT = "driftless-catalog-refresh/1.0 (+https://github.com/driftless-dev/driftless)"
_DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}")
_STATUS_RANK = {"active": 0, "deprecated": 1, "retired": 2}


def _http_get_text(url: str, *, timeout: float = 60.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"request failed for {url}: {exc.reason}") from exc


def _load_catalog_models(catalog_path: Path) -> list[dict[str, Any]]:
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    models = data.get("models")
    if not isinstance(models, list):
        raise RuntimeError("catalog must contain a 'models' array")
    return [m for m in models if isinstance(m, dict) and isinstance(m.get("model"), str)]


def _known_model_ids(catalog_path: Path) -> set[str]:
    return {m["model"] for m in _load_catalog_models(catalog_path)}


def _api_covers_model(model_id: str, api_ids: set[str]) -> bool:
    if model_id in api_ids:
        return True
    dated_prefix = model_id + "-"
    for aid in api_ids:
        if aid.startswith(dated_prefix):
            return True
        if model_id.startswith(aid + "-"):
            return True
    return False


def _page_status_near(html_lower: str, pos: int, *, window: int = 350) -> str | None:
    chunk = html_lower[pos : pos + window]
    if any(w in chunk for w in ("deprecated", "deprecation", "deprecating")):
        return "deprecated"
    if any(w in chunk for w in ("retired", "shutdown", "end of life", "end-of-life")):
        return "retired"
    return None


def _page_date_near(html: str, pos: int, *, window: int = 450) -> str | None:
    chunk = html[pos : pos + window]
    match = _DATE_RE.search(chunk)
    return match.group(0) if match else None


def _page_replacement_near(
    html: str,
    pos: int,
    *,
    source_model: str,
    known_ids: set[str],
    window: int = 600,
) -> str | None:
    chunk = html[pos : pos + window]
    candidates = [mid for mid in known_ids if mid != source_model and mid in chunk]
    if not candidates:
        return None
    candidates.sort(key=len, reverse=True)
    return candidates[0]


def parse_deprecation_page(
    html: str,
    *,
    provider: str,
    catalog_models: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract lifecycle hints for catalog models mentioned on a deprecation page."""
    known_ids = {m["model"] for m in catalog_models}
    html_lower = html.lower()
    hints: dict[str, dict[str, Any]] = {}

    for row in catalog_models:
        if row.get("provider") != provider:
            continue
        model_id = row["model"]
        pos = html.find(model_id)
        if pos < 0:
            continue
        hint: dict[str, Any] = {"model": model_id, "provider": provider}
        status = _page_status_near(html_lower, pos)
        if status:
            hint["status"] = status
        retirement = _page_date_near(html, pos)
        if retirement:
            hint["retirement_date"] = retirement
        replacement = _page_replacement_near(
            html, pos, source_model=model_id, known_ids=known_ids
        )
        if replacement:
            hint["recommended_replacement"] = replacement
        if len(hint) > 2:
            hints[model_id] = hint

    return sorted(hints.values(), key=lambda m: m["model"])


def discover_models_api_absence(
    *,
    provider: str,
    catalog_path: Path,
    api_ids: list[str],
    keep: Callable[[str], bool],
) -> list[dict[str, Any]]:
    """Flag active catalog models missing from a live /models listing."""
    live = {mid for mid in api_ids if keep(mid)}
    updates: list[dict[str, Any]] = []
    for row in _load_catalog_models(catalog_path):
        if row.get("provider") != provider:
            continue
        if row.get("status") != "active":
            continue
        model_id = row["model"]
        if _api_covers_model(model_id, live):
            continue
        updates.append(
            {
                "model": model_id,
                "provider": provider,
                "status": "deprecated",
            }
        )
    return updates


def _active_replacement(model_id: str, catalog_by_id: dict[str, dict[str, Any]]) -> bool:
    row = catalog_by_id.get(model_id)
    return isinstance(row, dict) and row.get("status") == "active"


def _merge_hint_fields(
    current: dict[str, Any],
    hint: dict[str, Any],
    *,
    catalog_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Return a catalog update entry if ``hint`` would change ``current``."""
    out: dict[str, Any] = {
        "model": current["model"],
        "provider": current.get("provider"),
    }
    changed = False

    cur_status = current.get("status", "active")
    new_status = hint.get("status")
    if isinstance(new_status, str):
        if _STATUS_RANK.get(new_status, -1) > _STATUS_RANK.get(cur_status, -1):
            out["status"] = new_status
            changed = True

    for field in ("retirement_date", "recommended_replacement"):
        if field not in hint:
            continue
        new_val = hint[field]
        if field == "recommended_replacement" and isinstance(new_val, str):
            if not _active_replacement(new_val, catalog_by_id):
                continue
        cur_val = current.get(field)
        if cur_val in (None, "") and new_val not in (None, ""):
            out[field] = new_val
            changed = True

    return out if changed else None


def consolidate_deprecation_hints(
    catalog_path: Path,
    hints: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge raw hints onto the catalog; keep only entries that would change it."""
    by_id = {m["model"]: m for m in _load_catalog_models(catalog_path)}
    merged: dict[str, dict[str, Any]] = {}

    for hint in hints:
        model_id = hint.get("model")
        if not isinstance(model_id, str) or model_id not in by_id:
            continue
        current = by_id[model_id]
        update = _merge_hint_fields(current, hint, catalog_by_id=by_id)
        if not update:
            continue
        if model_id in merged:
            prev = merged[model_id]
            prev_status = prev.get("status", current.get("status"))
            new_status = update.get("status", prev_status)
            if _STATUS_RANK.get(new_status, -1) > _STATUS_RANK.get(prev_status, -1):
                prev["status"] = new_status
            for field in ("retirement_date", "recommended_replacement"):
                if field in update and field not in prev:
                    prev[field] = update[field]
        else:
            merged[model_id] = update

    return sorted(merged.values(), key=lambda m: (m.get("provider", ""), m["model"]))


def fetch_deprecation_page_hints(
    providers: list[str],
    *,
    catalog_path: Path,
    fetch_html: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    fetch_html = fetch_html or _http_get_text
    catalog_models = _load_catalog_models(catalog_path)
    hints: list[dict[str, Any]] = []

    urls = {
        "openai": OPENAI_DEPRECATIONS_URL,
        "anthropic": ANTHROPIC_DEPRECATIONS_URL,
        "google": GOOGLE_DEPRECATIONS_URL,
    }
    for provider in providers:
        url = urls.get(provider)
        if not url:
            continue
        try:
            html = fetch_html(url)
        except RuntimeError as exc:
            print(f"skip {provider} deprecation page: {exc}", file=sys.stderr)
            continue
        hints.extend(
            parse_deprecation_page(html, provider=provider, catalog_models=catalog_models)
        )
    return hints


def fetch_models_api_hints(
    providers: list[str],
    *,
    catalog_path: Path,
    openai_key: str | None = None,
    anthropic_key: str | None = None,
) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    for provider in providers:
        if provider == "openai":
            key = openai_key or os.environ.get("OPENAI_API_KEY")
            if not key:
                print("skip openai /models diff: OPENAI_API_KEY not set", file=sys.stderr)
                continue
            try:
                api_ids = fpm._openai_model_ids(key)
            except RuntimeError as exc:
                print(f"skip openai /models diff: {exc}", file=sys.stderr)
                continue
            hints.extend(
                discover_models_api_absence(
                    provider="openai",
                    catalog_path=catalog_path,
                    api_ids=api_ids,
                    keep=fpm._keep_openai,
                )
            )
        elif provider == "anthropic":
            key = anthropic_key or os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                print("skip anthropic /models diff: ANTHROPIC_API_KEY not set", file=sys.stderr)
                continue
            try:
                api_ids = fpm._anthropic_model_ids(key)
            except RuntimeError as exc:
                print(f"skip anthropic /models diff: {exc}", file=sys.stderr)
                continue
            hints.extend(
                discover_models_api_absence(
                    provider="anthropic",
                    catalog_path=catalog_path,
                    api_ids=api_ids,
                    keep=fpm._keep_anthropic,
                )
            )
        elif provider == "google":
            key = fpm._google_api_key()
            if not key:
                print(
                    "skip google /models diff: GEMINI_API_KEY or GOOGLE_API_KEY not set",
                    file=sys.stderr,
                )
                continue
            try:
                api_ids = fpm._google_model_ids(key)
            except RuntimeError as exc:
                print(f"skip google /models diff: {exc}", file=sys.stderr)
                continue
            hints.extend(
                discover_models_api_absence(
                    provider="google",
                    catalog_path=catalog_path,
                    api_ids=api_ids,
                    keep=fpm._keep_google,
                )
            )
        else:
            raise ValueError(
                f"unknown provider {provider!r} (expected openai, anthropic, or google)"
            )
    return hints


def fetch_updates(
    providers: list[str],
    *,
    catalog_path: Path,
    skip_pages: bool = False,
    skip_models_api: bool = False,
    fetch_html: Callable[[str], str] | None = None,
    openai_key: str | None = None,
    anthropic_key: str | None = None,
) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    if not skip_pages:
        hints.extend(
            fetch_deprecation_page_hints(
                providers, catalog_path=catalog_path, fetch_html=fetch_html
            )
        )
    if not skip_models_api:
        hints.extend(
            fetch_models_api_hints(
                providers,
                catalog_path=catalog_path,
                openai_key=openai_key,
                anthropic_key=anthropic_key,
            )
        )
    return consolidate_deprecation_hints(catalog_path, hints)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        action="append",
        choices=["openai", "anthropic", "google"],
        required=True,
        help="Provider to query (repeatable)",
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument(
        "--skip-pages",
        action="store_true",
        help="Do not scrape provider deprecation documentation",
    )
    parser.add_argument(
        "--skip-models-api",
        action="store_true",
        help="Do not diff against provider /models listings",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Write JSON array of lifecycle update entries here",
    )
    args = parser.parse_args(argv)

    if not args.catalog.is_file():
        print(f"catalog not found: {args.catalog}", file=sys.stderr)
        return 1

    try:
        updates = fetch_updates(
            args.provider,
            catalog_path=args.catalog,
            skip_pages=args.skip_pages,
            skip_models_api=args.skip_models_api,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"deprecation fetch failed: {exc}", file=sys.stderr)
        return 1

    args.output.write_text(json.dumps(updates, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(updates)} lifecycle update(s) to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
