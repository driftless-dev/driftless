import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import fetch_provider_models as fpm  # noqa: E402


def _catalog(models) -> Path:
    import tempfile

    p = Path(tempfile.mkdtemp()) / "cat.json"
    p.write_text(json.dumps({"models": models}), encoding="utf-8")
    return p


def test_discover_new_models_skips_known_and_filters_openai(tmp_path):
    cat = _catalog(
        [
            {"model": "gpt-4o", "provider": "openai"},
            {"model": "claude-3-5-sonnet", "provider": "anthropic"},
        ]
    )

    def fake_fetch(_key):
        return [
            "gpt-4o",  # known
            "gpt-5-mini",  # new
            "ft:gpt-4o:org:123",  # fine-tune — skip
            "tts-1",  # infra — skip
            "whisper-1",
        ]

    updates = fpm.discover_new_models(
        provider="openai",
        catalog_path=cat,
        fetch_ids=fake_fetch,
        keep=fpm._keep_openai,
        api_key="k",
    )
    assert [u["model"] for u in updates] == ["gpt-5-mini"]
    assert updates[0]["status"] == "active"


def test_discover_new_models_anthropic_claude_only(tmp_path):
    cat = _catalog([{"model": "claude-3-5-sonnet", "provider": "anthropic"}])

    updates = fpm.discover_new_models(
        provider="anthropic",
        catalog_path=cat,
        fetch_ids=lambda _k: ["claude-3-5-sonnet", "claude-3-7-sonnet", "not-a-model"],
        keep=fpm._keep_anthropic,
        api_key="k",
    )
    assert [u["model"] for u in updates] == ["claude-3-7-sonnet"]


def test_fetch_updates_merges_providers_and_skips_missing_keys(tmp_path, monkeypatch):
    cat = _catalog([{"model": "gpt-4o", "provider": "openai"}])
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    updates = fpm.fetch_updates(["openai", "anthropic"], catalog_path=cat)
    assert updates == []


def test_fetch_updates_openai(monkeypatch, tmp_path):
    cat = _catalog([{"model": "gpt-4o", "provider": "openai"}])
    monkeypatch.setenv("OPENAI_API_KEY", "sekret")
    monkeypatch.setattr(
        fpm,
        "_openai_model_ids",
        lambda key: (["gpt-4o", "o3-mini"] if key == "sekret" else []),
    )

    updates = fpm.fetch_updates(["openai"], catalog_path=cat)
    assert [u["model"] for u in updates] == ["o3-mini"]


def test_cli_writes_output(tmp_path, monkeypatch):
    cat = tmp_path / "cat.json"
    cat.write_text(json.dumps({"models": []}), encoding="utf-8")
    out = tmp_path / "updates.json"
    monkeypatch.setattr(
        fpm,
        "fetch_updates",
        lambda providers, catalog_path: [
            {"model": "gpt-5", "provider": "openai", "status": "active"}
        ],
    )
    assert fpm.main(["--provider", "openai", "--catalog", str(cat), "-o", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data[0]["model"] == "gpt-5"


def test_http_get_json_raises_on_http_error(monkeypatch):
    import urllib.error

    class FakeHTTPError(urllib.error.HTTPError):
        def __init__(self):
            super().__init__(url="http://x", code=401, msg="nope", hdrs={}, fp=None)

    def boom(*a, **k):
        raise FakeHTTPError()

    monkeypatch.setattr(fpm.urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError, match="HTTP 401"):
        fpm._http_get_json("http://x", {})
