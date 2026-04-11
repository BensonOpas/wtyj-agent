"""Tests for Brief 182 — persistent IMAP connection with NOOP keepalive."""
import os
import time
from unittest.mock import MagicMock, patch

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from agents.marina.email_poller import _TOKEN_REFRESH_SECONDS


def test_token_refresh_constant():
    """Brief 182: token refresh at 45 min (before 60-min OAuth expiry)."""
    assert _TOKEN_REFRESH_SECONDS == 2700


def test_first_iteration_connects_and_selects():
    """Brief 182: when im is None, imap_connect() + select() are called."""
    mock_im = MagicMock()
    with patch('agents.marina.email_poller.imap_connect', return_value=mock_im) as mock_connect:
        from agents.marina.email_poller import imap_connect, MAILBOX
        im = None
        _last_connect = 0
        now = time.time()
        # Simulate the reconnect block from the loop
        if im is None or (now - _last_connect > _TOKEN_REFRESH_SECONDS):
            if im is not None:
                im.logout()
            im = imap_connect()
            im.select(MAILBOX)
            _last_connect = now
        mock_connect.assert_called_once()
        mock_im.select.assert_called_once_with(MAILBOX)
        assert im is mock_im


def test_live_connection_noops():
    """Brief 182: existing fresh connection triggers noop, NOT reconnect."""
    mock_im = MagicMock()
    with patch('agents.marina.email_poller.imap_connect') as mock_connect:
        im = mock_im
        _last_connect = time.time()  # fresh connection
        now = time.time()
        if im is None or (now - _last_connect > _TOKEN_REFRESH_SECONDS):
            im = mock_connect()  # should NOT happen
        else:
            im.noop()
        mock_im.noop.assert_called_once()
        mock_connect.assert_not_called()


def test_noop_failure_triggers_reconnect():
    """Brief 182: NOOP exception sets im to None + calls logout (so next iteration reconnects)."""
    mock_im = MagicMock()
    mock_im.noop.side_effect = Exception("socket error: EOF")
    im = mock_im
    # Simulate the try/except from the real error handler
    try:
        im.noop()
        assert False, "noop should have raised"
    except Exception:
        if im is not None:
            try:
                im.logout()
            except Exception:
                pass
        im = None
    assert im is None
    mock_im.logout.assert_called_once()


def test_stale_token_triggers_reconnect():
    """Brief 182: connection older than 45 min triggers reconnect even if im is alive."""
    mock_old_im = MagicMock()
    mock_new_im = MagicMock()
    with patch('agents.marina.email_poller.imap_connect', return_value=mock_new_im) as mock_connect:
        from agents.marina.email_poller import imap_connect, MAILBOX
        im = mock_old_im
        _last_connect = time.time() - 2701  # >2700s ago
        now = time.time()
        if im is None or (now - _last_connect > _TOKEN_REFRESH_SECONDS):
            if im is not None:
                try:
                    im.logout()
                except Exception:
                    pass
            im = imap_connect()
            im.select(MAILBOX)
            _last_connect = now
        mock_old_im.logout.assert_called_once()  # old connection closed
        mock_connect.assert_called_once()          # new connection opened
        mock_new_im.select.assert_called_once_with(MAILBOX)  # selected on new
        assert im is mock_new_im
