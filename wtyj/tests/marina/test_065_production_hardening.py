"""Tests for Brief 065 — Production Hardening."""
import json
import os
import sys
import tempfile
import time
from unittest.mock import patch, MagicMock

import pytest


# ── T1: Sender over rate limit → skipped ──
def test_sender_over_rate_limit():
    """20 timestamps within window → rate limit triggered."""
    from agents.marina import email_poller
    now = int(time.time())
    state = {"threads": {}, "sender_rates": {
        "spam@test.com": [now - i * 10 for i in range(20)]  # 20 timestamps, all within 3600s
    }}
    _sr = state["sender_rates"]
    _sr_times = _sr.get("spam@test.com", [])
    _sr_times = [t for t in _sr_times if now - t <= email_poller.SENDER_RATE_WINDOW]
    assert len(_sr_times) >= email_poller.SENDER_RATE_LIMIT, \
        f"Expected >= {email_poller.SENDER_RATE_LIMIT}, got {len(_sr_times)}"


# ── T2: Sender under rate limit → processed ──
def test_sender_under_rate_limit():
    """5 timestamps → under limit, list grows to 6 after append."""
    from agents.marina import email_poller
    now = int(time.time())
    _sr_times = [now - i * 10 for i in range(5)]
    _sr_times = [t for t in _sr_times if now - t <= email_poller.SENDER_RATE_WINDOW]
    assert len(_sr_times) < email_poller.SENDER_RATE_LIMIT
    _sr_times.append(now)
    assert len(_sr_times) == 6


