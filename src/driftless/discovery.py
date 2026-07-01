"""Candidate discovery: turn the world into migration triggers.

Today this implements the **deprecation** trigger only -- the one whose data we
already have (``lifecycle.py``). For each workflow in the contract, if the
current model is deprecated/retired, we emit a :class:`~driftless.policy.Trigger`
with the recommended replacement (or a declared ``target_candidate``) as the
candidate, and the days-until-retirement computed from the lifecycle date.

Cost / quality / new-model discovery will plug in here later once a richer model
catalog (pricing, release dates) exists; the policy decision layer already
supports them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .contract import Contract
from .datastate import (
    DatasetState,
    SignatureDelta,
    dataset_signature,
    load_state,
    signature_delta,
)
from .lifecycle import Lifecycle, ModelInfo, Pricing, capability_rank, load_lifecycle
from .policy import (
    DataChangePolicy,
    Policy,
    Trigger,
    TriggerKind,
    candidate_filter_reason,
    is_meaningful_change,
)


@dataclass
class DiscoveredTrigger:
    """A trigger plus the workflow and lifecycle context it came from."""

    workflow: str
    trigger: Trigger
    info: ModelInfo


@dataclass
class DataChangeTrigger:
    """A workflow whose eval dataset changed since the last refine.

    Unlike model triggers there's no candidate model -- the model is pinned and
    the *dataset* is the thing that drifted, so the action is always ``refine``.
    """

    workflow: str
    new_fingerprint: str
    last_fingerprint: str | None  # None when never seen before (first run)
    delta: SignatureDelta | None = None  # row-level change vs. last seen

    @property
    def first_seen(self) -> bool:
        return self.last_fingerprint is None

    @property
    def changed_rows(self) -> int:
        return self.delta.total if self.delta else 0


def _days_until(retirement_date: str | None, as_of: date) -> int | None:
    if not retirement_date:
        return None
    try:
        return (date.fromisoformat(retirement_date) - as_of).days
    except ValueError:
        return None


def discover_deprecation_triggers(
    contract: Contract,
    *,
    lifecycle: Lifecycle | None = None,
    as_of: date | None = None,
) -> list[DiscoveredTrigger]:
    """Find workflows whose current model is deprecated/retired."""
    lifecycle = lifecycle or load_lifecycle()
    as_of = as_of or date.today()

    discovered: list[DiscoveredTrigger] = []
    for name, wf in contract.workflows.items():
        info = lifecycle.lookup(wf.model.current)
        if info is None or not info.at_risk:
            continue

        candidate = info.recommended_replacement
        if not candidate and wf.model.target_candidates:
            candidate = wf.model.target_candidates[0]
        if not candidate:
            # At risk but we have nowhere to send it; still worth surfacing, but
            # there's no migration to attempt, so skip trigger emission for now.
            continue

        trigger = Trigger(
            kind=TriggerKind.DEPRECATION,
            current_model=wf.model.current,
            candidate_model=candidate,
            days_until_retirement=_days_until(info.retirement_date, as_of),
        )
        discovered.append(DiscoveredTrigger(workflow=name, trigger=trigger, info=info))
    return discovered


# --------------------------------------------------------------------------- #
# Opportunistic triggers (cost / quality / new_model)
# --------------------------------------------------------------------------- #
def _blended_cost(pricing: Pricing | None) -> float | None:
    """A monotonic price proxy for candidate selection (input + output / 1M)."""
    if pricing is None:
        return None
    return pricing.input_per_1m + pricing.output_per_1m


def estimate_cost_change_pct(
    current: str, candidate: str, lifecycle: Lifecycle | None = None
) -> float | None:
    """Catalog-estimated cost change of candidate vs current (negative = cheaper).

    Assumes comparable token usage across models (same prompt/task), so this is a
    *selection* signal; the policy prefers measured cost when the workflow emits
    it. ``None`` when either price is unknown.
    """
    lifecycle = lifecycle or load_lifecycle()
    cur = _blended_cost(lifecycle.pricing_for(current))
    cand = _blended_cost(lifecycle.pricing_for(candidate))
    if cur is None or cand is None or cur == 0:
        return None
    return (cand - cur) / cur


def _release_date(info: ModelInfo) -> date | None:
    if not info.release_date:
        return None
    try:
        return date.fromisoformat(info.release_date)
    except ValueError:
        return None


def _is_alias(a: str, b: str) -> bool:
    """True if one id is a dated/versioned snapshot of the other.

    e.g. ``claude-3-5-sonnet`` vs ``claude-3-5-sonnet-20241022``. Avoids treating
    genuinely-distinct models (``gpt-4o`` vs ``gpt-4o-mini``) as aliases.
    """
    if a == b:
        return True
    lo, hi = (a, b) if len(a) <= len(b) else (b, a)
    if hi.startswith(lo + "-"):
        suffix = hi[len(lo) + 1 :]
        return suffix[:1].isdigit()  # a version/date snapshot, not a new model
    return False


def _is_generative(info: ModelInfo) -> bool:
    """Exclude embedding-style models (no output tokens) from chat candidates."""
    return info.pricing is None or info.pricing.output_per_1m > 0


def _within_cooldown(info: ModelInfo, as_of: date, cooldown_days: int | None) -> bool:
    """True if ``info`` was released too recently to chase opportunistically."""
    if not cooldown_days:
        return False
    released = _release_date(info)
    if released is None:
        return False
    return (as_of - released).days < cooldown_days


def discover_opportunistic_triggers(
    contract: Contract,
    *,
    lifecycle: Lifecycle | None = None,
    policy: Policy | None = None,
    as_of: date | None = None,
) -> list[DiscoveredTrigger]:
    """Propose cost / quality / new-model candidates for *active* baselines.

    Conservative by design: candidates are same-provider, active, and never lower
    capability than the current model (we don't auto-propose a downgrade). Only
    policy-enabled trigger kinds are emitted, denied/snoozed candidates are
    filtered, freshly-released models inside ``policy.cooldown_days`` are held
    back, and at most one candidate per kind per workflow is returned (the best),
    deduped across kinds by priority cost > quality > new_model. Each is still
    gated on a real eval + policy in ``plan``.
    """
    lifecycle = lifecycle or load_lifecycle()
    policy = policy or Policy()
    as_of = as_of or date.today()

    enabled = {
        TriggerKind.COST: policy.cost.enabled,
        TriggerKind.QUALITY: policy.quality.enabled,
        TriggerKind.NEW_MODEL: policy.new_model.enabled,
    }
    if not any(enabled.values()):
        return []

    discovered: list[DiscoveredTrigger] = []
    for name, wf in contract.workflows.items():
        cur = lifecycle.lookup(wf.model.current)
        # Opportunistic moves need an active, known baseline to reason about;
        # at-risk models are handled by the (forced) deprecation path.
        if cur is None or cur.at_risk:
            continue
        cur_rank = capability_rank(cur.capability_tier)
        cur_release = _release_date(cur)
        cur_blended = _blended_cost(cur.pricing)

        pool = [
            m
            for m in lifecycle.models()
            if m.status == "active"
            and m.provider == cur.provider
            and _is_generative(m)
            and not _is_alias(m.model, cur.model)
            and not _is_alias(m.model, wf.model.current)
            and not _within_cooldown(m, as_of, policy.cooldown_days)
            and candidate_filter_reason(wf.model.current, m.model, policy) is None
        ]

        picks: dict[TriggerKind, ModelInfo] = {}

        if enabled[TriggerKind.COST] and cur_blended:
            cost_qualifying: list[tuple[float, ModelInfo]] = []
            for m in pool:
                b = _blended_cost(m.pricing)
                if b is None or capability_rank(m.capability_tier) < cur_rank:
                    continue
                savings = (cur_blended - b) / cur_blended
                if savings >= policy.cost.min_savings_pct:
                    cost_qualifying.append((savings, m))
            if cost_qualifying:
                picks[TriggerKind.COST] = max(cost_qualifying, key=lambda t: t[0])[1]

        if enabled[TriggerKind.QUALITY]:
            quality_qualifying = [
                m for m in pool if capability_rank(m.capability_tier) > cur_rank
            ]
            if quality_qualifying:
                picks[TriggerKind.QUALITY] = min(
                    quality_qualifying,
                    key=lambda m: (
                        -capability_rank(m.capability_tier),
                        _blended_cost(m.pricing) or float("inf"),
                    ),
                )

        if enabled[TriggerKind.NEW_MODEL] and cur_release is not None:
            new_model_qualifying = [
                m
                for m in pool
                if capability_rank(m.capability_tier) >= cur_rank
                and (rd := _release_date(m)) is not None
                and rd > cur_release
            ]
            if new_model_qualifying:
                picks[TriggerKind.NEW_MODEL] = max(
                    new_model_qualifying,
                    key=lambda m: (_release_date(m), -(_blended_cost(m.pricing) or 0.0)),
                )

        # Dedupe across kinds by candidate, keeping the highest-priority kind.
        chosen: set[str] = set()
        for kind in (TriggerKind.COST, TriggerKind.QUALITY, TriggerKind.NEW_MODEL):
            candidate = picks.get(kind)
            if candidate is None or candidate.model in chosen:
                continue
            chosen.add(candidate.model)
            discovered.append(
                DiscoveredTrigger(
                    workflow=name,
                    trigger=Trigger(
                        kind=kind,
                        current_model=wf.model.current,
                        candidate_model=candidate.model,
                    ),
                    info=cur,
                )
            )
    return discovered


# --------------------------------------------------------------------------- #
# Grouping (noise control): batch the same model move across workflows
# --------------------------------------------------------------------------- #
@dataclass
class TriggerGroup:
    """The same ``current -> candidate`` move shared by one or more workflows.

    Grouping lets the bot reason about (and later open) one logical migration per
    move instead of N near-identical PRs, which is the main source of noise once
    opportunistic triggers are on.
    """

    current_model: str
    candidate_model: str
    kind: TriggerKind
    triggers: list[DiscoveredTrigger]

    @property
    def workflows(self) -> list[str]:
        return [t.workflow for t in self.triggers]


def group_triggers(triggers: list[DiscoveredTrigger]) -> list[TriggerGroup]:
    """Cluster triggers by ``(current, candidate, kind)`` move, order preserved."""
    groups: dict[tuple[str, str, TriggerKind], TriggerGroup] = {}
    order: list[tuple[str, str, TriggerKind]] = []
    for t in triggers:
        key = (t.trigger.current_model, t.trigger.candidate_model, t.trigger.kind)
        if key not in groups:
            groups[key] = TriggerGroup(key[0], key[1], key[2], [])
            order.append(key)
        groups[key].triggers.append(t)
    return [groups[k] for k in order]


def _within_debounce(prev: DatasetState | None, as_of: date, days: int | None) -> bool:
    """True if the last processed change is too recent to re-fire (debounce)."""
    if not days or prev is None or not prev.updated_at:
        return False
    try:
        last = date.fromisoformat(prev.updated_at[:10])
    except ValueError:
        return False
    return (as_of - last).days < days


def discover_data_change_triggers(
    contract: Contract,
    *,
    cwd: Path | None = None,
    state: dict[str, DatasetState] | None = None,
    policy: DataChangePolicy | None = None,
    as_of: date | None = None,
    include_first_seen: bool = False,
) -> list[DataChangeTrigger]:
    """Find workflows whose eval dataset *meaningfully* drifted since last refine.

    Used by the *external-data* poll: fingerprint each workflow's dataset and
    compare against ``.driftless/state.json``. A bare fingerprint change isn't
    enough -- the row-level delta must clear the policy's meaningful-change gate
    (``min_changed_rows`` / ``min_changed_fraction``) and the debounce
    (``min_days_between``), so whitespace, reordering, or a row or two stay quiet.

    By default a first-ever sighting is treated as a baseline (recorded by the
    caller, not triggered) so a fresh checkout doesn't refine everything; pass
    ``include_first_seen=True`` to also surface those. (For *in-repo* data, prefer
    a path-filtered Action -- git is a better change detector.)
    """
    cwd = (cwd or Path.cwd()).resolve()
    state = load_state(cwd=cwd) if state is None else state
    policy = policy if policy is not None else DataChangePolicy()
    as_of = as_of or date.today()

    if not policy.enabled:
        return []

    triggers: list[DataChangeTrigger] = []
    for name, wf in contract.workflows.items():
        if not wf.eval.labels_path:
            # No gold labels -> nothing to optimize toward; skip.
            continue
        new_sig = dataset_signature(wf, cwd=cwd)
        prev = state.get(name)
        last_fp = prev.fingerprint if prev else None
        if last_fp == new_sig.fingerprint:
            continue
        if last_fp is None and not include_first_seen:
            continue

        delta = signature_delta(prev.signature if prev else None, new_sig)
        # First sighting (when surfaced) bypasses the gate; otherwise require a
        # meaningful change that isn't within the debounce window.
        if last_fp is not None:
            if _within_debounce(prev, as_of, policy.min_days_between):
                continue
            if not is_meaningful_change(delta, policy):
                continue

        triggers.append(
            DataChangeTrigger(
                workflow=name,
                new_fingerprint=new_sig.fingerprint,
                last_fingerprint=last_fp,
                delta=delta,
            )
        )
    return triggers
