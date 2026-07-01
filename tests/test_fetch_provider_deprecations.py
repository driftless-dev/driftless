import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import fetch_provider_deprecations as fpd  # noqa: E402
import fetch_provider_models as fpm  # noqa: E402


def _catalog(models) -> Path:
    import tempfile

    p = Path(tempfile.mkdtemp()) / "cat.json"
    p.write_text(json.dumps({"models": models}), encoding="utf-8")
    return p


def test_api_covers_model_with_dated_snapshots():
    api = {"gpt-4o", "gpt-4o-2024-05-13", "claude-3-5-sonnet-20241022"}
    assert fpd._api_covers_model("gpt-4o", api)
    assert fpd._api_covers_model("gpt-4o-mini", {"gpt-4o-mini-2024-07-18"})
    assert not fpd._api_covers_model("gpt-3.5-turbo", api)


def test_discover_models_api_absence_flags_missing_active():
    cat = _catalog(
        [
            {"model": "gpt-4o", "provider": "openai", "status": "active"},
            {"model": "legacy-x", "provider": "openai", "status": "active"},
            {"model": "gpt-4", "provider": "openai", "status": "deprecated"},
        ]
    )
    updates = fpd.discover_models_api_absence(
        provider="openai",
        catalog_path=cat,
        api_ids=["gpt-4o", "gpt-4o-2024-05-13"],
        keep=lambda mid: mid.startswith("gpt-"),
    )
    assert [u["model"] for u in updates] == ["legacy-x"]
    assert updates[0]["status"] == "deprecated"


def test_discover_models_api_absence_google():
    cat = _catalog(
        [
            {"model": "gemini-1.5-flash", "provider": "google", "status": "active"},
            {"model": "gemini-pro", "provider": "google", "status": "active"},
        ]
    )
    updates = fpd.discover_models_api_absence(
        provider="google",
        catalog_path=cat,
        api_ids=["gemini-1.5-flash", "gemini-2.0-flash"],
        keep=fpm._keep_google,
    )
    assert [u["model"] for u in updates] == ["gemini-pro"]


def test_parse_deprecation_page_extracts_status_date_and_replacement():
    html = """
    <p>Model gpt-4-turbo is deprecated. Shutdown date 2025-12-01.
    Migrate to gpt-4o for chat completions.</p>
    """
    catalog = [
        {"model": "gpt-4-turbo", "provider": "openai", "status": "active"},
        {"model": "gpt-4o", "provider": "openai", "status": "active"},
    ]
    hints = fpd.parse_deprecation_page(html, provider="openai", catalog_models=catalog)
    assert len(hints) == 1
    assert hints[0]["model"] == "gpt-4-turbo"
    assert hints[0]["status"] == "deprecated"
    assert hints[0]["retirement_date"] == "2025-12-01"
    assert hints[0]["recommended_replacement"] == "gpt-4o"


def test_consolidate_never_downgrades_status():
    cat = _catalog(
        [
            {
                "model": "gpt-4",
                "provider": "openai",
                "status": "deprecated",
                "retirement_date": "2025-09-30",
                "recommended_replacement": "gpt-4o",
            }
        ]
    )
    updates = fpd.consolidate_deprecation_hints(
        cat,
        [{"model": "gpt-4", "provider": "openai", "status": "active"}],
    )
    assert updates == []


def test_consolidate_upgrades_active_to_deprecated_and_fills_missing_fields():
    cat = _catalog(
        [
            {
                "model": "gpt-4-turbo",
                "provider": "openai",
                "status": "active",
                "retirement_date": None,
                "recommended_replacement": None,
            },
            {"model": "gpt-4o", "provider": "openai", "status": "active"},
        ]
    )
    updates = fpd.consolidate_deprecation_hints(
        cat,
        [
            {
                "model": "gpt-4-turbo",
                "provider": "openai",
                "status": "deprecated",
                "retirement_date": "2025-12-01",
                "recommended_replacement": "gpt-4o",
            }
        ],
    )
    assert updates == [
        {
            "model": "gpt-4-turbo",
            "provider": "openai",
            "status": "deprecated",
            "retirement_date": "2025-12-01",
            "recommended_replacement": "gpt-4o",
        }
    ]


