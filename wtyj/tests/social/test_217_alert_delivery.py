# test_217_alert_delivery.py
# Brief 217: alert dispatcher fires email/whatsapp on new escalations,
# audit log captures status. Requires `from agents.social.webhook_server
# import app` at module top to trigger dashboard.api import-time
# dispatcher registration with state_registry.

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from agents.social.webhook_server import app  # registers dispatcher

client = TestClient(app)


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _clean_alert_state():
    from shared import state_registry
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM alert_settings")
    conn.execute("DELETE FROM alert_deliveries")
    conn.commit()
    conn.close()


def _set_alert_settings(email=None, whatsapp=None, telegram=None, messenger=None):
    """Helper to seed alert_settings via the state_registry helper."""
    from shared import state_registry
    state_registry.save_alert_settings({
        "email":     email or {"enabled": False, "destination": ""},
        "whatsapp":  whatsapp or {"enabled": False, "destination": ""},
        "telegram":  telegram or {"enabled": False, "destination": ""},
        "messenger": messenger or {"enabled": False, "destination": ""},
    })


def _cleanup_escalation(esc_id, customer_id):
    from shared import state_registry
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM pending_notifications WHERE id = ?", (esc_id,))
    conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?", (customer_id,))
    conn.execute("DELETE FROM alert_deliveries WHERE escalation_id = ?", (esc_id,))
    conn.commit()
    conn.close()


# --- Test 1: GET synthesizes default when no row exists
def test_get_alert_settings_synthesizes_default_when_no_row():
    _clean_alert_state()
    token = _login()
    r = client.get("/dashboard/api/settings/escalation-alerts",
                    headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["channels"]["email"]["enabled"] is True
    assert body["channels"]["whatsapp"]["enabled"] is False
    assert body["channels"]["telegram"]["enabled"] is False
    assert body["channels"]["messenger"]["enabled"] is False


# --- Test 2: PUT persists settings
def test_put_alert_settings_persists():
    _clean_alert_state()
    token = _login()
    payload = {
        "channels": {
            "email":     {"enabled": True,  "destination": "ops@example.com"},
            "whatsapp":  {"enabled": True,  "destination": "+15551234567"},
            "telegram":  {"enabled": False, "destination": ""},
            "messenger": {"enabled": False, "destination": ""},
        }
    }
    r = client.put("/dashboard/api/settings/escalation-alerts",
                    json=payload, headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["channels"]["email"]["destination"] == "ops@example.com"
    assert body["channels"]["whatsapp"]["destination"] == "+15551234567"

    # GET round-trip
    r2 = client.get("/dashboard/api/settings/escalation-alerts",
                     headers=_auth(token))
    assert r2.json()["channels"]["whatsapp"]["destination"] == "+15551234567"


# --- Test 3: create_pending_notification (escalation) fires email alert
@patch("dashboard.api.smtp_send")
def test_create_pending_notification_fires_email_alert(mock_smtp):
    from shared import state_registry
    _clean_alert_state()
    _set_alert_settings(email={"enabled": True, "destination": "ops@example.com"})

    customer_id = "217_email_phone"
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation", channel="whatsapp",
        customer_id=customer_id, customer_name="Calvin Adamus",
        subject="Customer wants to speak to a human", body="full body")

    mock_smtp.assert_called_once()
    args = mock_smtp.call_args.args
    assert args[0] == "ops@example.com"
    assert "New escalation" in args[2]
    assert "Calvin Adamus" in args[2]

    # Audit row
    conn = state_registry._get_conn()
    rows = conn.execute(
        "SELECT channel, status, destination FROM alert_deliveries "
        "WHERE escalation_id = ?", (esc_id,)).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "email"
    assert rows[0][1] == "sent"
    assert rows[0][2] == "ops@example.com"

    _cleanup_escalation(esc_id, customer_id)


# --- Test 4: WhatsApp alert routes to configured destination, NOT business WhatsApp
@patch("dashboard.api.send_whatsapp_message", return_value=True)
def test_create_pending_notification_fires_whatsapp_alert_to_configured_destination(mock_wa):
    from shared import state_registry
    _clean_alert_state()
    private_phone = "+15559999000"
    _set_alert_settings(whatsapp={"enabled": True, "destination": private_phone})

    customer_id = "217_wa_phone_other"  # the customer's WhatsApp, NOT the alert dest
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation", channel="whatsapp",
        customer_id=customer_id, customer_name="Test",
        subject="urgent", body="x")

    mock_wa.assert_called_once()
    sent_to = mock_wa.call_args.args[0]
    assert sent_to == private_phone, \
        f"alert routed to wrong number: expected {private_phone}, got {sent_to}"
    assert sent_to != customer_id, "alert must not go to the customer's own WhatsApp"

    conn = state_registry._get_conn()
    rows = conn.execute(
        "SELECT channel, status FROM alert_deliveries "
        "WHERE escalation_id = ?", (esc_id,)).fetchall()
    conn.close()
    assert any(r[0] == "whatsapp" and r[1] == "sent" for r in rows)

    _cleanup_escalation(esc_id, customer_id)


