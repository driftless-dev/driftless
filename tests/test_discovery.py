"""Tests for deprecation-trigger discovery."""

from datetime import date

from driftless.contract import Contract
from driftless.discovery import (
    discover_deprecation_triggers,
    discover_opportunistic_triggers,
    estimate_cost_change_pct,
    group_triggers,
)
from driftless.policy import Policy, TriggerKind


def _contract(current: str, *, candidates=None) -> Contract:
    return Contract.model_validate(
        {
            "version": 1,
            "workflows": {
                "wf": {
                    "run": {
                        "command": "echo hi",
                        "input_path": "in.jsonl",
                        "output_path": "out.jsonl",
                    },
                    "model": {
                        "current": current,
                        "env_var": "MODEL",
                        "target_candidates": candidates or [],
                    },
                }
            },
        }
    )


def test_deprecated_model_yields_trigger_with_recommended_replacement():
    contract = _contract("gpt-3.5-turbo")  # deprecated in seed data, replacement gpt-4o-mini
    triggers = discover_deprecation_triggers(contract, as_of=date(2025, 9, 1))
    assert len(triggers) == 1
    dt = triggers[0]
    assert dt.trigger.kind is TriggerKind.DEPRECATION
    assert dt.trigger.current_model == "gpt-3.5-turbo"
    assert dt.trigger.candidate_model == "gpt-4o-mini"
    # retirement 2025-09-30 minus 2025-09-01 = 29 days
    assert dt.trigger.days_until_retirement == 29


def test_active_model_yields_no_trigger():
    contract = _contract("gpt-4o")  # active
    assert discover_deprecation_triggers(contract, as_of=date(2025, 9, 1)) == []


def test_dated_alias_resolves_via_prefix():
    contract = _contract("gpt-3.5-turbo-0125")  # not an exact key; longest-prefix match
    triggers = discover_deprecation_triggers(contract, as_of=date(2025, 1, 1))
    assert len(triggers) == 1
    assert triggers[0].trigger.candidate_model == "gpt-4o-mini"


def _opp_contract(current: str) -> Contract:
    return _contract(current)


def test_cost_trigger_proposes_cheaper_same_or_better_tier():
    # claude-3-opus (frontier, ~$90 blended) -> claude-3-5-sonnet (frontier, ~$18):
    # same tier, far cheaper -> a cost win. Default policy enables only cost.
    contract = _opp_contract("claude-3-opus-20240229")
    triggers = discover_opportunistic_triggers(contract)
    assert len(triggers) == 1
    t = triggers[0].trigger
    assert t.kind is TriggerKind.COST
    assert t.candidate_model.startswith("claude-3-5-sonnet")


def test_cost_trigger_never_downgrades_capability():
    # gpt-4o (frontier) has no cheaper same-or-higher-tier generative peer; the
    # cheaper models are lower-tier, so we do NOT auto-propose a downgrade.
    contract = _opp_contract("gpt-4o")
    assert discover_opportunistic_triggers(contract) == []


def test_quality_trigger_picks_higher_tier_when_enabled():
    policy = Policy.model_validate({"cost": {"enabled": False}, "quality": {"enabled": True}})
    contract = _opp_contract("gpt-4o-mini")  # economy
    triggers = discover_opportunistic_triggers(contract, policy=policy)
    assert len(triggers) == 1
    t = triggers[0].trigger
    assert t.kind is TriggerKind.QUALITY
    # Highest available tier (reasoning), cheapest among them -> o1-mini.
    assert t.candidate_model == "o1-mini"


def test_new_model_trigger_picks_newest_not_weaker():
    policy = Policy.model_validate({"cost": {"enabled": False}, "new_model": {"enabled": True}})
    contract = _opp_contract("gpt-4o")  # released 2024-05-13, frontier
    triggers = discover_opportunistic_triggers(contract, policy=policy)
    assert len(triggers) == 1
    t = triggers[0].trigger
    assert t.kind is TriggerKind.NEW_MODEL
    assert t.candidate_model == "o1"  # newest same-or-higher-tier release


def test_embedding_models_are_not_proposed():
    # text-embedding-3-small is cheaper than -large but has no output tokens; it
    # must never be proposed as a generative replacement.
    policy = Policy.model_validate({"cost": {"enabled": True}})
    contract = _opp_contract("text-embedding-3-large")
    assert discover_opportunistic_triggers(contract, policy=policy) == []


def test_at_risk_baseline_has_no_opportunistic_triggers():
    # Deprecated models are handled by the forced deprecation path only.
    contract = _opp_contract("gpt-3.5-turbo")
    assert discover_opportunistic_triggers(contract) == []


