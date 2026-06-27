"""Tests for the migration trigger policy (decision core)."""

import yaml

from driftless.policy import (
    Action,
    EvalOutcome,
    Policy,
    Trigger,
    TriggerKind,
    Urgency,
    load_policy,
    should_migrate,
)
from driftless.templates import POLICY_TEMPLATE


def test_policy_template_parses_to_defaults():
    # The scaffolded file must round-trip and match an empty (default) policy, so
    # `init-policy` followed by no edits behaves exactly like no file at all.
    parsed = Policy.model_validate(yaml.safe_load(POLICY_TEMPLATE))
    assert parsed == Policy()


def test_load_policy_reads_scaffolded_file(tmp_path):
    (tmp_path / ".driftless").mkdir()
    (tmp_path / ".driftless" / "policy.yml").write_text(POLICY_TEMPLATE)
    assert load_policy(cwd=tmp_path) == Policy()


def _shippable(**kw) -> EvalOutcome:
    base = dict(passed_thresholds=True, migration_status="pass", has_committed_change=True)
    base.update(kw)
    return EvalOutcome(**base)


def _blocked() -> EvalOutcome:
    return EvalOutcome(passed_thresholds=False, migration_status="blocked")


# --------------------------------------------------------------------------- #
# Deprecation (Tier 1: forced, always surfaces)
# --------------------------------------------------------------------------- #
def test_deprecation_imminent_success_opens_pr_critical():
    trig = Trigger(TriggerKind.DEPRECATION, "gpt-3.5-turbo", "gpt-4o-mini", days_until_retirement=5)
    d = should_migrate(trig, _shippable(), Policy())
    assert d.action is Action.PR
    assert d.urgency is Urgency.CRITICAL


def test_deprecation_blocked_still_opens_issue():
    trig = Trigger(TriggerKind.DEPRECATION, "gpt-3.5-turbo", "gpt-4o-mini", days_until_retirement=20)
    d = should_migrate(trig, _blocked(), Policy())
    assert d.action is Action.ISSUE  # deadline forces surfacing even on failure
    assert d.urgency is Urgency.HIGH


def test_deprecation_beyond_warn_window_skips():
    trig = Trigger(TriggerKind.DEPRECATION, "gpt-3.5-turbo", "gpt-4o-mini", days_until_retirement=200)
    d = should_migrate(trig, _shippable(), Policy())
    assert d.action is Action.SKIP


def test_deprecation_no_date_is_medium():
    trig = Trigger(TriggerKind.DEPRECATION, "old-model", "new-model")
    d = should_migrate(trig, _shippable(), Policy())
    assert d.urgency is Urgency.MEDIUM
    assert d.should_act


# --------------------------------------------------------------------------- #
# Cost (Tier 2: opportunistic, gated)
# --------------------------------------------------------------------------- #
def test_cost_savings_with_stable_quality_opens_pr():
    trig = Trigger(TriggerKind.COST, "gpt-4o", "gpt-4o-mini", )
    out = _shippable(cost_change_pct=-0.40, f1_delta=-0.005)
    d = should_migrate(trig, out, Policy())
    assert d.action is Action.PR
    assert d.urgency is Urgency.LOW


def test_cost_insufficient_savings_skips():
    trig = Trigger(TriggerKind.COST, "gpt-4o", "gpt-4o-mini")
    out = _shippable(cost_change_pct=-0.10, f1_delta=0.0)
    assert should_migrate(trig, out, Policy()).action is Action.SKIP


def test_cost_savings_but_quality_drop_too_large_skips():
    trig = Trigger(TriggerKind.COST, "gpt-4o", "gpt-4o-mini")
    out = _shippable(cost_change_pct=-0.50, f1_delta=-0.05)
    assert should_migrate(trig, out, Policy()).action is Action.SKIP


def test_opportunistic_never_ships_a_blocked_candidate():
    trig = Trigger(TriggerKind.COST, "gpt-4o", "gpt-4o-mini")
    out = EvalOutcome(passed_thresholds=False, migration_status="partial", cost_change_pct=-0.9)
    assert should_migrate(trig, out, Policy()).action is Action.SKIP


# --------------------------------------------------------------------------- #
# Quality (opt-in by default)
# --------------------------------------------------------------------------- #
def test_quality_disabled_by_default_skips():
    trig = Trigger(TriggerKind.QUALITY, "gpt-4o-mini", "gpt-4o")
    out = _shippable(f1_delta=0.10)
    assert should_migrate(trig, out, Policy()).action is Action.SKIP


def test_quality_enabled_with_gain_opens_pr():
    policy = Policy()
    policy.quality.enabled = True
    trig = Trigger(TriggerKind.QUALITY, "gpt-4o-mini", "gpt-4o")
    out = _shippable(f1_delta=0.05)
    assert should_migrate(trig, out, policy).action is Action.PR


# --------------------------------------------------------------------------- #
# Candidate filtering / snooze
# --------------------------------------------------------------------------- #
def test_preview_candidate_denied_by_default():
    trig = Trigger(TriggerKind.DEPRECATION, "gpt-4o", "gpt-5-preview", days_until_retirement=5)
    assert should_migrate(trig, _shippable(), Policy()).action is Action.SKIP


def test_snoozed_candidate_skips():
    policy = Policy()
    policy.ignore.append("gpt-4o->gpt-4o-mini")
    trig = Trigger(TriggerKind.COST, "gpt-4o", "gpt-4o-mini")
    out = _shippable(cost_change_pct=-0.5)
    assert should_migrate(trig, out, policy).action is Action.SKIP


def test_action_can_be_configured_to_issue_only():
    policy = Policy()
    policy.deprecation.action = Action.ISSUE
    trig = Trigger(TriggerKind.DEPRECATION, "gpt-3.5-turbo", "gpt-4o-mini", days_until_retirement=5)
    assert should_migrate(trig, _shippable(), policy).action is Action.ISSUE
