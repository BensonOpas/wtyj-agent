"""Brief 199 — verify the unboks tenant's client.json is well-formed and
encodes Calvin's SOT spec (agent name, languages, pricing guard)."""
import json
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
UNBOKS_CONFIG = REPO_ROOT / "clients" / "unboks" / "config" / "client.json"


def test_unboks_client_json_is_valid():
    """The unboks client.json parses cleanly and has required top-level keys."""
    with open(UNBOKS_CONFIG) as f:
        cfg = json.load(f)
    required_top_level = {"business", "agent_persona", "payment", "features",
                          "terminology", "booking_rules", "services",
                          "service_aliases", "faq", "common_sense_knowledge"}
    assert required_top_level <= set(cfg.keys()), \
        f"missing keys: {required_top_level - set(cfg.keys())}"


def test_unboks_business_identity():
    """Business block has Calvin as agent and 5 languages, booking off."""
    cfg = json.loads(UNBOKS_CONFIG.read_text())
    assert cfg["business"]["name"] == "Unboks"
    assert cfg["business"]["agent_name"] == "Calvin"
    assert cfg["business"]["agent_internal_id"] == "calvin-csa"
    assert len(cfg["business"]["languages"]) == 5
    assert cfg["features"]["booking_flow"] is False


def test_unboks_persona_has_pricing_guard():
    """The brand_voice_rules block must include a never-quote-price rule."""
    cfg = json.loads(UNBOKS_CONFIG.read_text())
    rules_text = " ".join(cfg["agent_persona"]["brand_voice_rules"]).lower()
    assert "never quote" in rules_text and "price" in rules_text, \
        "brand_voice_rules must explicitly forbid quoting a specific price"