def test_unknown_baseline_yields_no_opportunistic():
    contract = _opp_contract("some-private-model")
    assert discover_opportunistic_triggers(contract) == []


def test_denied_candidate_is_not_proposed():
    policy = Policy.model_validate({"candidates": {"deny": ["claude-3-5-sonnet*"]}})
    contract = _opp_contract("claude-3-opus-20240229")
    # The only cost win was a sonnet variant; denying it leaves nothing.
    assert discover_opportunistic_triggers(contract, policy=policy) == []


def test_all_kinds_disabled_returns_nothing():
    policy = Policy.model_validate(
        {"cost": {"enabled": False}, "quality": {"enabled": False}, "new_model": {"enabled": False}}
    )
    contract = _opp_contract("claude-3-opus-20240229")
    assert discover_opportunistic_triggers(contract, policy=policy) == []


def test_estimate_cost_change_is_negative_for_cheaper_candidate():
    # opus ~$90 blended -> sonnet ~$18 blended: a large negative (cheaper) change.
    change = estimate_cost_change_pct("claude-3-opus-20240229", "claude-3-5-sonnet")
    assert change is not None and change < -0.5


def test_estimate_cost_change_unknown_when_price_missing():
    assert estimate_cost_change_pct("claude-3-opus-20240229", "mystery") is None


def test_cooldown_holds_back_freshly_released_candidate():
    policy = Policy.model_validate({"cost": {"enabled": False}, "new_model": {"enabled": True}})
    contract = _opp_contract("gpt-4o")
    # 5 days after o1's release (2024-12-05): o1 is within the 14-day cooldown, so
    # the newest *eligible* candidate falls back to o1-mini (released 2024-09-12).
    triggers = discover_opportunistic_triggers(
        contract, policy=policy, as_of=date(2024, 12, 10)
    )
    assert len(triggers) == 1
    assert triggers[0].trigger.candidate_model == "o1-mini"


def test_cooldown_disabled_allows_fresh_candidate():
    policy = Policy.model_validate(
        {"cost": {"enabled": False}, "new_model": {"enabled": True}, "cooldown_days": None}
    )
    contract = _opp_contract("gpt-4o")
    triggers = discover_opportunistic_triggers(
        contract, policy=policy, as_of=date(2024, 12, 10)
    )
    assert triggers and triggers[0].trigger.candidate_model == "o1"


def _two_workflow_contract(current: str) -> Contract:
    wf = {
        "run": {"command": "echo hi", "input_path": "in.jsonl", "output_path": "out.jsonl"},
        "model": {"current": current, "env_var": "MODEL", "target_candidates": []},
    }
    return Contract.model_validate({"version": 1, "workflows": {"a": dict(wf), "b": dict(wf)}})


def test_group_triggers_batches_shared_move():
    # Both workflows are on the same deprecated model -> one grouped move.
    contract = _two_workflow_contract("gpt-3.5-turbo")
    triggers = discover_deprecation_triggers(contract, as_of=date(2025, 9, 1))
    groups = group_triggers(triggers)
    assert len(groups) == 1
    g = groups[0]
    assert g.current_model == "gpt-3.5-turbo"
    assert g.candidate_model == "gpt-4o-mini"
    assert g.kind is TriggerKind.DEPRECATION
    assert sorted(g.workflows) == ["a", "b"]


def test_group_triggers_separates_distinct_moves():
    contract = _two_workflow_contract("gpt-3.5-turbo")
    dep = discover_deprecation_triggers(contract, as_of=date(2025, 9, 1))
    # Mutate one trigger's candidate so the two no longer share a move.
    dep[1].trigger.candidate_model = "gpt-4o"
    groups = group_triggers(dep)
    assert len(groups) == 2


def test_target_candidate_used_when_no_recommended_replacement(monkeypatch):
    from driftless import lifecycle as lc

    # A deprecated model with no recommended replacement falls back to the
    # contract's declared target_candidates.
    fake = lc.Lifecycle(
        [lc.ModelInfo(model="legacy-x", provider="acme", status="deprecated",
                      retirement_date=None, recommended_replacement=None)]
    )
    contract = _contract("legacy-x", candidates=["successor-y"])
    triggers = discover_deprecation_triggers(contract, lifecycle=fake, as_of=date(2025, 1, 1))
    assert len(triggers) == 1
    assert triggers[0].trigger.candidate_model == "successor-y"
    assert triggers[0].trigger.days_until_retirement is None
