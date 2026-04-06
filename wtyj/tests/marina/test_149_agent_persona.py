"""
Brief 149 — Structured agent_persona config + operating_mode alias tests.

Guards against:
1. Missing persona sections in client.json for either client
2. Missing required fields within the persona section
3. BlueFinn / Adamus vocabulary crossover in persona content
4. operating_mode drifting from booking_flow
5. Prompt builder dropping persona fields during assembly
6. Double-injection regression via marina_agent._build_client_context()
7. Dashboard draft-email endpoint using legacy persona string
"""
import json
import os

import pytest

# Repo-relative paths
_TEST_FILE = os.path.abspath(__file__)
_BM_TESTS = os.path.dirname(os.path.dirname(_TEST_FILE))
_BM_ROOT = os.path.dirname(_BM_TESTS)
_REPO_ROOT = os.path.dirname(_BM_ROOT)

# Brief 150 — BlueMarlin config moved from bluemarlin/config/ to clients/bluemarlin/config/
# Name kept as BLUEFINN_CLIENT_JSON for historical reasons in test names only;
# the value now points at BlueMarlin's new location.
BLUEFINN_CLIENT_JSON = os.path.join(_REPO_ROOT, "clients", "bluemarlin", "config", "client.json")
ADAMUS_CLIENT_JSON = os.path.join(_REPO_ROOT, "clients", "adamus", "config", "client.json")
DASHBOARD_API_PATH = os.path.join(_BM_ROOT, "dashboard", "api.py")

PERSONA_FIELDS = [
    "tone",
    "language_register",
    "greeting_style",
    "closing_style",
    "brand_voice_rules",
    "topics_allowed",
    "topics_refused",
    "small_talk",
    "escalation_tone",
    "freeform_notes",
]


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Persona section presence
# ---------------------------------------------------------------------------

def test_bluefinn_client_json_has_agent_persona_section():
    cfg = _load_json(BLUEFINN_CLIENT_JSON)
    assert "agent_persona" in cfg, "BlueFinn client.json missing top-level agent_persona section"
    assert isinstance(cfg["agent_persona"], dict)


def test_adamus_client_json_has_agent_persona_section():
    cfg = _load_json(ADAMUS_CLIENT_JSON)
    assert "agent_persona" in cfg, "Adamus client.json missing top-level agent_persona section"
    assert isinstance(cfg["agent_persona"], dict)


def test_bluefinn_agent_persona_has_all_10_fields():
    cfg = _load_json(BLUEFINN_CLIENT_JSON)
    persona = cfg["agent_persona"]
    missing = [f for f in PERSONA_FIELDS if not persona.get(f)]
    assert not missing, f"BlueFinn agent_persona missing/empty fields: {missing}"


def test_adamus_agent_persona_has_all_10_fields():
    cfg = _load_json(ADAMUS_CLIENT_JSON)
    persona = cfg["agent_persona"]
    missing = [f for f in PERSONA_FIELDS if not persona.get(f)]
    assert not missing, f"Adamus agent_persona missing/empty fields: {missing}"


# ---------------------------------------------------------------------------
# Vocabulary consistency — guards against copy-paste between clients
# ---------------------------------------------------------------------------

def test_bluefinn_persona_mentions_charter_vocabulary():
    cfg = _load_json(BLUEFINN_CLIENT_JSON)
    persona = cfg["agent_persona"]
    searchable = (
        persona.get("freeform_notes", "")
        + " "
        + " ".join(persona.get("topics_allowed", []))
    ).lower()
    keywords = ["charter", "catamaran", "klein curaçao", "trip"]
    matched = [k for k in keywords if k in searchable]
    assert matched, f"BlueFinn persona should mention charter vocabulary, found none of {keywords}"


def test_adamus_persona_mentions_restaurant_vocabulary():
    cfg = _load_json(ADAMUS_CLIENT_JSON)
    persona = cfg["agent_persona"]
    searchable = (
        persona.get("freeform_notes", "")
        + " "
        + " ".join(persona.get("topics_allowed", []))
    ).lower()
    keywords = ["restaurant", "lunch", "dinner", "reservation", "terrace", "beach"]
    matched = [k for k in keywords if k in searchable]
    assert matched, f"Adamus persona should mention restaurant vocabulary, found none of {keywords}"


def test_adamus_persona_has_no_bluefinn_or_bluemarlin_references():
    """Guard: Adamus persona text must not leak BlueFinn/BlueMarlin vocabulary."""
    cfg = _load_json(ADAMUS_CLIENT_JSON)
    persona_text = json.dumps(cfg["agent_persona"])
    forbidden = ["BlueFinn", "bluefinn", "BlueMarlin", "bluemarlin", "charter", "Charter", "boat", "Boat"]
    present = [f for f in forbidden if f in persona_text]
    assert not present, f"Adamus agent_persona contains forbidden strings: {present}"


# ---------------------------------------------------------------------------
# operating_mode alias field
# ---------------------------------------------------------------------------

def test_bluefinn_operating_mode_matches_booking_flow():
    cfg = _load_json(BLUEFINN_CLIENT_JSON)
    mode = cfg["business"].get("operating_mode")
    booking_flow = cfg["features"].get("booking_flow")
    assert mode == "full_booking", f"BlueFinn operating_mode should be 'full_booking', got {mode!r}"
    assert booking_flow is True, f"BlueFinn booking_flow should be True when mode is full_booking"


