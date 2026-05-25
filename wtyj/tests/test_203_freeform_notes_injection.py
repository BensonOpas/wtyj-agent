"""Brief 203: agent_persona.freeform_notes injection in dm_agent system prompt."""

import os

# Match established test pattern; module-level setdefault before any imports.
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from unittest.mock import MagicMock, patch


# ── Mode 1: master prompt set ───────────────────────────────────────────────

@patch("agents.social.dm_agent.config_loader")
def test_master_prompt_replaces_hardcoded_writing_style(mock_config):
    """When agent_persona.freeform_notes is set, the rendered system prompt contains
    the master prompt block AND skips the hardcoded WRITING STYLE / AVOID blocks."""
    from agents.social.dm_agent import _build_dm_system_prompt

    master_prompt = "You are the Unboks AI assistant.\nNo em dashes. Use commas, periods, or colons."
    mock_config.get_business.return_value = {
        "agent_name": "Calvin", "name": "Unboks", "whatsapp": "", "languages": ["English"]
    }
    mock_config.get_common_sense_knowledge.return_value = {}
    mock_config.get_services.return_value = {}
    mock_config.get_faq.return_value = {}
    mock_config.get_raw.return_value = {
        "terminology": {},
        "agent_persona": {"freeform_notes": master_prompt},
    }

    prompt = _build_dm_system_prompt("whatsapp")

    # Master prompt content present
    assert "You are the Unboks AI assistant." in prompt
    assert "No em dashes" in prompt
    # Hardcoded WRITING STYLE / AVOID blocks NOT present
    assert "WRITING STYLE:" not in prompt
    assert "Sound like a real person texting from work" not in prompt
    assert 'AVOID: em dashes, "Shall I"' not in prompt


@patch("agents.social.dm_agent.config_loader")
def test_master_prompt_mode_keeps_structural_blocks(mock_config):
    """Master prompt mode still appends services, FAQ, booking redirect, language line."""
    from agents.social.dm_agent import _build_dm_system_prompt

    mock_config.get_business.return_value = {
        "agent_name": "Calvin", "name": "Unboks", "whatsapp": "+59912345",
        "languages": ["English", "Papiamentu"],
        "booking_email": "hello@unboks.org",
    }
    mock_config.get_common_sense_knowledge.return_value = {}
    mock_config.get_services.return_value = {
        "consultation": {"display_name": "Strategy Consultation", "description": "1-hour consult"},
    }
    mock_config.get_faq.return_value = {"how_long": "About 30 minutes."}
    mock_config.get_raw.return_value = {
        "terminology": {"service_label": "service"},
        "agent_persona": {"freeform_notes": "You are Calvin from Unboks."},
    }

    prompt = _build_dm_system_prompt("whatsapp")

    # Master prompt present
    assert "You are Calvin from Unboks." in prompt
    # Structural blocks present
    assert "Strategy Consultation" in prompt
    # Existing FAQ rendering uses q.replace('_', ' ').title() — pin the exact
    # title-cased form rather than hedging case-insensitive. If a future change
    # alters the case treatment, this should fail loudly.
    assert "How Long" in prompt
    assert "BOOKING REDIRECT" in prompt
    assert "wa.me/59912345" in prompt
    assert "hello@unboks.org" in prompt
    assert "Papiamentu" in prompt


# ── Mode 2: master prompt absent ────────────────────────────────────────────

@patch("agents.social.dm_agent.config_loader")
def test_no_master_prompt_falls_back_to_hardcoded_writing_style(mock_config):
    """When agent_persona is absent or freeform_notes is empty, the hardcoded
    WRITING STYLE / AVOID blocks ARE present (full backward-compat path)."""
    from agents.social.dm_agent import _build_dm_system_prompt

    mock_config.get_business.return_value = {
        "agent_name": "Marina", "name": "BlueMarlin Charters", "whatsapp": "+59999999",
        "languages": ["English"],
    }
    mock_config.get_common_sense_knowledge.return_value = {}
    mock_config.get_services.return_value = {}
    mock_config.get_faq.return_value = {}
    mock_config.get_raw.return_value = {"terminology": {}}  # NO agent_persona key at all

    prompt = _build_dm_system_prompt("whatsapp")

    assert "WRITING STYLE:" in prompt
    assert "Sound like a real person texting from work" in prompt
    assert 'AVOID: em dashes' in prompt