def test_consolidate_skips_inactive_recommended_replacement():
    cat = _catalog(
        [
            {
                "model": "gemini-pro-vision",
                "provider": "google",
                "status": "retired",
                "recommended_replacement": None,
            },
            {"model": "gemini-pro", "provider": "google", "status": "deprecated"},
            {"model": "gemini-1.5-pro", "provider": "google", "status": "active"},
            {"model": "gemini-1.5-flash", "provider": "google", "status": "active"},
        ]
    )
    updates = fpd.consolidate_deprecation_hints(
        cat,
        [
            {
                "model": "gemini-pro-vision",
                "provider": "google",
                "status": "retired",
                "recommended_replacement": "gemini-pro",
            },
            {
                "model": "gemini-1.5-pro",
                "provider": "google",
                "status": "deprecated",
                "recommended_replacement": "gemini-1.5-flash",
            },
        ],
    )
    assert updates == [
        {
            "model": "gemini-1.5-pro",
            "provider": "google",
            "status": "deprecated",
            "recommended_replacement": "gemini-1.5-flash",
        }
    ]


def test_fetch_deprecation_page_hints_includes_google_url(monkeypatch, tmp_path):
    cat = _catalog(
        [
            {"model": "gemini-1.5-pro", "provider": "google", "status": "active"},
            {"model": "gemini-1.5-flash", "provider": "google", "status": "active"},
        ]
    )
    seen: list[str] = []

    def fake_fetch(url: str) -> str:
        seen.append(url)
        if "gemini-api/docs/changelog" in url:
            return (
                "gemini-1.5-pro is deprecated. Shutdown 2025-02-15. "
                "Use gemini-1.5-flash instead."
            )
        return ""

    hints = fpd.fetch_deprecation_page_hints(
        ["google"], catalog_path=cat, fetch_html=fake_fetch
    )
    assert any("gemini-api/docs/changelog" in u for u in seen)
    assert hints[0]["model"] == "gemini-1.5-pro"
    assert hints[0]["status"] == "deprecated"
    assert hints[0]["recommended_replacement"] == "gemini-1.5-flash"


def test_fetch_updates_merges_page_and_api_hints(tmp_path, monkeypatch):
    cat = _catalog(
        [
            {"model": "gpt-4o", "provider": "openai", "status": "active"},
            {"model": "legacy-y", "provider": "openai", "status": "active"},
        ]
    )
    monkeypatch.setattr(
        fpd,
        "fetch_deprecation_page_hints",
        lambda providers, catalog_path, fetch_html=None: [
            {
                "model": "legacy-y",
                "provider": "openai",
                "status": "retired",
                "retirement_date": "2024-01-04",
            }
        ],
    )
    monkeypatch.setattr(
        fpd,
        "fetch_models_api_hints",
        lambda providers, catalog_path, openai_key=None, anthropic_key=None: [
            {"model": "legacy-y", "provider": "openai", "status": "deprecated"}
        ],
    )
    updates = fpd.fetch_updates(["openai"], catalog_path=cat, skip_pages=False)
    assert len(updates) == 1
    assert updates[0]["status"] == "retired"
    assert updates[0]["retirement_date"] == "2024-01-04"


def test_cli_writes_output(tmp_path, monkeypatch):
    cat = tmp_path / "cat.json"
    cat.write_text(json.dumps({"models": []}), encoding="utf-8")
    out = tmp_path / "updates.json"
    monkeypatch.setattr(fpd, "fetch_updates", lambda providers, catalog_path, **kw: [])
    assert (
        fpd.main(["--provider", "openai", "--catalog", str(cat), "-o", str(out)])
        == 0
    )
    assert json.loads(out.read_text(encoding="utf-8")) == []


def test_http_get_text_raises_on_http_error(monkeypatch):
    import urllib.error

    class FakeHTTPError(urllib.error.HTTPError):
        def __init__(self):
            super().__init__(url="http://x", code=403, msg="nope", hdrs={}, fp=None)

    def boom(*a, **k):
        raise FakeHTTPError()

    monkeypatch.setattr(fpd.urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError, match="HTTP 403"):
        fpd._http_get_text("http://x")
