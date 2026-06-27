"""Pre-run checks that catch foot-guns before a (possibly slow) harness run.

Today the only check is cross-provider safety: the harness overrides the model
*id* via ``model.env_var``, so swapping to a different provider's model only works
if the workflow routes provider-agnostically (LiteLLM/OpenRouter/gateway) or sets
``model.portable``. Otherwise the run fails mid-way with a confusing API error;
we'd rather warn up front.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .contract import Workflow
from .lifecycle import infer_provider


@dataclass
class ProviderPreflight:
    source_provider: str | None
    target_provider: str | None
    portable: bool
    warning: str | None

    @property
    def mismatch(self) -> bool:
        return bool(
            self.source_provider
            and self.target_provider
            and self.source_provider != self.target_provider
        )


def provider_preflight(
    workflow: Workflow, target_model: str, *, cwd: Path | None = None
) -> ProviderPreflight:
    """Warn when the target model's provider differs from the workflow's.

    Suppressed when the workflow is provider-portable (declared via
    ``model.portable`` or detected statically).
    """
    source = workflow.model.provider or infer_provider(workflow.model.current)
    target = infer_provider(target_model)

    portable = workflow.model.portable
    if not portable:
        # Only pay for a static scan when there's an apparent mismatch.
        if source and target and source != target:
            from .scanner import detect_portability

            portable = detect_portability(cwd)

    warning: str | None = None
    if source and target and source != target and not portable:
        warning = (
            f"Target '{target_model}' looks like provider '{target}', but the "
            f"workflow uses '{source}'. The harness only overrides the model id "
            f"(via model.env_var), so a cross-provider swap will fail unless your "
            f"code routes to '{target}' (e.g. LiteLLM/OpenRouter) — set "
            f"model.portable: true to silence this once routing is in place."
        )

    return ProviderPreflight(source, target, portable, warning)
