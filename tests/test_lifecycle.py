from driftless.lifecycle import Pricing, infer_provider, load_lifecycle


def test_pricing_cost_for():
    p = Pricing(input_per_1m=2.5, output_per_1m=10.0)
    # 1000 input + 500 output tokens.
    assert p.cost_for(1000, 500) == (1000 * 2.5 + 500 * 10.0) / 1_000_000


def test_catalog_parses_pricing_and_tier():
    lc = load_lifecycle()
    info = lc.lookup("gpt-4o")
    assert info is not None
    assert info.capability_tier == "frontier"
    assert info.pricing is not None
    assert info.pricing.input_per_1m == 2.5
    assert info.pricing.output_per_1m == 10.0
    assert info.release_date == "2024-05-13"


def test_pricing_for_handles_dated_alias():
    lc = load_lifecycle()
    # Dated suffix should resolve via the longest-prefix match.
    pricing = lc.pricing_for("gpt-4o-2024-11-20")
    assert pricing is not None
    assert pricing.input_per_1m == 2.5


def test_unpriced_model_returns_none():
    lc = load_lifecycle()
    assert lc.pricing_for("totally-unknown-model") is None


def test_infer_provider_from_catalog_and_prefix():
    assert infer_provider("gpt-4o") == "openai"  # catalog hit
    assert infer_provider("claude-3-5-sonnet") == "anthropic"
    # Not in catalog, but a known prefix (e.g. a brand-new model).
    assert infer_provider("gpt-6-turbo-2027") == "openai"
    assert infer_provider("claude-9") == "anthropic"
    assert infer_provider("gemini-3-ultra") == "google"
    assert infer_provider("llama-3-70b") is None
