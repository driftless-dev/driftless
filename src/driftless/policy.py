"""Migration trigger policy: *when* should a migration be proposed?

This is the "Dependabot config" layer. The rest of the tool answers *can* we
migrate (compare + engine + holdout); this module answers *should* we, and *how
loudly*, given a trigger and the measured outcome of evaluating the candidate.

The central asymmetry vs. dependency bots: a trigger is only a **candidate**.
"Newer / cheaper / recommended" says nothing about whether the model still works
for *this* workflow -- that's decided by running the user's eval. So every
opportunistic trigger is gated on an :class:`EvalOutcome`, while the forced
trigger (deprecation) always surfaces *something* because there's a deadline.

Tiers:

* **Tier 1 - forced**: ``deprecation`` (deadline-driven; always surfaces, even
  when auto-repair fails -> opens an issue). The "security update" analog.
* **Tier 2 - opportunistic**: ``cost`` / ``quality`` / ``new_model`` (only open a
  PR when the candidate passes thresholds *and* materially wins).

This module is intentionally pure (no I/O) and not yet wired into the CLI; it's
the decision core you can call from `scan`/CI once candidate discovery exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fnmatch import fnmatch
from pathlib import Path

import yaml
from pydantic import Field, ValidationError

from .contract import StrictModel
from .errors import DriftlessError


# --------------------------------------------------------------------------- #
# Inputs: the trigger and the measured outcome
# --------------------------------------------------------------------------- #
class TriggerKind(str, Enum):
    DEPRECATION = "deprecation"
    COST = "cost"
    QUALITY = "quality"
    NEW_MODEL = "new_model"


@dataclass
class Trigger:
    """A reason a migration *might* be warranted, plus its candidate model."""

    kind: TriggerKind
    current_model: str
    candidate_model: str
    # Deprecation only: days until the current model is retired (None = retired
    # already, or date unknown).
    days_until_retirement: int | None = None


@dataclass
class EvalOutcome:
    """The measured result of evaluating the candidate through the workflow.

    Produced (in real use) from a :class:`~driftless.engine.MigrationResult`.
    Deltas are candidate-minus-baseline: ``f1_delta`` positive = better quality;
    ``cost_change_pct`` negative = cheaper.
    """

    passed_thresholds: bool
    migration_status: str  # model_change_only | pass | partial | blocked
    has_committed_change: bool = False
    f1_delta: float | None = None
    cost_change_pct: float | None = None
    latency_change_pct: float | None = None

    @property
    def shippable(self) -> bool:
        """A candidate we could actually open a PR for (passed + something to ship)."""
        return self.passed_thresholds and self.migration_status in {"pass", "model_change_only"}


# --------------------------------------------------------------------------- #
# Policy (the dependabot.yml analog)
# --------------------------------------------------------------------------- #
class Action(str, Enum):
    PR = "pr"
    ISSUE = "issue"
    NOTIFY = "notify"
    SKIP = "skip"


class Urgency(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TriggerSettings(StrictModel):
    enabled: bool = True
    action: Action = Action.PR  # what to do on a qualifying, shippable candidate


class DeprecationPolicy(TriggerSettings):
    # Start surfacing this many days before retirement; earlier than that is too
    # noisy. ``None`` = always surface deprecated models regardless of date.
    warn_before_days: int | None = 90


class CostPolicy(TriggerSettings):
    enabled: bool = True
    min_savings_pct: float = 0.20  # require >= 20% cheaper
    max_quality_drop: float = 0.01  # tolerate <= 1 F1 point of regression


class QualityPolicy(TriggerSettings):
    enabled: bool = False  # opt-in: quality chasing is noisier
    min_gain: float = 0.02  # require >= 2 F1 points of improvement


class NewModelPolicy(TriggerSettings):
    enabled: bool = False  # "newer" alone isn't a reason; must also win on cost/quality
    min_savings_pct: float = 0.0
    min_gain: float = 0.0


class CandidateFilter(StrictModel):
    allow: list[str] = Field(default_factory=lambda: ["*"])
    deny: list[str] = Field(default_factory=lambda: ["*-preview", "*-exp*", "*-alpha*"])


class DataChangePolicy(StrictModel):
    """When should a *dataset* change trigger a `refine` (vs. stay quiet)?

    The dataset-drift analog of the opportunistic gates: don't fire on
    whitespace, reordering, or a row or two. Require a substantive change and
    debounce so continuous feedback ingestion doesn't spam refine PRs.
    """

    enabled: bool = True
    # Fire only when at least this many labeled rows were added/removed/changed
    # ("every +N examples"). Set 1 to fire on any real change.
    min_changed_rows: int = 5
    # ...or when the changed fraction of the dataset is at least this (0 = off).
    min_changed_fraction: float = 0.0
    # Debounce: don't re-fire within this many days of the last processed change
    # (None = off; the CI cron cadence is the coarse debounce).
    min_days_between: int | None = None
    action: Action = Action.PR


def is_meaningful_change(delta, policy: "DataChangePolicy") -> bool:
    """True when a dataset delta clears the meaningful-change gate.

    ``delta`` is a :class:`driftless.datastate.SignatureDelta` (duck-typed to
    keep this module I/O- and import-free).
    """
    n = delta.total
    if n <= 0:
        return False
    if n >= policy.min_changed_rows:
        return True
    if policy.min_changed_fraction > 0 and delta.fraction >= policy.min_changed_fraction:
        return True
    return False


class Policy(StrictModel):
    """Per-repo migration policy. Mirrors the spirit of ``dependabot.yml``."""

    deprecation: DeprecationPolicy = Field(default_factory=DeprecationPolicy)
    cost: CostPolicy = Field(default_factory=CostPolicy)
    quality: QualityPolicy = Field(default_factory=QualityPolicy)
    new_model: NewModelPolicy = Field(default_factory=NewModelPolicy)
    # Dataset-drift trigger for `refine` (the external-data poll's gate).
    data_change: DataChangePolicy = Field(default_factory=DataChangePolicy)
    candidates: CandidateFilter = Field(default_factory=CandidateFilter)
    # Snoozed candidates: globs matched against the candidate model id or a
    # "current->candidate" pair (Dependabot's `ignore`).
    ignore: list[str] = Field(default_factory=list)
    # Don't propose *opportunistic* moves to models released within this many days
    # -- let brand-new releases stabilize (pricing, availability, quirks) before
    # the bot chases them. Forced deprecation triggers ignore this. None = off.
    cooldown_days: int | None = 14

    def settings_for(self, kind: TriggerKind) -> TriggerSettings:
        return {
            TriggerKind.DEPRECATION: self.deprecation,
            TriggerKind.COST: self.cost,
            TriggerKind.QUALITY: self.quality,
            TriggerKind.NEW_MODEL: self.new_model,
        }[kind]


# --------------------------------------------------------------------------- #
# Decision
# --------------------------------------------------------------------------- #
@dataclass
class Decision:
    action: Action
    urgency: Urgency
    trigger: TriggerKind
    reason: str

    @property
    def should_act(self) -> bool:
        return self.action is not Action.SKIP


def _skip(trigger: TriggerKind, reason: str) -> Decision:
    return Decision(Action.SKIP, Urgency.NONE, trigger, reason)


def candidate_filter_reason(
    current_model: str, candidate_model: str, policy: Policy
) -> str | None:
    """Return a reason string if the candidate is denied/snoozed, else None.

    Public so discovery can pre-filter denied/snoozed candidates before spending
    an eval on them; ``should_migrate`` enforces the same rule as the final gate.
    """
    model = candidate_model
    pair = f"{current_model}->{model}"
    for pat in policy.ignore:
        if fnmatch(model, pat) or fnmatch(pair, pat):
            return f"candidate {model!r} is snoozed (ignore: {pat!r})"
    if not any(fnmatch(model, pat) for pat in policy.candidates.allow):
        return f"candidate {model!r} not in candidates.allow"
    for pat in policy.candidates.deny:
        if fnmatch(model, pat):
            return f"candidate {model!r} matched candidates.deny ({pat!r})"
    return None


def _candidate_filtered(trigger: Trigger, policy: Policy) -> str | None:
    return candidate_filter_reason(trigger.current_model, trigger.candidate_model, policy)


def _deprecation_urgency(days: int | None) -> Urgency:
    if days is None:
        return Urgency.MEDIUM  # already deprecated, no date
    if days <= 7:
        return Urgency.CRITICAL
    if days <= 30:
        return Urgency.HIGH
    return Urgency.MEDIUM


def should_migrate(trigger: Trigger, outcome: EvalOutcome, policy: Policy) -> Decision:
    """Decide whether (and how) to act on a trigger given the eval outcome."""
    settings = policy.settings_for(trigger.kind)
    if not settings.enabled:
        return _skip(trigger.kind, f"{trigger.kind.value} trigger disabled")

    filtered = _candidate_filtered(trigger, policy)
    if filtered is not None:
        return _skip(trigger.kind, filtered)

    if trigger.kind is TriggerKind.DEPRECATION:
        return _decide_deprecation(trigger, outcome, policy.deprecation)
    return _decide_opportunistic(trigger, outcome, settings)


def _decide_deprecation(
    trigger: Trigger, outcome: EvalOutcome, settings: DeprecationPolicy
) -> Decision:
    days = trigger.days_until_retirement
    if (
        settings.warn_before_days is not None
        and days is not None
        and days > settings.warn_before_days
    ):
        return _skip(
            TriggerKind.DEPRECATION,
            f"retirement in {days}d is beyond warn window ({settings.warn_before_days}d)",
        )

    urgency = _deprecation_urgency(days)
    if days is None:
        when = "already deprecated"
    elif days < 0:
        when = f"retired {-days}d ago"
    else:
        when = f"retires in {days}d"

    # The deadline forces us to surface *something*, even if auto-repair failed.
    if outcome.shippable:
        return Decision(
            settings.action,
            urgency,
            TriggerKind.DEPRECATION,
            f"{trigger.current_model} {when}; validated migration to "
            f"{trigger.candidate_model} -> open {settings.action.value}",
        )
    return Decision(
        Action.ISSUE,
        urgency,
        TriggerKind.DEPRECATION,
        f"{trigger.current_model} {when}; candidate {trigger.candidate_model} not "
        f"shippable as-is (status={outcome.migration_status}) -> open issue for a "
        f"human before the deadline",
    )


def _decide_opportunistic(
    trigger: Trigger, outcome: EvalOutcome, settings: TriggerSettings
) -> Decision:
    # Opportunistic moves are optional: never ship a regression or a non-passing
    # candidate. If there's nothing to ship, stay quiet.
    if not outcome.shippable:
        return _skip(
            trigger.kind,
            f"candidate did not pass thresholds (status={outcome.migration_status})",
        )

    if trigger.kind is TriggerKind.COST:
        return _decide_cost(trigger, outcome, settings)  # type: ignore[arg-type]
    if trigger.kind is TriggerKind.QUALITY:
        return _decide_quality(trigger, outcome, settings)  # type: ignore[arg-type]
    return _decide_new_model(trigger, outcome, settings)  # type: ignore[arg-type]


def _decide_cost(trigger: Trigger, outcome: EvalOutcome, settings: CostPolicy) -> Decision:
    if outcome.cost_change_pct is None:
        return _skip(TriggerKind.COST, "no cost data to evaluate savings")
    savings = -outcome.cost_change_pct
    if savings < settings.min_savings_pct:
        return _skip(
            TriggerKind.COST,
            f"savings {savings:.0%} < min {settings.min_savings_pct:.0%}",
        )
    drop = -(outcome.f1_delta or 0.0)
    if drop > settings.max_quality_drop:
        return _skip(
            TriggerKind.COST,
            f"quality drop {drop:.3f} > max {settings.max_quality_drop:.3f}",
        )
    return Decision(
        settings.action,
        Urgency.LOW,
        TriggerKind.COST,
        f"{trigger.candidate_model} is {savings:.0%} cheaper with quality within "
        f"tolerance -> open {settings.action.value}",
    )


def _decide_quality(trigger: Trigger, outcome: EvalOutcome, settings: QualityPolicy) -> Decision:
    gain = outcome.f1_delta or 0.0
    if gain < settings.min_gain:
        return _skip(
            TriggerKind.QUALITY,
            f"F1 gain {gain:+.3f} < min {settings.min_gain:.3f}",
        )
    return Decision(
        settings.action,
        Urgency.LOW,
        TriggerKind.QUALITY,
        f"{trigger.candidate_model} improves F1 by {gain:+.3f} -> open {settings.action.value}",
    )


def _decide_new_model(trigger: Trigger, outcome: EvalOutcome, settings: NewModelPolicy) -> Decision:
    # A new model is only worth a PR if it also wins on cost or quality.
    savings = -(outcome.cost_change_pct or 0.0)
    gain = outcome.f1_delta or 0.0
    if savings >= settings.min_savings_pct and savings > 0:
        why = f"{savings:.0%} cheaper"
    elif gain >= settings.min_gain and gain > 0:
        why = f"F1 {gain:+.3f}"
    else:
        return _skip(
            TriggerKind.NEW_MODEL,
            "new model offers no material cost or quality win",
        )
    return Decision(
        settings.action,
        Urgency.LOW,
        TriggerKind.NEW_MODEL,
        f"new model {trigger.candidate_model} wins ({why}) -> open {settings.action.value}",
    )


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
POLICY_FILENAME = "policy.yml"


def load_policy(path: Path | None = None, *, cwd: Path | None = None) -> Policy:
    """Load ``.driftless/policy.yml``; return defaults when absent."""
    cwd = (cwd or Path.cwd()).resolve()
    path = path or (cwd / ".driftless" / POLICY_FILENAME)
    if not path.is_file():
        return Policy()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise DriftlessError(f"{path} must contain a YAML mapping")
    try:
        return Policy.model_validate(raw)
    except ValidationError as exc:
        raise DriftlessError(f"invalid policy {path}:\n{exc}") from exc
