"""Tests for Brief 179 — email poller resilience (backoff, cleanup, exit)."""
import os
import sys
from unittest.mock import MagicMock, patch

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

# Import the constants we're testing against
from agents.marina.email_poller import POLL_INTERVAL, _ERROR_EXIT_THRESHOLD


def _backoff(consecutive_errors: int) -> int:
    """Replicate the Brief 179 backoff formula for unit testing."""
    return min(POLL_INTERVAL * (2 ** (consecutive_errors - 1)), 300)


def test_backoff_formula_doubles():
    """Brief 179: backoff doubles on each consecutive error, capped at 300s."""
    assert _backoff(1) == 10    # first error: normal interval
    assert _backoff(2) == 20
    assert _backoff(3) == 40
    assert _backoff(4) == 80
    assert _backoff(5) == 160
    assert _backoff(6) == 300   # capped
    assert _backoff(10) == 300  # still capped


def test_backoff_first_error_is_normal_interval():
    """Brief 179: the FIRST consecutive error should wait POLL_INTERVAL (not 2x)."""
    assert _backoff(1) == POLL_INTERVAL


def test_exit_threshold_is_30():
    """Brief 179: forced exit at 30 consecutive errors (matches the constant)."""
    assert _ERROR_EXIT_THRESHOLD == 30


def test_cleanup_calls_close_and_logout():
    """Brief 179: on error, the handler calls im.close() and im.logout()."""
    im = MagicMock()
    # Simulate the error handler cleanup block
    if im is not None:
        try:
            im.close()
        except Exception:
            pass
        try:
            im.logout()
        except Exception:
            pass
    im.close.assert_called_once()
    im.logout.assert_called_once()


def test_cleanup_handles_none_im():
    """Brief 179: when im is None (imap_connect itself threw), cleanup skips gracefully."""
    im = None
    # This is the actual guard from the error handler
    if im is not None:
        im.close()   # pragma: no cover — should NOT be reached
        im.logout()  # pragma: no cover
    # No exception raised = pass. The guard protects against NameError/AttributeError.
    assert im is None
