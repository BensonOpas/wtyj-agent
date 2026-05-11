"""Brief 201: em-dash strip in dm_agent + dashboard message field aliases."""

import os

# Match established test pattern (see test_125, test_173, test_186, etc.) —
# DASHBOARD_PASSWORD must be set BEFORE importing the dashboard module so the
# auth handler reads our test password rather than a missing env var.
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from unittest.mock import MagicMock, patch

import pytest


# ── Part 1: em-dash strip ────────────────────────────────────────────────────
# Module path is `agents.social.dm_agent` (NOT `wtyj.agents.social.dm_agent`)
# because conftest.py adds `wtyj/` to sys.path — see existing tests like
# test_068_pipeline.py:144 which uses `agents.social.social_agent.marina_agent`.

@patch("agents.social.dm_agent.state_registry")
@patch("agents.social.dm_agent.config_loader")
@patch("agents.social.dm_agent.anthropic.Anthropic")
@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
def test_em_dash_replaced_with_comma(mock_anthropic, mock_config, mock_state):
    """An em-dash in Claude's reply is replaced with a comma."""
    from agents.social import dm_agent

    # Stub config_loader so _build_dm_system_prompt doesn't blow up
    mock_config.get_business.return_value = {"agent_name": "Calvin", "name": "Unboks", "whatsapp": "", "languages": ["English"]}
    mock_config.get_common_sense_knowledge.return_value = {}
    mock_config.get_services.return_value = {}
    mock_config.get_faq.return_value = {}
    mock_config.get_raw.return_value = {"terminology": {}}
    mock_state.dm_get_history.return_value = []

    # Stub Claude response with em-dash in reply
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="Hello — how can I help?")]
    mock_msg.usage = None
    mock_anthropic.return_value.messages.create.return_value = mock_msg

    reply = dm_agent.handle_incoming_dm({
        "conversation_id": "test-conv",
        "platform": "whatsapp",
        "channel": "whatsapp",
        "sender_name": "TestUser",
        "text": "hi",
        "account_id": "acct-1",
    })

    assert "—" not in reply
    assert "," in reply
    # The space normalizer collapses double spaces but leaves single-space-comma-single-space.
    # We verify the em-dash is gone and a comma is present — not the exact whitespace.


@patch("agents.social.dm_agent.state_registry")
@patch("agents.social.dm_agent.config_loader")
@patch("agents.social.dm_agent.anthropic.Anthropic")
@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
def test_no_em_dash_passes_through_unchanged(mock_anthropic, mock_config, mock_state):
    """A reply with no em-dash is returned unchanged (no false replacements)."""
    from agents.social import dm_agent

    mock_config.get_business.return_value = {"agent_name": "Calvin", "name": "Unboks", "whatsapp": "", "languages": ["English"]}
    mock_config.get_common_sense_knowledge.return_value = {}
    mock_config.get_services.return_value = {}
    mock_config.get_faq.return_value = {}
    mock_config.get_raw.return_value = {"terminology": {}}
    mock_state.dm_get_history.return_value = []

    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="Hello, how can I help?")]
    mock_msg.usage = None
    mock_anthropic.return_value.messages.create.return_value = mock_msg

    reply = dm_agent.handle_incoming_dm({
        "conversation_id": "test-conv-2",
        "platform": "whatsapp",
        "channel": "whatsapp",
        "sender_name": "TestUser",
        "text": "hi",
        "account_id": "acct-1",
    })

    assert reply == "Hello, how can I help?"


# ── Part 2: dashboard detail-endpoint field aliases ───────────────────────

def test_wa_get_full_history_includes_id():
    """state_registry.wa_get_full_history returns dicts that include the row id."""
    from shared import state_registry

    # Use a unique phone to isolate from other tests
    phone = "test-201-phone-aliases"
    state_registry.wa_store_message(phone, "user", "first message")
    state_registry.wa_store_message(phone, "assistant", "second message")

    history = state_registry.wa_get_full_history(phone, limit=10)
    assert len(history) == 2
    assert "id" in history[0]
    assert "id" in history[1]
    assert isinstance(history[0]["id"], int)
    # IDs are strictly increasing (insertion order matches created_at order)
    assert history[1]["id"] > history[0]["id"]


