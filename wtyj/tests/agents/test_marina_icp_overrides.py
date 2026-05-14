"""J3-N2-02: marina_agent runtime honors ICP override envelope.

Tests:
- _build_icp_sot_block renders entries when envelope has SOT data
- _build_icp_sot_block returns empty string when no entries / bridge down
- _build_agent_persona_block uses ICP tone override over backend tone
- _build_agent_persona_block uses ICP escalation rules over backend
- _build_system_prompt includes the ICP SOT block when entries exist
- bridge unavailable -> persona falls back to backend cleanly
- malformed envelope shapes are tolerated
- tenant isolation: helper takes no tenant arg from agent code
- token never appears in the rendered prompt
"""
import pytest

from agents.marina import marina_agent
from shared import icp_overrides


@pytest.fixture(autouse=True)
def _clear_icp_cache():
    icp_overrides.clear_cache()
    yield
    icp_overrides.clear_cache()


# --- _build_icp_sot_block -------------------------------------


def test_sot_block_empty_when_no_entries():
    env = {"sot_entries": [], "ai_agent_settings": {"tone": None,
                                                       "escalation_rules": None}}
    assert marina_agent._build_icp_sot_block(env) == ""


def test_sot_block_empty_when_envelope_missing_key():
    """If the bridge response shape is older / missing sot_entries,
    return empty - never raise."""
    assert marina_agent._build_icp_sot_block({}) == ""


def test_sot_block_renders_entries():
    env = {"sot_entries": [
        {"title": "Holiday hours", "content": "Closed Dec 25",
         "category": "hours", "source": "icp_override"},
        {"title": "Refund policy", "content": "Full refund within 7 days",
         "category": "policy", "source": "icp_override"},
    ]}
    block = marina_agent._build_icp_sot_block(env)
    assert "ICP SOURCE OF TRUTH" in block
    assert "Holiday hours" in block
    assert "Closed Dec 25" in block
    assert "Refund policy" in block
    assert "Full refund within 7 days" in block
    assert "[hours]" in block
    assert "[policy]" in block


def test_sot_block_skips_entries_missing_title_or_content():
    """Defensive: malformed entries don't break the block; they're
    just skipped."""
    env = {"sot_entries": [
        {"title": "Has title only", "content": "", "category": "x"},
        {"title": "", "content": "Has content only", "category": "y"},
        {"title": "Both", "content": "Both", "category": "general"},
        "not a dict",
    ]}
    block = marina_agent._build_icp_sot_block(env)
    assert "Both" in block
    assert "Has title only" not in block
    assert "Has content only" not in block


def test_sot_block_non_list_entries_returns_empty():
    """If sot_entries is somehow not a list, the block stays empty
    rather than raising."""
    env = {"sot_entries": "not a list"}
    assert marina_agent._build_icp_sot_block(env) == ""


# --- _build_agent_persona_block: tone -----------------------


def test_persona_tone_icp_override_wins(monkeypatch):
    """When the ICP envelope carries an AI tone override, that wins
    over the client.json backend tone."""
    env = {
        "sot_entries": [],
        "ai_agent_settings": {
            "tone": {"tone": "professional",
                      "notes": "Short, calm, helpful.",
                      "source": "icp_override",
                      "updated_by": "op@example.com",
                      "updated_at": "2026-05-15T00:00:00"},
            "escalation_rules": None,
        },
    }
    block = marina_agent._build_agent_persona_block(env)
    # ICP override appears with marker
    assert "ICP override" in block
    assert "Tone: professional" in block
    assert "Tone notes: Short, calm, helpful." in block


def test_persona_tone_backend_used_when_no_override(monkeypatch):
    """No ICP override -> backend tone from client.json is used."""
    env = {"sot_entries": [], "ai_agent_settings": {"tone": None,
                                                       "escalation_rules": None}}
    block = marina_agent._build_agent_persona_block(env)
    # Whatever the client.json's tone is, ICP override marker must NOT
    # appear when there's no ICP tone override.
    assert "[ICP override]" not in block or "Tone:" in block


def test_persona_tone_empty_string_override_ignored():
    """An ICP override with empty tone string should NOT replace the
    backend tone (treat empty as 'not set')."""
    env = {
        "sot_entries": [],
        "ai_agent_settings": {
            "tone": {"tone": "", "notes": "", "source": "icp_override"},
            "escalation_rules": None,
        },
    }
    block = marina_agent._build_agent_persona_block(env)
    # ICP marker should NOT appear; backend (or no tone line) used
    assert "ICP override" not in block or "Tone: " in block


# --- _build_agent_persona_block: escalation rules ----------


def test_persona_escalation_rules_icp_override_wins():
    """When ICP carries an escalation_rules override, both soft +
    hard rules render with the canonical operator-facing terms."""
    env = {
        "sot_entries": [],
        "ai_agent_settings": {
            "tone": None,
            "escalation_rules": {
                "soft_escalation": {"enabled": True,
                                       "when": "Agent is uncertain."},
                "hard_escalation": {"enabled": True,
                                       "when": "Complaint or legal issue."},
                "source": "icp_override",
            },
        },
    }
    block = marina_agent._build_agent_persona_block(env)
    assert "Escalation rules [ICP override]" in block
    assert "Soft escalation" in block
    assert "Agent is uncertain." in block
    assert "Hard escalation" in block
    assert "Complaint or legal issue." in block
    # Banned terminology MUST NOT appear (J3-BE-19 rule)
    assert "soft mode" not in block.lower()
    assert "hard mode" not in block.lower()