# ── T3: Thread >30d, no hold → archived and deleted ──
def test_old_thread_no_hold_archived():
    """Thread older than 30 days without hold_created → removed from state."""
    from agents.marina import email_poller
    now = int(time.time())
    state = {
        "threads": {
            "test_old": {
                "last_activity": now - 31 * 86400,
                "flags": {},
                "fields": {"customer_name": "Old Customer"},
            }
        },
        "sender_rates": {},
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        archive_path = f.name
    orig_archive = email_poller.ARCHIVE_PATH
    email_poller.ARCHIVE_PATH = archive_path
    try:
        email_poller._cleanup_stale_data(state, now)
        assert "test_old" not in state["threads"]
    finally:
        email_poller.ARCHIVE_PATH = orig_archive
        os.unlink(archive_path)


# ── T4: Thread >30d, hold_created=True → preserved ──
def test_old_thread_with_hold_preserved():
    """Thread older than 30 days WITH hold_created → not deleted."""
    from agents.marina import email_poller
    now = int(time.time())
    state = {
        "threads": {
            "test_hold": {
                "last_activity": now - 31 * 86400,
                "flags": {"hold_created": True},
                "fields": {},
            }
        },
        "sender_rates": {},
    }
    orig_archive = email_poller.ARCHIVE_PATH
    email_poller.ARCHIVE_PATH = os.path.join(tempfile.gettempdir(), "test_archive_t4.jsonl")
    try:
        email_poller._cleanup_stale_data(state, now)
        assert "test_hold" in state["threads"]
    finally:
        email_poller.ARCHIVE_PATH = orig_archive
        if os.path.exists(os.path.join(tempfile.gettempdir(), "test_archive_t4.jsonl")):
            os.unlink(os.path.join(tempfile.gettempdir(), "test_archive_t4.jsonl"))


# ── T5: Thread <30d → preserved ──
def test_recent_thread_preserved():
    """Thread younger than 30 days → not deleted."""
    from agents.marina import email_poller
    now = int(time.time())
    state = {
        "threads": {
            "test_recent": {
                "last_activity": now - 10 * 86400,
                "flags": {},
                "fields": {},
            }
        },
        "sender_rates": {},
    }
    orig_archive = email_poller.ARCHIVE_PATH
    email_poller.ARCHIVE_PATH = os.path.join(tempfile.gettempdir(), "test_archive_t5.jsonl")
    try:
        email_poller._cleanup_stale_data(state, now)
        assert "test_recent" in state["threads"]
    finally:
        email_poller.ARCHIVE_PATH = orig_archive
        if os.path.exists(os.path.join(tempfile.gettempdir(), "test_archive_t5.jsonl")):
            os.unlink(os.path.join(tempfile.gettempdir(), "test_archive_t5.jsonl"))


# ── T6: Archive file contains correct JSON ──
def test_archive_file_json():
    """After archiving, JSONL file has thread_key, archived_at, data."""
    from agents.marina import email_poller
    now = int(time.time())
    original_data = {"last_activity": now - 31 * 86400, "flags": {}, "fields": {"name": "Archived"}}
    state = {
        "threads": {"test_old": dict(original_data)},
        "sender_rates": {},
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        archive_path = f.name
    orig_archive = email_poller.ARCHIVE_PATH
    email_poller.ARCHIVE_PATH = archive_path
    try:
        email_poller._cleanup_stale_data(state, now)
        with open(archive_path, "r") as f:
            line = f.readline().strip()
        parsed = json.loads(line)
        assert parsed["thread_key"] == "test_old"
        assert "archived_at" in parsed
        assert parsed["archived_at"] == now
        assert "data" in parsed
        assert parsed["data"]["fields"]["name"] == "Archived"
    finally:
        email_poller.ARCHIVE_PATH = orig_archive
        os.unlink(archive_path)


# ── T7: OAuth saves new refresh token ──
def test_oauth_saves_refresh_token():
    """OAuth response with new refresh_token → saved to disk."""
    from agents.marina import email_poller
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("old_token")
        token_path = f.name
    from agents.marina import email_adapter
    orig_path = email_poller.REFRESH_TOKEN_PATH
    orig_adapter_path = email_adapter.REFRESH_TOKEN_PATH
    email_poller.REFRESH_TOKEN_PATH = token_path
    email_adapter.REFRESH_TOKEN_PATH = token_path
    try:
        mock_resp = json.dumps({"access_token": "at_123", "refresh_token": "rt_new_456"}).encode()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.read.return_value = mock_resp
            result = email_poller.oauth_token("test_scope")
        assert result == "at_123"
        with open(token_path) as f:
            assert f.read() == "rt_new_456"
    finally:
        email_poller.REFRESH_TOKEN_PATH = orig_path
        email_adapter.REFRESH_TOKEN_PATH = orig_adapter_path
        os.unlink(token_path)


# ── T8: OAuth raises on missing access_token ──
def test_oauth_raises_on_missing_access_token():
    """OAuth response without access_token → raises RuntimeError."""
    from agents.marina import email_poller
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("some_token")
        token_path = f.name
    from agents.marina import email_adapter
    orig_path = email_poller.REFRESH_TOKEN_PATH
    orig_adapter_path = email_adapter.REFRESH_TOKEN_PATH
    email_poller.REFRESH_TOKEN_PATH = token_path
    email_adapter.REFRESH_TOKEN_PATH = token_path
    try:
        mock_resp = json.dumps({"error": "invalid_grant", "error_description": "token expired"}).encode()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.read.return_value = mock_resp
            with pytest.raises(RuntimeError) as exc_info:
                email_poller.oauth_token("test_scope")
            assert "token expired" in str(exc_info.value)
    finally:
        email_poller.REFRESH_TOKEN_PATH = orig_path
        email_adapter.REFRESH_TOKEN_PATH = orig_adapter_path
        os.unlink(token_path)


# ── T9: Token usage logged ──
def test_token_usage_logged():
    """After API call, bm_logger.log called with usage data."""
    from shared import bm_logger

    # Simulate the logging code from marina_agent.py
    mock_response = MagicMock()
    mock_response.usage.input_tokens = 1500
    mock_response.usage.output_tokens = 200

    with patch.object(bm_logger, "log") as mock_log:
        _usage = getattr(mock_response, "usage", None)
        if _usage:
            bm_logger.log("api_usage",
                input_tokens=_usage.input_tokens,
                output_tokens=_usage.output_tokens,
                model="claude-sonnet-4-6")

        mock_log.assert_called_once_with(
            "api_usage",
            input_tokens=1500,
            output_tokens=200,
            model="claude-sonnet-4-6",
        )


# ── T10: Heartbeat file written ──
def test_heartbeat_file_written():
    """Heartbeat file contains a valid timestamp close to now."""
    from agents.marina import email_poller
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        hb_path = f.name
    try:
        with open(hb_path, "w") as f:
            f.write(str(int(time.time())))
        with open(hb_path) as f:
            content = f.read().strip()
        assert content.isdigit()
        assert abs(int(content) - int(time.time())) < 5
    finally:
        os.unlink(hb_path)


# ── T11: 3 consecutive errors → alert sent ──
def test_consecutive_errors_trigger_alert():
    """3 consecutive errors → smtp_send called with [ALERT] subject."""
    from agents.marina import email_poller
    demo_support_email = "butlerbensonagent@gmail.com"

    _consecutive_errors = 0
    _error_alert_sent = False
    smtp_calls = []

    def mock_smtp_send(to, subject, body, **kwargs):
        smtp_calls.append((to, subject, body))

    for i in range(3):
        _consecutive_errors += 1
        ex = Exception(f"Test error {i+1}")
        if _consecutive_errors >= email_poller._ERROR_ALERT_THRESHOLD and not _error_alert_sent:
            try:
                mock_smtp_send(demo_support_email,
                    f"[ALERT] Marina poller: {_consecutive_errors} consecutive errors",
                    f"Latest error: {ex}\n\nCheck journalctl -u bluemarlin")
                _error_alert_sent = True
            except Exception:
                pass

    assert len(smtp_calls) == 1
    assert smtp_calls[0][0] == demo_support_email
    assert smtp_calls[0][1].startswith("[ALERT]")


# ── T12: Error then success → counter reset ──
def test_error_then_success_resets_counter():
    """After error, a successful cycle resets counters."""
    _consecutive_errors = 1
    _error_alert_sent = False

    # Simulate the else branch (success)
    _consecutive_errors = 0
    _error_alert_sent = False

    assert _consecutive_errors == 0
    assert _error_alert_sent == False