def test_get_conversation_endpoint_adds_content_and_timestamp_aliases():
    """The dashboard get_conversation endpoint enriches messages with `content`
    and `timestamp` aliases (matching SR's frontend's expected shape)."""
    from fastapi.testclient import TestClient
    from agents.social.webhook_server import app
    from shared import state_registry

    # Seed the DB with two messages on a unique phone
    phone = "test-201-aliases-phone"
    state_registry.wa_store_message(phone, "user", "incoming text")
    state_registry.wa_store_message(phone, "assistant", "outgoing text")

    client = TestClient(app)

    # Login first to get auth token. Password matches the module-level
    # os.environ.setdefault("DASHBOARD_PASSWORD", "testpass") at the top.
    login = client.post("/dashboard/api/login", json={"password": "testpass"})
    assert login.status_code == 200
    token = login.json()["token"]

    # Hit the detail endpoint
    resp = client.get(
        f"/dashboard/api/messages/conversations/{phone}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "messages" in body
    assert len(body["messages"]) == 2

    for m in body["messages"]:
        # Originals preserved (backward-compat)
        assert "text" in m
        assert "created_at" in m
        # New aliases present
        assert "content" in m
        assert "timestamp" in m
        # Aliases match originals
        assert m["content"] == m["text"]
        assert m["timestamp"] == m["created_at"]
        # id passes through from state_registry
        assert "id" in m


# ── Brief 250: wa_get_full_history must return MOST RECENT N when total > limit ─

def test_wa_get_full_history_returns_most_recent_when_total_exceeds_limit():
    """Brief 250: when a conversation has more messages than `limit`,
    the function MUST return the most-recent `limit` messages, not the
    oldest. Pre-Brief-250 the SQL was `ORDER BY ASC LIMIT ?` which
    returned the oldest N -- silently truncating the messages Claude
    needed to see in the escalation summary (issue #20 root cause)."""
    from shared import state_registry
    phone = "250_recent_phone"
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()
    # Seed 25 messages with sequential text. msg_0 is oldest, msg_24 is newest.
    for i in range(25):
        state_registry.wa_store_message(phone, "user", f"msg_{i}")
    history = state_registry.wa_get_full_history(phone, limit=10)
    assert len(history) == 10, f"expected 10 entries, got {len(history)}"
    texts = [m["text"] for m in history]
    assert texts[-1] == "msg_24", (
        f"last entry must be the most recent (msg_24); got {texts[-1]!r}")
    assert texts[0] == "msg_15", (
        f"first entry must be msg_15 (10th newest); got {texts[0]!r}")
    assert "msg_0" not in texts, (
        f"msg_0 (oldest) MUST NOT be in the most-recent 10; "
        f"this would indicate the pre-Brief-250 ASC bug; texts={texts}")
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


def test_wa_get_full_history_preserves_oldest_first_output_order():
    """Brief 250: even though the SELECT now picks the newest N, the
    output order is still oldest-first (callers iterate forward through
    time). Backward-compat with all 5 production callers."""
    from shared import state_registry
    phone = "250_order_phone"
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()
    for i in range(5):
        state_registry.wa_store_message(phone, "user", f"order_{i}")
    history = state_registry.wa_get_full_history(phone, limit=10)
    assert len(history) == 5
    texts = [m["text"] for m in history]
    assert texts == ["order_0", "order_1", "order_2", "order_3", "order_4"], (
        f"output must be oldest-first (order_0 first, order_4 last); "
        f"got {texts}")
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


def test_wa_get_full_history_returns_all_when_total_below_limit():
    """Brief 250: when total messages <= limit, behavior is unchanged
    from pre-Brief-250 -- all messages returned, oldest-first. This is
    the common case for short conversations and dashboard full-history
    views (limit=200)."""
    from shared import state_registry
    phone = "250_below_limit_phone"
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()
    for i in range(3):
        state_registry.wa_store_message(phone, "user", f"all_{i}")
    history = state_registry.wa_get_full_history(phone, limit=100)
    assert [m["text"] for m in history] == ["all_0", "all_1", "all_2"]
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()