@patch("agents.social.dm_agent.icp_overrides.fetch_overrides")
@patch("agents.social.dm_agent.config_loader")
def test_dm_prompt_includes_icp_sot_and_tone_overrides(mock_config, mock_fetch):
    """Q&A-only DM prompt path must consume Nr3 SOT/tone like Marina does."""
    from agents.social.dm_agent import _build_dm_system_prompt

    mock_config.get_business.return_value = {
        "agent_name": "Marina", "name": "Clinic", "whatsapp": "+59999999",
        "languages": ["English"],
    }
    mock_config.get_common_sense_knowledge.return_value = {}
    mock_config.get_services.return_value = {}
    mock_config.get_faq.return_value = {}
    mock_config.get_raw.return_value = {
        "terminology": {},
        "features": {"booking_flow": False},
        "agent_persona": {"freeform_notes": "Base master prompt."},
    }
    mock_fetch.return_value = {
        "available": True,
        "sot_entries": [{
            "title": "Roberto intake rule",
            "content": "Collect center preference, horario, full name, phone, and reason before handoff.",
            "category": "appointments",
        }],
        "ai_agent_settings": {
            "tone": {
                "tone": "Warm, calm Spanish clinic receptionist",
                "notes": "Do not sound robotic.",
                "source": "icp_override",
            },
            "escalation_rules": None,
        },
    }

    prompt = _build_dm_system_prompt("instagram_dm")

    assert "FINAL TENANT-SPECIFIC OPERATOR OVERRIDES FROM NR3" in prompt
    assert "Roberto intake rule" in prompt
    assert "Collect center preference" in prompt
    assert "Warm, calm Spanish clinic receptionist" in prompt
    assert "Do not sound robotic" in prompt


# ── End-to-end: full handle_incoming_dm flow with master prompt ────────────

@patch("agents.social.dm_agent.state_registry")
@patch("agents.social.dm_agent.config_loader")
@patch("agents.social.dm_agent.anthropic.Anthropic")
def test_full_dm_flow_with_master_prompt_and_em_dash_post_process(
    mock_anthropic, mock_config, mock_state
):
    """End-to-end: handle_incoming_dm with master prompt loaded, Claude returns reply
    containing an em-dash, post-process strips it (Brief 201 behavior preserved)."""
    from agents.social import dm_agent

    mock_config.get_business.return_value = {
        "agent_name": "Calvin", "name": "Unboks", "whatsapp": "", "languages": ["English"]
    }
    mock_config.get_common_sense_knowledge.return_value = {}
    mock_config.get_services.return_value = {}
    mock_config.get_faq.return_value = {}
    mock_config.get_raw.return_value = {
        "terminology": {},
        "agent_persona": {"freeform_notes": "You are the Unboks AI."},
    }
    mock_state.dm_get_history.return_value = []

    # Claude returns a reply with em-dashes — should be stripped by Brief 201 post-process
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="Sure — I can help. We do support that — yes.")]
    mock_msg.usage = None
    mock_anthropic.return_value.messages.create.return_value = mock_msg

    reply = dm_agent.handle_incoming_dm({
        "conversation_id": "test-203-e2e",
        "platform": "whatsapp",
        "channel": "whatsapp",
        "sender_name": "TestProspect",
        "text": "Hi, what does Unboks do?",
        "account_id": "acct-1",
    })

    # Em-dash stripped (Brief 201 post-process)
    assert "—" not in reply
    assert "," in reply
    # Master prompt was actually used (was passed to Claude)
    sys_prompt_arg = mock_anthropic.return_value.messages.create.call_args.kwargs["system"]
    assert "You are the Unboks AI." in sys_prompt_arg
    assert "WRITING STYLE:" not in sys_prompt_arg  # confirmed not in fallback mode