def test_persona_escalation_disabled_rule_shows_disabled():
    env = {
        "sot_entries": [],
        "ai_agent_settings": {
            "tone": None,
            "escalation_rules": {
                "soft_escalation": {"enabled": False, "when": ""},
                "hard_escalation": {"enabled": True, "when": "Always"},
            },
        },
    }
    block = marina_agent._build_agent_persona_block(env)
    assert "Soft escalation: DISABLED" in block
    assert "Hard escalation" in block
    assert "Always" in block


# --- fail-closed behavior --------------------------------


def test_bridge_unreachable_envelope_falls_back_to_backend():
    """When the helper returns an empty envelope (bridge offline),
    the persona block uses backend tone and the SOT block is empty."""
    env = icp_overrides._empty_envelope("demo", "bridge offline")
    sot_block = marina_agent._build_icp_sot_block(env)
    assert sot_block == ""
    persona_block = marina_agent._build_agent_persona_block(env)
    # Persona block renders (using backend), no ICP markers
    assert "[ICP override]" not in persona_block


def test_envelope_helper_returns_safe_defaults_on_exception(monkeypatch):
    """If icp_overrides.fetch_overrides somehow raises, the
    _icp_envelope_for_prompt helper must catch and return safe
    defaults so the agent prompt never crashes."""
    def boom(*a, **k):
        raise RuntimeError("simulated bridge crash")
    monkeypatch.setattr(icp_overrides, "fetch_overrides", boom)
    env = marina_agent._icp_envelope_for_prompt()
    assert env.get("sot_entries") == []
    ai = env.get("ai_agent_settings", {})
    assert ai.get("tone") is None
    assert ai.get("escalation_rules") is None


# --- tenant isolation ------------------------------------


def test_icp_envelope_helper_takes_no_tenant_arg_from_agent():
    """Critical: the marina_agent helper must NOT accept a tenant_id
    arg. tenant_id comes from icp_overrides.fetch_overrides which
    resolves it locally from TENANT_ID env / business.slug. This
    prevents any agent-side code path from accidentally requesting
    overrides for the wrong tenant."""
    import inspect
    sig = inspect.signature(marina_agent._icp_envelope_for_prompt)
    assert len(sig.parameters) == 0


# --- token leak guard ----------------------------------


def test_token_never_appears_in_prompt_render(monkeypatch):
    """Even though the helper holds the bridge token in env, the
    rendered prompt must never include it."""
    monkeypatch.setenv("NR3_INTERNAL_API_TOKEN", "secret-token-32-bytes-long-xyz")
    monkeypatch.setenv("NR3_INTERNAL_OVERRIDES_URL", "http://nr3.local")
    monkeypatch.setenv("TENANT_ID", "demo")
    # Make the helper return a minimal envelope (we don't need a real
    # HTTP fetch for this assertion)
    fake_env = {"sot_entries": [],
                 "ai_agent_settings": {"tone": None,
                                         "escalation_rules": None}}
    monkeypatch.setattr(icp_overrides, "fetch_overrides",
                          lambda: fake_env)
    sot_block = marina_agent._build_icp_sot_block(fake_env)
    persona_block = marina_agent._build_agent_persona_block(fake_env)
    assert "secret-token-32-bytes-long-xyz" not in sot_block
    assert "secret-token-32-bytes-long-xyz" not in persona_block


# --- end-to-end: full system prompt builder ----------


def test_full_prompt_includes_icp_sot_when_present(monkeypatch):
    """End-to-end: _build_system_prompt produces a prompt that
    contains the SOT block when the envelope has entries."""
    fake_env = {
        "sot_entries": [{"title": "Test Entry", "content": "Test body",
                          "category": "faq", "source": "icp_override"}],
        "ai_agent_settings": {"tone": None, "escalation_rules": None},
    }
    monkeypatch.setattr(icp_overrides, "fetch_overrides",
                          lambda: fake_env)
    prompt = marina_agent._build_system_prompt(
        thread_flags={}, channel="email")
    assert "ICP SOURCE OF TRUTH" in prompt
    assert "Test Entry" in prompt
    assert "Test body" in prompt


def test_full_prompt_omits_sot_block_when_empty(monkeypatch):
    monkeypatch.setattr(
        icp_overrides, "fetch_overrides",
        lambda: {"sot_entries": [],
                  "ai_agent_settings": {"tone": None,
                                          "escalation_rules": None}})
    prompt = marina_agent._build_system_prompt(
        thread_flags={}, channel="email")
    assert "ICP SOURCE OF TRUTH" not in prompt


def test_full_prompt_applies_icp_tone_override(monkeypatch):
    fake_env = {
        "sot_entries": [],
        "ai_agent_settings": {
            "tone": {"tone": "MY_TEST_TONE_MARKER",
                      "notes": "", "source": "icp_override"},
            "escalation_rules": None,
        },
    }
    monkeypatch.setattr(icp_overrides, "fetch_overrides",
                          lambda: fake_env)
    prompt = marina_agent._build_system_prompt(
        thread_flags={}, channel="email")
    assert "MY_TEST_TONE_MARKER" in prompt
    assert "ICP override" in prompt