# --- Test 5: dispatcher failure does NOT block escalation row insert
@patch("dashboard.api.smtp_send", side_effect=RuntimeError("smtp down"))
def test_alert_dispatch_failure_does_not_block_escalation_creation(mock_smtp):
    from shared import state_registry
    _clean_alert_state()
    _set_alert_settings(email={"enabled": True, "destination": "ops@example.com"})

    customer_id = "217_fail_phone"
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation", channel="whatsapp",
        customer_id=customer_id, customer_name="Test",
        subject="x", body="x")

    # Escalation row was still created
    rows = state_registry.get_all_escalations()
    assert any(r["id"] == esc_id for r in rows)

    # Audit row recorded the failure
    conn = state_registry._get_conn()
    fail_rows = conn.execute(
        "SELECT status, error FROM alert_deliveries "
        "WHERE escalation_id = ?", (esc_id,)).fetchall()
    conn.close()
    assert any(r[0] == "failed" and "smtp down" in (r[1] or "") for r in fail_rows)

    _cleanup_escalation(esc_id, customer_id)


# --- Test 6: telegram enabled records skipped (provider not configured)
def test_telegram_enabled_records_skipped_with_provider_not_configured():
    from shared import state_registry
    _clean_alert_state()
    _set_alert_settings(telegram={"enabled": True, "destination": "@calvin"})

    customer_id = "217_tg_phone"
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation", channel="whatsapp",
        customer_id=customer_id, customer_name="Test",
        subject="x", body="x")

    conn = state_registry._get_conn()
    rows = conn.execute(
        "SELECT channel, status, error FROM alert_deliveries "
        "WHERE escalation_id = ?", (esc_id,)).fetchall()
    conn.close()
    tg_rows = [r for r in rows if r[0] == "telegram"]
    assert len(tg_rows) == 1
    assert tg_rows[0][1] == "skipped"
    assert "telegram provider not configured" in (tg_rows[0][2] or "")

    _cleanup_escalation(esc_id, customer_id)


# --- Test 7: messenger enabled records skipped
def test_messenger_enabled_records_skipped():
    from shared import state_registry
    _clean_alert_state()
    _set_alert_settings(messenger={"enabled": True, "destination": "page_id_123"})

    customer_id = "217_msg_phone"
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation", channel="whatsapp",
        customer_id=customer_id, customer_name="Test",
        subject="x", body="x")

    conn = state_registry._get_conn()
    rows = conn.execute(
        "SELECT channel, status, error FROM alert_deliveries "
        "WHERE escalation_id = ?", (esc_id,)).fetchall()
    conn.close()
    ms_rows = [r for r in rows if r[0] == "messenger"]
    assert len(ms_rows) == 1
    assert ms_rows[0][1] == "skipped"
    assert "messenger provider not configured" in (ms_rows[0][2] or "")

    _cleanup_escalation(esc_id, customer_id)


# --- Test 8: email enabled but no destination + no support_email → skipped
@patch("dashboard.api.config_loader")
def test_email_enabled_with_no_destination_records_skipped(mock_config):
    from shared import state_registry
    _clean_alert_state()
    # Force config_loader.get_business() to return no support_email/email
    mock_config.get_business.return_value = {"name": "TestCo"}

    _set_alert_settings(email={"enabled": True, "destination": ""})

    customer_id = "217_no_email_phone"
    esc_id = state_registry.create_pending_notification(
        notification_type="escalation", channel="whatsapp",
        customer_id=customer_id, customer_name="Test",
        subject="x", body="x")

    conn = state_registry._get_conn()
    rows = conn.execute(
        "SELECT channel, status, error FROM alert_deliveries "
        "WHERE escalation_id = ?", (esc_id,)).fetchall()
    conn.close()
    em_rows = [r for r in rows if r[0] == "email"]
    assert len(em_rows) == 1
    assert em_rows[0][1] == "skipped"
    assert "no email destination" in (em_rows[0][2] or "")

    _cleanup_escalation(esc_id, customer_id)


# --- Test 9: relay rows do NOT fire alerts (regression guard from round 1)
@patch("dashboard.api.smtp_send")
@patch("dashboard.api.send_whatsapp_message")
def test_relay_notification_does_NOT_fire_alerts(mock_wa, mock_smtp):
    from shared import state_registry
    _clean_alert_state()
    _set_alert_settings(
        email={"enabled": True, "destination": "ops@example.com"},
        whatsapp={"enabled": True, "destination": "+15551234567"})

    customer_id = "217_relay_phone"
    esc_id = state_registry.create_pending_notification(
        notification_type="relay", channel="whatsapp",  # relay, NOT escalation
        customer_id=customer_id, customer_name="Test",
        subject="Marina asks for input", body="x")

    # Neither sender was called
    mock_smtp.assert_not_called()
    mock_wa.assert_not_called()

    # No alert_deliveries rows for this row id
    conn = state_registry._get_conn()
    rows = conn.execute(
        "SELECT * FROM alert_deliveries WHERE escalation_id = ?",
        (esc_id,)).fetchall()
    conn.close()
    assert len(rows) == 0

    _cleanup_escalation(esc_id, customer_id)
