"""Dataset fingerprints + last-seen state for the ``data_change`` trigger.

`refine` is triggered by *dataset* drift. Two detectors:

* **In-repo data** (the MVP): git is the change detector -- a path-filtered Action
  runs `refine` when ``eval.labels_path`` / ``run.input_path`` change. No state
  needed.
* **External data** (object storage, a labeling tool, a warehouse): git can't see
  it, so a scheduled job fetches the data, **fingerprints** it here, and compares
  against the last-seen fingerprint persisted in ``.driftless/state.json``.

This module owns the fingerprint + state file; the decision of *which* workflows
changed lives in :func:`driftless.discovery.discover_data_change_triggers`.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .contract import Workflow

STATE_DIRNAME = ".driftless"
STATE_FILENAME = "state.json"


def _hash_file(h: "hashlib._Hash", path: Path) -> None:
    """Fold a file's bytes into ``h``; absent files contribute a stable marker."""
    if path.is_file():
        h.update(b"\x01")
        h.update(path.read_bytes())
    else:
        h.update(b"\x00")


def fingerprint_dataset(workflow: Workflow, *, cwd: Path | None = None) -> str:
    """A content hash of a workflow's eval dataset (inputs + labels + schema).

    Deterministic and order-sensitive: any change to the input rows, the gold
    labels, or the alignment fields produces a new fingerprint, so the poll only
    fires on a *real* dataset change -- not on unrelated repo edits.
    """
    cwd = (cwd or Path.cwd()).resolve()
    h = hashlib.sha256()

    h.update(b"input:")
    _hash_file(h, (cwd / workflow.run.input_path).resolve())

    h.update(b"labels:")
    if workflow.eval.labels_path:
        _hash_file(h, (cwd / workflow.eval.labels_path).resolve())
    else:
        h.update(b"\x00")

    # Field names participate: re-keying labels is a meaningful dataset change.
    h.update(b"fields:")
    h.update((workflow.eval.label_field or "").encode("utf-8"))
    h.update(b"|")
    h.update((workflow.eval.id_field or "").encode("utf-8"))

    return h.hexdigest()


# --------------------------------------------------------------------------- #
# Per-row signature (for the meaningful-change gate / debounce)
# --------------------------------------------------------------------------- #
def _canonical_row(line: str) -> str:
    """Normalize a row so whitespace / key-order don't count as a change."""
    line = line.strip()
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return line
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _row_hash(line: str) -> str:
    return hashlib.sha256(_canonical_row(line).encode("utf-8")).hexdigest()


@dataclass
class DatasetSignature:
    """A content fingerprint plus per-row hashes for delta computation.

    ``keyed`` signatures (when ``eval.id_field`` is set) map id -> row hash, so we
    can tell *added* / *removed* / *changed* rows apart. Unkeyed signatures keep a
    sorted multiset of row hashes, so reordering is free but added/removed are
    still counted (changed can't be distinguished).
    """

    fingerprint: str
    row_count: int
    keyed: bool
    rows: dict[str, str] | list[str]


def dataset_signature(workflow: Workflow, *, cwd: Path | None = None) -> DatasetSignature:
    """Signature of a workflow's gold dataset (the labels file), keyed by id."""
    cwd = (cwd or Path.cwd()).resolve()
    fingerprint = fingerprint_dataset(workflow, cwd=cwd)
    id_field = workflow.eval.id_field
    labels_path = workflow.eval.labels_path
    if not labels_path:
        return DatasetSignature(fingerprint, 0, keyed=bool(id_field), rows={} if id_field else [])

    path = (cwd / labels_path).resolve()
    if not path.is_file():
        return DatasetSignature(fingerprint, 0, keyed=bool(id_field), rows={} if id_field else [])

    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if id_field:
        rows: dict[str, str] = {}
        for ln in lines:
            try:
                obj = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and id_field in obj:
                rows[str(obj[id_field])] = _row_hash(ln)
        return DatasetSignature(fingerprint, len(rows), keyed=True, rows=rows)

    hashes = sorted(_row_hash(ln) for ln in lines)
    return DatasetSignature(fingerprint, len(hashes), keyed=False, rows=hashes)


