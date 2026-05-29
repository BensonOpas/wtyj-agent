# bluemarlin/tests/social/test_076_debounce.py
# Created: Brief 076
# Purpose: Tests for WhatsApp message debouncing and rate limit at 50

import os
import sys
import time
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

os.environ["WHATSAPP_VERIFY_TOKEN"] = "test_token_067"
os.environ["WHATSAPP_ACCESS_TOKEN"] = "test_access_token"
os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "990622044139349"

from agents.social.webhook_server import (
    _buffer_message, _flush_buffer, _message_buffers, _buffer_lock,
)
from agents.social.social_agent import handle_incoming_whatsapp_message
from shared import state_registry


# --- Cleanup fixture ---

@pytest.fixture(autouse=True)
def cleanup_buffers():
    """Cancel all active timers and clear buffers before and after each test."""
    def _clear():
        with _buffer_lock:
            for phone, buf in list(_message_buffers.items()):
                if buf.get("timer") is not None:
                    buf["timer"].cancel()
            _message_buffers.clear()
    _clear()
    yield
    _clear()


# --- Helpers ---

def _cleanup_phone(phone):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM service_bookings WHERE customer_email = ?", (phone,))
    conn.commit()
    conn.close()


def _base_result(**overrides):
    """Build a base marina_agent result dict with overrides."""
    base = {
        "intents": ["inquiry"],
        "fields": {},
        "confidence": "high",
        "reply": "Default reply.",
        "clarifications_needed": [],
        "requires_human": False,
        "flags": {},
        "internal_note": "",
    }
    base.update(overrides)
    return base


# --- Test 1: Single message flushes after debounce window ---

@patch("agents.social.webhook_server.send_text_message")
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
def test_single_message_flush(mock_handle, mock_send):
    """Single message is buffered, then flushed with original text."""
    phone = "TEST_076_SINGLE_001"
    mock_handle.return_value = "Got it!"
    msg = {"from": phone, "text": "hello", "from_name": "Test", "message_type": "text"}
    _buffer_message(msg)
    assert phone in _message_buffers
    assert len(_message_buffers[phone]["messages"]) == 1
    # Cancel timer and flush manually
    _message_buffers[phone]["timer"].cancel()
    _flush_buffer(phone)
    mock_handle.assert_called_once()
    assert mock_handle.call_args[0][0]["text"] == "hello"
    assert phone not in _message_buffers


# --- Test 2: Rapid-fire messages batched into one ---

@patch("agents.social.webhook_server.send_text_message")
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
def test_rapid_fire_batched(mock_handle, mock_send):
    """Multiple messages from same phone are concatenated into one."""
    phone = "TEST_076_BATCH_001"
    mock_handle.return_value = "Noted!"
    _buffer_message({"from": phone, "text": "book snorkeling", "from_name": "Test", "message_type": "text"})
    _buffer_message({"from": phone, "text": "for 4 people", "from_name": "Test", "message_type": "text"})
    _buffer_message({"from": phone, "text": "march 27", "from_name": "Test", "message_type": "text"})
    with _buffer_lock:
        _message_buffers[phone]["timer"].cancel()
    _flush_buffer(phone)
    mock_handle.assert_called_once()
    assert mock_handle.call_args[0][0]["text"] == "book snorkeling\nfor 4 people\nmarch 27"


def test_buffer_uses_tenant_response_timing(monkeypatch):
    """Timer delay comes from tenant/Nr3 response timing, not hardcoded 2s."""
    phone = "TEST_076_TIMING_001"
    monkeypatch.setattr(
        "agents.social.webhook_server.icp_overrides.fetch_overrides",
        lambda: {
            "response_timing": {
                "settings": {
                    "message_batching_enabled": True,
                    "preset": "patient",
                    "delay_seconds": 15,
                    "max_wait_seconds": 25,
                },
                "source": "icp_override",
            }
        },
    )
    _buffer_message({"from": phone, "text": "hello", "from_name": "Test", "message_type": "text"})
    with _buffer_lock:
        timer = _message_buffers[phone]["timer"]
        timing = _message_buffers[phone]["timing"]
        timer.cancel()
    assert timing["delay_seconds"] == 15.0
    assert timing["max_wait_seconds"] == 25.0


def test_blocked_conversation_flushes_immediately(monkeypatch):
    phone = "TEST_076_BLOCKED_TIMING"
    monkeypatch.setattr(
        "agents.social.webhook_server.state_registry.get_blocked",
        lambda conversation_id: True,
    )
    _buffer_message({"from": phone, "text": "hello", "from_name": "Test", "message_type": "text"})
    with _buffer_lock:
        timer = _message_buffers[phone]["timer"]
        timing = _message_buffers[phone]["timing"]
        timer.cancel()
    assert timing["source"] == "immediate_runtime_state"
    assert timing["delay_seconds"] == 0.1


