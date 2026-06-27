"""Provider model lifecycle data.

Seeded from a static JSON file today; structured to become a hosted,
regularly-updated database later (the SaaS layer in the proposal). The scanner
uses this to flag deprecated/retired model dependencies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_DATA_PATH = Path(__file__).parent / "data" / "model_lifecycle.json"

AT_RISK_STATUSES = {"deprecated", "retired"}

# Coarse capability ordering for opportunistic candidate selection. Higher =
# more capable. ``reasoning`` sits above frontier as a distinct, higher-effort
# tier. Used only to *propose* candidates; the real eval decides quality.
CAPABILITY_RANK = {"economy": 1, "balanced": 2, "frontier": 3, "reasoning": 4}


def capability_rank(tier: str | None) -> int:
    """Rank a capability tier (0 when unknown)."""
    return CAPABILITY_RANK.get(tier or "", 0)


@dataclass(frozen=True)
class Pricing:
    """Token pricing in USD per 1,000,000 tokens."""

    input_per_1m: float
    output_per_1m: float

    def cost_for(self, prompt_tokens: float, completion_tokens: float) -> float:
        return (
            prompt_tokens * self.input_per_1m + completion_tokens * self.output_per_1m
        ) / 1_000_000.0


@dataclass(frozen=True)
class ModelInfo:
    model: str
    provider: str
    status: str
    retirement_date: str | None = None
    recommended_replacement: str | None = None
    release_date: str | None = None
    capability_tier: str | None = None
    pricing: Pricing | None = None

    @property
    def at_risk(self) -> bool:
        return self.status in AT_RISK_STATUSES


class Lifecycle:
    def __init__(self, entries: list[ModelInfo]) -> None:
        self._by_model = {e.model: e for e in entries}

    def lookup(self, model: str) -> ModelInfo | None:
        if model in self._by_model:
            return self._by_model[model]
        # Tolerate dated/suffixed aliases: match the longest known prefix.
        candidates = [m for m in self._by_model if model.startswith(m)]
        if candidates:
            return self._by_model[max(candidates, key=len)]
        return None

    def status_of(self, model: str) -> str:
        info = self.lookup(model)
        return info.status if info else "unknown"

    def pricing_for(self, model: str) -> Pricing | None:
        info = self.lookup(model)
        return info.pricing if info else None

    def models(self) -> list[ModelInfo]:
        """All catalog entries (insertion order)."""
        return list(self._by_model.values())

    def __len__(self) -> int:
        return len(self._by_model)


def _parse_pricing(raw: dict | None) -> Pricing | None:
    if not raw:
        return None
    inp = raw.get("input_per_1m")
    out = raw.get("output_per_1m")
    if inp is None or out is None:
        return None
    return Pricing(input_per_1m=float(inp), output_per_1m=float(out))


def _entry_from_dict(m: dict) -> ModelInfo:
    return ModelInfo(
        model=m["model"],
        provider=m["provider"],
        status=m["status"],
        retirement_date=m.get("retirement_date"),
        recommended_replacement=m.get("recommended_replacement"),
        release_date=m.get("release_date"),
        capability_tier=m.get("capability_tier"),
        pricing=_parse_pricing(m.get("pricing")),
    )


@lru_cache(maxsize=1)
def load_lifecycle(path: Path | None = None) -> Lifecycle:
    data = json.loads((path or _DATA_PATH).read_text(encoding="utf-8"))
    entries = [_entry_from_dict(m) for m in data["models"]]
    return Lifecycle(entries)


# Prefix heuristics used when a model isn't in the catalog (e.g. a brand-new
# release). Ordered longest-first so e.g. "text-embedding-" beats nothing.
_PROVIDER_PREFIXES: tuple[tuple[str, str], ...] = (
    ("gpt-", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("text-davinci", "openai"),
    ("text-embedding", "openai"),
    ("chatgpt", "openai"),
    ("claude-", "anthropic"),
    ("gemini", "google"),
    ("models/gemini", "google"),
)


def infer_provider(model: str) -> str | None:
    """Best-effort provider for a model id: catalog first, then prefixes."""
    if not model:
        return None
    info = load_lifecycle().lookup(model)
    if info is not None:
        return info.provider
    lowered = model.lower()
    for prefix, provider in _PROVIDER_PREFIXES:
        if lowered.startswith(prefix):
            return provider
    return None