def test_adamus_operating_mode_matches_booking_flow():
    cfg = _load_json(ADAMUS_CLIENT_JSON)
    mode = cfg["business"].get("operating_mode")
    booking_flow = cfg["features"].get("booking_flow")
    assert mode == "full_booking", f"Adamus operating_mode should be 'full_booking', got {mode!r}"
    assert booking_flow is True, f"Adamus booking_flow should be True when mode is full_booking"


# ---------------------------------------------------------------------------
# Prompt builder — _build_agent_persona_block()
# ---------------------------------------------------------------------------

def test_build_agent_persona_block_assembles_bluefinn():
    """BlueFinn is the default-loaded config. The assembled block should contain
    all section headings and at least one field from each category."""
    from agents.marina import marina_agent
    block = marina_agent._build_agent_persona_block()

    # Section headings
    assert "Tone:" in block
    assert "Language register:" in block
    assert "Greeting style:" in block
    assert "Closing style:" in block
    assert "Brand voice rules" in block
    assert "Topics you handle:" in block
    assert "Topics you refuse" in block
    assert "Small talk:" in block
    assert "Escalation tone:" in block
    assert "Additional context:" in block

    # Sample content from BlueFinn
    assert "warm, calm, practical" in block
    assert "Never use em-dashes" in block
    assert "Charter trip booking" in block


def test_build_agent_persona_block_contains_all_brand_rules():
    """Every brand_voice_rules item must appear in the assembled block."""
    from agents.marina import marina_agent
    cfg = _load_json(BLUEFINN_CLIENT_JSON)
    rules = cfg["agent_persona"]["brand_voice_rules"]
    block = marina_agent._build_agent_persona_block()
    missing = [r for r in rules if r not in block]
    assert not missing, f"Brand voice rules missing from assembled block: {missing}"


def test_build_agent_persona_block_contains_all_allowed_topics():
    from agents.marina import marina_agent
    cfg = _load_json(BLUEFINN_CLIENT_JSON)
    topics = cfg["agent_persona"]["topics_allowed"]
    block = marina_agent._build_agent_persona_block()
    missing = [t for t in topics if t not in block]
    assert not missing, f"Allowed topics missing from assembled block: {missing}"


def test_build_agent_persona_block_contains_all_refused_topics():
    from agents.marina import marina_agent
    cfg = _load_json(BLUEFINN_CLIENT_JSON)
    topics = cfg["agent_persona"]["topics_refused"]
    block = marina_agent._build_agent_persona_block()
    missing = [t for t in topics if t not in block]
    assert not missing, f"Refused topics missing from assembled block: {missing}"


def test_build_agent_persona_block_fallback_to_legacy(monkeypatch):
    """When agent_persona section is missing, fall back to common_sense_knowledge.marina_persona."""
    from agents.marina import marina_agent
    from shared import config_loader

    monkeypatch.setattr(config_loader, "get_raw", lambda: {})
    monkeypatch.setattr(
        config_loader,
        "get_common_sense_knowledge",
        lambda: {"marina_persona": "LEGACY SENTINEL VALUE"},
    )

    result = marina_agent._build_agent_persona_block()
    assert result == "LEGACY SENTINEL VALUE"


def test_build_agent_persona_block_skips_empty_fields(monkeypatch):
    """Empty fields should not produce empty section headers."""
    from agents.marina import marina_agent
    from shared import config_loader

    monkeypatch.setattr(
        config_loader,
        "get_raw",
        lambda: {"agent_persona": {"tone": "warm", "topics_allowed": ["one", "two"]}},
    )

    block = marina_agent._build_agent_persona_block()
    assert "Tone: warm" in block
    assert "one" in block
    assert "two" in block
    assert "Language register:" not in block
    assert "Greeting style:" not in block
    assert "Closing style:" not in block


def test_system_prompt_contains_agent_persona_section():
    """The new structured block must be injected into the system prompt."""
    from agents.marina import marina_agent
    prompt = marina_agent._build_system_prompt({}, channel="email")
    assert "AGENT PERSONA:" in prompt
    assert "warm, calm, practical" in prompt  # BlueFinn's tone


# ---------------------------------------------------------------------------
# Skip-list guards (prevent double-injection regression)
# ---------------------------------------------------------------------------

def test_marina_agent_skips_agent_persona_in_client_context():
    """Constant-level guard: agent_persona must be in marina_agent._SKIP_TOP_LEVEL."""
    from agents.marina import marina_agent
    assert "agent_persona" in marina_agent._SKIP_TOP_LEVEL


def test_marina_build_client_context_does_not_contain_agent_persona():
    """Loop-body guard: calling _build_client_context() directly must not produce
    a '=== AGENT PERSONA ===' section. Catches a future refactor that drops the
    `if key in _SKIP_TOP_LEVEL` check inside the loop body."""
    from agents.marina import marina_agent
    context = marina_agent._build_client_context()
    assert "=== AGENT PERSONA ===" not in context, \
        "agent_persona leaked into _build_client_context output; double-injection bug"


# ---------------------------------------------------------------------------
# Dashboard migration
# ---------------------------------------------------------------------------

def test_dashboard_draft_email_uses_structured_persona():
    """dashboard/api.py must use _build_agent_persona_block(), not the legacy string."""
    content = _load_text(DASHBOARD_API_PATH)
    assert "_build_agent_persona_block" in content, \
        "dashboard/api.py does not call _build_agent_persona_block — migration incomplete"
    assert 'persona = csk.get("marina_persona"' not in content, \
        "dashboard/api.py still has the legacy persona binding — migration incomplete"
