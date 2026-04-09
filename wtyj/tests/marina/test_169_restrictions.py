"""Tests for Brief 169 — Marina restrictions audit (HARD REFUSAL RULES block)."""
import os

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from agents.marina import marina_agent


def test_hard_refusal_rules_block_in_whatsapp_prompt():
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "HARD REFUSAL RULES" in prompt
    # Key forbidden categories explicit
    assert "Jokes" in prompt
    assert "Political opinions" in prompt
    assert "Ethical, moral, or philosophical advice" in prompt
    assert "Medical advice" in prompt
    assert "Legal advice" in prompt


def test_hard_refusal_rules_block_in_email_prompt():
    prompt = marina_agent._build_system_prompt({}, channel="email")
    assert "HARD REFUSAL RULES" in prompt
    assert "Political opinions" in prompt


def test_hard_refusal_rules_include_redirect_guidance():
    """Brief 169: refusals should include guidance to redirect to the business,
    not just refuse bluntly."""
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "redirect" in prompt.lower() or "pivot" in prompt.lower()
    assert "booking" in prompt.lower()


def test_scope_statement_present():
    """Brief 169: the prompt must explicitly state Marina's strict scope."""
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "scope is strictly" in prompt.lower() or "strictly:" in prompt.lower()
