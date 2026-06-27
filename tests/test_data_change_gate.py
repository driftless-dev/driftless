"""P3.1: meaningful-change gate + debounce for the data-change (refine) trigger."""

import json
from datetime import date, timedelta
from pathlib import Path

from driftless.contract import Contract
from driftless.datastate import (
    DatasetState,
    dataset_signature,
    record_dataset_state,
    signature_delta,
)
from driftless.discovery import discover_data_change_triggers
from driftless.policy import DataChangePolicy, is_meaningful_change
from scenarios import build_scenario


def _contract(wf) -> Contract:
    return Contract(workflows={"ticket_classifier": wf})


def _append_label(tmp_path: Path, n: int) -> None:
    labels = tmp_path / "labels.jsonl"
    extra = "".join(json.dumps({"id": f"x{i}", "label": "billing"}) + "\n" for i in range(n))
    labels.write_text(labels.read_text(encoding="utf-8") + extra, encoding="utf-8")


# --- signature + delta ----------------------------------------------------- #
def test_signature_is_keyed_and_counts_rows(tmp_path: Path):
    wf = build_scenario(tmp_path)
    sig = dataset_signature(wf, cwd=tmp_path)
    assert sig.keyed is True
    assert sig.row_count == 24


def test_delta_detects_added_changed_removed(tmp_path: Path):
    wf = build_scenario(tmp_path)
    before = dataset_signature(wf, cwd=tmp_path)

    labels = tmp_path / "labels.jsonl"
    rows = [json.loads(l) for l in labels.read_text().splitlines() if l.strip()]
    rows[0]["label"] = "technical"          # changed
    rows.pop()                              # removed
    rows.append({"id": "new1", "label": "billing"})  # added
    labels.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    after = dataset_signature(wf, cwd=tmp_path)
    delta = signature_delta(before, after)
    assert delta.added == 1
    assert delta.removed == 1
    assert delta.changed == 1
    assert delta.total == 3


def test_reorder_and_whitespace_are_not_changes(tmp_path: Path):
    wf = build_scenario(tmp_path)
    before = dataset_signature(wf, cwd=tmp_path)
    labels = tmp_path / "labels.jsonl"
    rows = [json.loads(l) for l in labels.read_text().splitlines() if l.strip()]
    rows.reverse()
    # reorder keys + add whitespace; canonicalization should ignore both
    labels.write_text("\n".join(json.dumps({"label": r["label"], "id": r["id"]}, indent=2).replace("\n", " ") for r in rows) + "\n")
    after = dataset_signature(wf, cwd=tmp_path)
    assert signature_delta(before, after).total == 0


def test_meaningful_gate_thresholds():
    pol = DataChangePolicy(min_changed_rows=5)
    small = signature_delta(None, _sig(old=0, new=0))  # zero
    assert not is_meaningful_change(small, pol)

    from driftless.datastate import SignatureDelta

    assert not is_meaningful_change(SignatureDelta(3, 0, 0, 100, 103), pol)
    assert is_meaningful_change(SignatureDelta(5, 0, 0, 100, 105), pol)
    # fraction path
    frac = DataChangePolicy(min_changed_rows=1000, min_changed_fraction=0.1)
    assert is_meaningful_change(SignatureDelta(10, 0, 0, 90, 100), frac)
    assert not is_meaningful_change(SignatureDelta(5, 0, 0, 95, 100), frac)


def _sig(*, old, new):
    from driftless.datastate import DatasetSignature

    return DatasetSignature("fp", new, True, {})


# --- discovery gate + debounce -------------------------------------------- #
def test_small_change_below_gate_does_not_fire(tmp_path: Path):
    wf = build_scenario(tmp_path)
    contract = _contract(wf)
    record_dataset_state("ticket_classifier", dataset_signature(wf, cwd=tmp_path), cwd=tmp_path)

    _append_label(tmp_path, 2)  # only 2 new rows, below default min_changed_rows=5
    triggers = discover_data_change_triggers(contract, cwd=tmp_path, policy=DataChangePolicy())
    assert triggers == []


def test_substantive_change_fires_with_delta(tmp_path: Path):
    wf = build_scenario(tmp_path)
    contract = _contract(wf)
    record_dataset_state("ticket_classifier", dataset_signature(wf, cwd=tmp_path), cwd=tmp_path)

    _append_label(tmp_path, 6)
    triggers = discover_data_change_triggers(contract, cwd=tmp_path, policy=DataChangePolicy())
    assert len(triggers) == 1
    assert triggers[0].changed_rows == 6
    assert triggers[0].delta.added == 6


def test_min_changed_rows_one_fires_on_any_change(tmp_path: Path):
    wf = build_scenario(tmp_path)
    contract = _contract(wf)
    record_dataset_state("ticket_classifier", dataset_signature(wf, cwd=tmp_path), cwd=tmp_path)

    _append_label(tmp_path, 1)
    triggers = discover_data_change_triggers(
        contract, cwd=tmp_path, policy=DataChangePolicy(min_changed_rows=1)
    )
    assert len(triggers) == 1


def test_debounce_suppresses_recent_refire(tmp_path: Path):
    wf = build_scenario(tmp_path)
    contract = _contract(wf)
    record_dataset_state("ticket_classifier", dataset_signature(wf, cwd=tmp_path), cwd=tmp_path)
    _append_label(tmp_path, 6)

    policy = DataChangePolicy(min_changed_rows=5, min_days_between=7)
    # state.updated_at was just written (today) -> within the 7-day window.
    assert discover_data_change_triggers(contract, cwd=tmp_path, policy=policy) == []
    # As-of far in the future -> outside the window -> fires.
    future = date.today() + timedelta(days=30)
    assert len(discover_data_change_triggers(contract, cwd=tmp_path, policy=policy, as_of=future)) == 1


def test_disabled_policy_short_circuits(tmp_path: Path):
    wf = build_scenario(tmp_path)
    contract = _contract(wf)
    record_dataset_state("ticket_classifier", dataset_signature(wf, cwd=tmp_path), cwd=tmp_path)
    _append_label(tmp_path, 10)
    assert discover_data_change_triggers(
        contract, cwd=tmp_path, policy=DataChangePolicy(enabled=False)
    ) == []