def test_random_timing_is_sampled_once_per_batch(monkeypatch):
    phone = "TEST_076_RANDOM_TIMING"
    monkeypatch.setattr(
        "agents.social.webhook_server.icp_overrides.fetch_overrides",
        lambda: {
            "response_timing": {
                "settings": {
                    "message_batching_enabled": True,
                    "mode": "random",
                    "preset": "balanced",
                    "delay_seconds": 12,
                    "max_wait_seconds": 25,
                    "random_min_seconds": 100,
                    "random_max_seconds": 100,
                },
                "source": "icp_override",
            }
        },
    )
    _buffer_message({"from": phone, "text": "one", "from_name": "Test", "message_type": "text"})
    _buffer_message({"from": phone, "text": "two", "from_name": "Test", "message_type": "text"})
    with _buffer_lock:
        timer = _message_buffers[phone]["timer"]
        timing = _message_buffers[phone]["timing"]
        timer.cancel()
    assert timing["mode"] == "random"
    assert timing["delay_seconds"] == 100.0
    assert timing["random_picked_seconds"] == 100.0


# --- Test 3: Different phones don't batch together ---

@patch("agents.social.webhook_server.send_text_message")
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
def test_different_phones_separate(mock_handle, mock_send):
    """Messages from different phones are processed independently."""
    phone_a = "TEST_076_PHONEA"
    phone_b = "TEST_076_PHONEB"
    mock_handle.return_value = "Reply!"
    _buffer_message({"from": phone_a, "text": "hello", "from_name": "Alice", "message_type": "text"})
    _buffer_message({"from": phone_b, "text": "hi there", "from_name": "Bob", "message_type": "text"})
    with _buffer_lock:
        _message_buffers[phone_a]["timer"].cancel()
        _message_buffers[phone_b]["timer"].cancel()
    _flush_buffer(phone_a)
    _flush_buffer(phone_b)
    assert mock_handle.call_count == 2
    first_text = mock_handle.call_args_list[0][0][0]["text"]
    second_text = mock_handle.call_args_list[1][0][0]["text"]
    assert first_text == "hello"
    assert second_text == "hi there"


# --- Test 4: Flush with empty buffer is no-op ---

@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
def test_flush_empty_noop(mock_handle):
    """Flushing a non-existent phone buffer does nothing."""
    _flush_buffer("NONEXISTENT_PHONE")
    assert mock_handle.call_count == 0


# --- Test 5: Rate limit at 50 blocks ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_rate_limit_50_blocks(mock_process):
    """50 reply_times within the hour → rate limited, empty reply."""
    phone = "TEST_076_RATE_001"
    _cleanup_phone(phone)
    now = int(time.time())
    reply_times = [now - i * 60 for i in range(50)]
    state_registry.wa_save_booking_state(phone, {}, {"reply_times": reply_times})
    msg = {"from": phone, "text": "Hello", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == ""
    assert mock_process.call_count == 0
    _cleanup_phone(phone)


# --- Test 6: Rate limit at 49 allows ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_rate_limit_49_allows(mock_process):
    """49 reply_times within the hour → still under limit, call proceeds."""
    phone = "TEST_076_RATE_002"
    _cleanup_phone(phone)
    now = int(time.time())
    reply_times = [now - i * 60 for i in range(49)]
    state_registry.wa_save_booking_state(phone, {}, {"reply_times": reply_times})
    mock_process.return_value = _base_result(
        intents=["inquiry"],
        reply="Happy to help!",
    )
    msg = {"from": phone, "text": "Hi there", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert reply == "Happy to help!"
    assert mock_process.call_count == 1
    _cleanup_phone(phone)


# --- Test 7: Batched message stores combined text in thread history ---

@patch("agents.social.webhook_server.state_registry.wa_store_message")
@patch("agents.social.webhook_server.send_text_message")
@patch("agents.social.webhook_server.handle_incoming_whatsapp_message")
def test_batched_stores_combined_text(mock_handle, mock_send, mock_store):
    """Flushed batch stores the combined text in thread history."""
    phone = "TEST_076_STORE_001"
    mock_handle.return_value = "Got it!"
    _buffer_message({"from": phone, "text": "msg1", "from_name": "Test", "message_type": "text"})
    _buffer_message({"from": phone, "text": "msg2", "from_name": "Test", "message_type": "text"})
    with _buffer_lock:
        _message_buffers[phone]["timer"].cancel()
    _flush_buffer(phone)
    # wa_store_message called as: wa_store_message(phone, "user", combined_text)
    user_call = mock_store.call_args_list[0]
    assert user_call[0][0] == phone
    assert user_call[0][1] == "user"
    assert user_call[0][2] == "msg1\nmsg2"