@dataclass
class SignatureDelta:
    added: int
    removed: int
    changed: int
    old_count: int
    new_count: int

    @property
    def total(self) -> int:
        return self.added + self.removed + self.changed

    @property
    def fraction(self) -> float:
        """Changed rows as a fraction of the new dataset size (0 when empty)."""
        return self.total / self.new_count if self.new_count else 0.0


def signature_delta(
    old: DatasetSignature | None, new: DatasetSignature
) -> SignatureDelta:
    """Count added/removed/changed rows between two signatures.

    With no prior signature (or one of them unkeyed) we fall back to a multiset
    comparison of row hashes, which still counts added/removed but reports
    ``changed=0`` (a changed row reads as one removed + one added there).
    """
    old_count = old.row_count if old else 0
    if old is not None and old.keyed and new.keyed:
        old_rows: dict[str, str] = old.rows  # type: ignore[assignment]
        new_rows: dict[str, str] = new.rows  # type: ignore[assignment]
        old_ids, new_ids = set(old_rows), set(new_rows)
        added = len(new_ids - old_ids)
        removed = len(old_ids - new_ids)
        changed = sum(1 for i in old_ids & new_ids if old_rows[i] != new_rows[i])
        return SignatureDelta(added, removed, changed, old_count, new.row_count)

    old_hashes = Counter(_as_hash_list(old)) if old else Counter()
    new_hashes = Counter(_as_hash_list(new))
    added = sum((new_hashes - old_hashes).values())
    removed = sum((old_hashes - new_hashes).values())
    return SignatureDelta(added, removed, 0, old_count, new.row_count)


def _as_hash_list(sig: DatasetSignature) -> list[str]:
    return list(sig.rows.values()) if isinstance(sig.rows, dict) else list(sig.rows)


@dataclass
class DatasetState:
    fingerprint: str
    updated_at: str
    signature: DatasetSignature | None = None


def _state_path(cwd: Path) -> Path:
    return cwd / STATE_DIRNAME / STATE_FILENAME


def load_state(*, cwd: Path | None = None) -> dict[str, DatasetState]:
    """Load per-workflow last-seen dataset fingerprints (empty when absent)."""
    cwd = (cwd or Path.cwd()).resolve()
    path = _state_path(cwd)
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    datasets = raw.get("datasets", {}) if isinstance(raw, dict) else {}
    out: dict[str, DatasetState] = {}
    for name, entry in datasets.items():
        if isinstance(entry, dict) and "fingerprint" in entry:
            sig = None
            if "rows" in entry and "keyed" in entry:
                sig = DatasetSignature(
                    fingerprint=str(entry["fingerprint"]),
                    row_count=int(entry.get("row_count", 0)),
                    keyed=bool(entry["keyed"]),
                    rows=entry["rows"],
                )
            out[name] = DatasetState(
                fingerprint=str(entry["fingerprint"]),
                updated_at=str(entry.get("updated_at", "")),
                signature=sig,
            )
    return out


def _write_entry(workflow_name: str, entry: dict, *, cwd: Path) -> Path:
    path = _state_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw: dict = {}
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            raw = loaded
    datasets = raw.setdefault("datasets", {})
    entry["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    datasets[workflow_name] = entry
    path.write_text(json.dumps(raw, indent=2, sort_keys=True), encoding="utf-8")
    return path


def record_fingerprint(
    workflow_name: str, fingerprint: str, *, cwd: Path | None = None
) -> Path:
    """Persist the last-seen fingerprint for one workflow, preserving others."""
    cwd = (cwd or Path.cwd()).resolve()
    return _write_entry(workflow_name, {"fingerprint": fingerprint}, cwd=cwd)


def record_dataset_state(
    workflow_name: str, signature: DatasetSignature, *, cwd: Path | None = None
) -> Path:
    """Persist the full last-seen signature (fingerprint + per-row hashes).

    The poll uses the row hashes to compute a meaningful-change delta on the next
    run, so processed datasets are recorded with :func:`record_dataset_state`
    rather than the bare :func:`record_fingerprint`.
    """
    cwd = (cwd or Path.cwd()).resolve()
    return _write_entry(
        workflow_name,
        {
            "fingerprint": signature.fingerprint,
            "row_count": signature.row_count,
            "keyed": signature.keyed,
            "rows": signature.rows,
        },
        cwd=cwd,
    )
