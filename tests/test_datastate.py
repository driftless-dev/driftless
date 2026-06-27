"""Tests for dataset fingerprinting + the data_change trigger discovery."""

from pathlib import Path

from driftless.contract import Contract
from driftless.datastate import (
    fingerprint_dataset,
    load_state,
    record_fingerprint,
)
from driftless.discovery import discover_data_change_triggers
from scenarios import build_scenario


def _contract(wf) -> Contract:
    return Contract(workflows={"ticket_classifier": wf})


def test_fingerprint_is_stable_for_unchanged_data(tmp_path: Path):
    wf = build_scenario(tmp_path)
    assert fingerprint_dataset(wf, cwd=tmp_path) == fingerprint_dataset(wf, cwd=tmp_path)


def test_fingerprint_changes_when_labels_change(tmp_path: Path):
    wf = build_scenario(tmp_path)
    before = fingerprint_dataset(wf, cwd=tmp_path)
    labels = tmp_path / "labels.jsonl"
    labels.write_text(labels.read_text(encoding="utf-8") + '{"id":"zz","label":"billing"}\n', encoding="utf-8")
    assert fingerprint_dataset(wf, cwd=tmp_path) != before


def test_fingerprint_changes_when_inputs_change(tmp_path: Path):
    wf = build_scenario(tmp_path)
    before = fingerprint_dataset(wf, cwd=tmp_path)
    inputs = tmp_path / "inputs.jsonl"
    inputs.write_text(inputs.read_text(encoding="utf-8") + '{"id":"zz","text":"new ticket"}\n', encoding="utf-8")
    assert fingerprint_dataset(wf, cwd=tmp_path) != before


def test_first_seen_is_baseline_not_a_trigger(tmp_path: Path):
    wf = build_scenario(tmp_path)
    contract = _contract(wf)
    # No state yet -> by default a first sighting is recorded as baseline, not fired.
    assert discover_data_change_triggers(contract, cwd=tmp_path) == []
    # Opt-in surfaces first-seen workflows.
    triggers = discover_data_change_triggers(contract, cwd=tmp_path, include_first_seen=True)
    assert len(triggers) == 1
    assert triggers[0].first_seen


def test_trigger_fires_only_after_data_changes(tmp_path: Path):
    wf = build_scenario(tmp_path)
    contract = _contract(wf)
    record_fingerprint("ticket_classifier", fingerprint_dataset(wf, cwd=tmp_path), cwd=tmp_path)

    # Same data -> no trigger.
    assert discover_data_change_triggers(contract, cwd=tmp_path) == []

    # Mutate the dataset -> trigger fires with the old fingerprint preserved.
    labels = tmp_path / "labels.jsonl"
    labels.write_text(labels.read_text(encoding="utf-8") + '{"id":"zz","label":"billing"}\n', encoding="utf-8")
    triggers = discover_data_change_triggers(contract, cwd=tmp_path)
    assert len(triggers) == 1
    t = triggers[0]
    assert not t.first_seen
    assert t.new_fingerprint != t.last_fingerprint


def test_record_fingerprint_roundtrips_and_preserves_others(tmp_path: Path):
    record_fingerprint("a", "fp-a", cwd=tmp_path)
    record_fingerprint("b", "fp-b", cwd=tmp_path)
    state = load_state(cwd=tmp_path)
    assert state["a"].fingerprint == "fp-a"
    assert state["b"].fingerprint == "fp-b"
    assert state["a"].updated_at  # timestamp recorded


def test_workflow_without_labels_is_skipped(tmp_path: Path):
    wf = build_scenario(tmp_path)
    wf.eval.labels_path = None
    contract = _contract(wf)
    assert discover_data_change_triggers(contract, cwd=tmp_path, include_first_seen=True) == []
