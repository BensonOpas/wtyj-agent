"""Brief 248: tests for the confirmedTime extraction in escalation summary
+ bridge to appointment_upsert's date_time_label parameter."""
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")


def test_summary_tool_schema_includes_confirmed_time_field():
    """Brief 248: the SUMMARY_TOOL schema MUST include confirmedTime in
    extractedDetails.properties so Claude has a slot to record explicit
    customer confirmations. Required so absence-vs-empty is unambiguous."""
    from dashboard.escalation_summary import SUMMARY_TOOL
    schema = SUMMARY_TOOL["input_schema"]["properties"]
    details_props = schema["extractedDetails"]["properties"]
    assert "confirmedTime" in details_props, (
        f"extractedDetails.properties must include confirmedTime; "
        f"has {sorted(details_props.keys())}")
    assert "confirmedTime" in schema["extractedDetails"]["required"], (
        "confirmedTime must be in extractedDetails.required so Claude "
        "always emits it (empty string when not applicable)")


def test_bridge_uses_confirmed_time_as_date_time_label_when_set(monkeypatch):
    """Brief 248 + 228: when the summary's extractedDetails.confirmedTime
    is populated, the bridge passes it as appointment_upsert's
    date_time_label kwarg (overriding the proposed_times fallback)."""
    from shared import escalation_dispatcher
    from shared import state_registry

    captured = {}
    def fake_upsert(**kw):
        captured.update(kw)
        return 999
    monkeypatch.setattr(state_registry, "appointment_upsert", fake_upsert)
    fake_summary = {
        "extractedDetails": {
            "intent": "scheduling",
            "proposedTimes": ["Thursday 09:00", "Friday 12:00"],
            "confirmedTime": "12:00",
            "topic": "Discovery call",
        },
    }
    monkeypatch.setattr(
        escalation_dispatcher._esc_summary, "generate_summary",
        lambda **kw: fake_summary)
    monkeypatch.setattr(state_registry, "wa_get_full_history",
                         lambda *a, **k: [])

    escalation_dispatcher._generate_escalation_summary(
        escalation_id=1, channel="whatsapp",
        customer_id="248_cust_phone", customer_name="Calvin Test")

    assert captured.get("date_time_label") == "12:00", (
        f"date_time_label must equal confirmedTime when set; "
        f"captured kwargs={captured}")
    assert captured.get("status") == "pending_team_confirmation"
    assert captured.get("proposed_times") == ["Thursday 09:00", "Friday 12:00"]


def test_bridge_falls_back_to_first_proposed_when_no_confirmed_time(monkeypatch):
    """Brief 248: when confirmedTime is empty/missing, the bridge falls
    back to proposed_times[0]. Matches the pre-Brief-248 behavior in
    appointment_upsert (which derived label = pt[0] internally), so
    Brief 228's existing fixture-based test continues to pass."""
    from shared import escalation_dispatcher
    from shared import state_registry

    captured = {}
    monkeypatch.setattr(state_registry, "appointment_upsert",
                         lambda **kw: captured.update(kw) or 999)
    fake_summary = {
        "extractedDetails": {
            "intent": "scheduling",
            "proposedTimes": ["Thursday 09:00", "Friday 12:00"],
            "confirmedTime": "",  # empty -- fall back to proposed[0]
            "topic": "Discovery call",
        },
    }
    monkeypatch.setattr(
        escalation_dispatcher._esc_summary, "generate_summary",
        lambda **kw: fake_summary)
    monkeypatch.setattr(state_registry, "wa_get_full_history",
                         lambda *a, **k: [])

    escalation_dispatcher._generate_escalation_summary(
        escalation_id=2, channel="whatsapp",
        customer_id="248_cust_phone_2", customer_name="Calvin Test")

    assert captured.get("date_time_label") == "Thursday 09:00", (
        f"date_time_label must fall back to first proposed time when "
        f"confirmedTime is empty; captured={captured}")


def test_bridge_uses_empty_label_when_no_times_at_all(monkeypatch):
    """Brief 248: when both confirmedTime AND proposedTimes are empty
    but intent IS scheduling (e.g., 'I want to schedule something soon'
    with no time), the bridge passes empty string for date_time_label
    and status='detected'."""
    from shared import escalation_dispatcher
    from shared import state_registry

    captured = {}
    monkeypatch.setattr(state_registry, "appointment_upsert",
                         lambda **kw: captured.update(kw) or 999)
    fake_summary = {
        "extractedDetails": {
            "intent": "scheduling",
            "proposedTimes": [],
            "confirmedTime": "",
            "topic": "General scheduling intent",
        },
    }
    monkeypatch.setattr(
        escalation_dispatcher._esc_summary, "generate_summary",
        lambda **kw: fake_summary)
    monkeypatch.setattr(state_registry, "wa_get_full_history",
                         lambda *a, **k: [])

    escalation_dispatcher._generate_escalation_summary(
        escalation_id=3, channel="whatsapp",
        customer_id="248_cust_phone_3", customer_name="Calvin Test")

    assert captured.get("date_time_label") == ""
    assert captured.get("status") == "detected"


# ── Brief 252: prompt extracts concrete entities + bans meta-language ─

def test_summary_prompt_includes_concrete_entity_extraction_rule():
    """Brief 252: the system prompt MUST include the entity-extraction
    rule. Distinctive markers from Calvin's issue #20 follow-up that
    distinguish this rule from the existing Brief 248 / Brief 250 rules."""
    from dashboard.escalation_summary import _build_system_prompt
    prompt = _build_system_prompt()
    assert "EXTRACT THE CONCRETE ENTITY" in prompt
    assert "MUST INCLUDE THAT EXACT ENTITY VERBATIM" in prompt
    assert "updated request" in prompt
    assert "their latest message" in prompt
    assert "based on their reply" in prompt


def test_summary_prompt_includes_concrete_do_examples():
    """Brief 252: the prompt MUST include positive DO examples that
    show Claude what concrete entity extraction looks like (not just
    the negative DO NOT)."""
    from dashboard.escalation_summary import _build_system_prompt
    prompt = _build_system_prompt()
    assert "Move or confirm the appointment at 10:30" in prompt
    assert "Confirm whether 10:30 is available" in prompt
    assert "USE THE TIME" in prompt
    assert "USE THE SERVICE" in prompt
    assert "INCLUDE THE REASON" in prompt


def test_summary_prompt_preserves_brief_248_and_250_rules():
    """Brief 252 regression: the helper extraction must not drop the
    earlier Brief 248 (confirmedTime) or Brief 250 (latest-message
    anchoring) rules. Both must remain in the prompt verbatim."""
    from dashboard.escalation_summary import _build_system_prompt
    prompt = _build_system_prompt()
    assert "When in doubt, leave confirmedTime empty" in prompt
    assert "what was being decided 20 messages ago" in prompt
    assert "we will be there at 12:00" in prompt
