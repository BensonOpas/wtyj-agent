# bluemarlin/tests/social/conftest.py
# Created: Brief 067
# Last modified: Brief 071
# Purpose: Shared test config for social agent tests
import sys
import os
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Set WhatsApp env vars before any module imports — whatsapp_client.py reads these
# at import time. Without this, test_067 importing webhook_server triggers
# whatsapp_client init with empty values, breaking test_068's send assertions.
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test_token_067")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test_access_token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "990622044139349")

# Brief 217: alerts default to "email enabled with support_email destination"
# in production. Tests that pre-existed Brief 217 don't expect smtp_send to
# fire when they seed an escalation row — they mock smtp_send only for their
# own /reply call. Pre-disable alerts before each test so legacy tests pass;
# test_217 explicitly enables what it needs per-test.
import pytest


@pytest.fixture(autouse=True, scope="function")
def _disable_alert_dispatch_default():
    """Reset alert_settings to all-disabled before each test in this dir."""
    try:
        from shared import state_registry as _sr
        _sr.save_alert_settings({
            "email":     {"enabled": False, "destination": ""},
            "whatsapp":  {"enabled": False, "destination": ""},
            "telegram":  {"enabled": False, "destination": ""},
            "messenger": {"enabled": False, "destination": ""},
        })
    except Exception:
        pass
    yield
