import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import refresh_catalog as rc  # noqa: E402


def _catalog(*models) -> dict:
    return {"_meta": {"as_of": "2026-06-21"}, "models": list(models)}


def _model(model, provider="openai", status="active", **extra) -> dict:
    base = {"model": model, "provider": provider, "status": status}
    base.update(extra)
    return base


def test_committed_catalog_is_valid_and_normalized():
    data = rc.load_raw(rc.DEFAULT_PATH)
    assert rc.validate(data) == []
    assert rc.DEFAULT_PATH.read_text(encoding="utf-8") == rc.serialize(rc.normalize(data))


def test_validate_flags_bad_status_and_pricing():
    data = _catalog(
        _model("a", status="zombie"),
        _model("b", pricing={"input_per_1m": -1}),
    )
    errors = rc.validate(data)
    assert any("status" in e for e in errors)
    assert any("pricing" in e for e in errors)


def test_validate_flags_duplicate_and_dangling_replacement():
    data = _catalog(
        _model("a"),
        _model("a"),  # duplicate
        _model("c", recommended_replacement="nope"),  # dangling
    )
    errors = rc.validate(data)
    assert any("duplicate" in e for e in errors)
    assert any("recommended_replacement" in e for e in errors)


def test_validate_flags_bad_date():
    data = _catalog(_model("a", release_date="2024/01/01"))
    assert any("date" in e for e in rc.validate(data))


def test_normalize_sorts_and_is_idempotent():
    data = _catalog(
        _model("zeta", provider="openai"),
        _model("alpha", provider="anthropic"),
    )
    once = rc.normalize(data)
    assert [m["model"] for m in once["models"]] == ["alpha", "zeta"]
    # provider order wins: anthropic < openai
    assert once["models"][0]["provider"] == "anthropic"
    twice = rc.normalize(once)
    assert rc.serialize(once) == rc.serialize(twice)


def test_merge_upserts_by_model_id():
    data = _catalog(_model("a", status="active"))
    merged = rc.merge(data, [_model("a", status="deprecated"), _model("b")])
    by_id = {m["model"]: m for m in merged["models"]}
    assert by_id["a"]["status"] == "deprecated"  # updated in place
    assert "b" in by_id  # new entry added


def test_cli_check_passes_on_committed_file(capsys):
    assert rc.main(["--check"]) == 0


def test_cli_write_normalizes_tmp_file(tmp_path: Path):
    p = tmp_path / "cat.json"
    p.write_text(json.dumps(_catalog(_model("z"), _model("a"))), encoding="utf-8")
    assert rc.main(["--path", str(p), "--write"]) == 0
    text = p.read_text(encoding="utf-8")
    assert text == rc.serialize(rc.normalize(rc.load_raw(p)))
    assert rc.main(["--path", str(p), "--check"]) == 0


def test_cli_validate_fails_on_bad_catalog(tmp_path: Path):
    p = tmp_path / "cat.json"
    p.write_text(json.dumps(_catalog(_model("a", status="zombie"))), encoding="utf-8")
    assert rc.main(["--path", str(p), "--validate"]) == 1
