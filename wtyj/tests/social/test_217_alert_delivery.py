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


def _wipe_escalations_for(customer_id: str):
    """Brief 239 + 240: wipe stale rows for this customer_id before a test
    runs. Tests share the dev DB; without this, a prior run's row triggers
    Brief 239's dedup-update path and the test's expected create-from-scratch
    flow doesn't fire."""
    from shared import state_registry
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM alert_deliveries WHERE escalation_id IN "
                 "(SELECT id FROM pending_notifications WHERE customer_id = ?)",
                 (customer_id,))
    conn.execute("DELETE FROM pending_notifications WHERE customer_id = ?",
                 (customer_id,))
    conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?",
                 (customer_id,))
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


# --- Test 4 (Brief 217 obsolete, removed in Brief 240): asserted that
# `send_whatsapp_message` (Meta Cloud API) was called for operator WA
# alerts. Brief 240 replaced that contract: operator WA alerts now go via
# Zernio's send_dm_reply, not Meta. Three new tests at the bottom of this
# file (test_wa_alert_unresolved_route_records_skipped_no_zernio_call,
# test_wa_alert_resolved_route_calls_zernio_records_sent,
# test_wa_alert_zernio_failure_records_failed_with_reason) cover the
# new contract end-to-end.


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


# ── Brief 239: rich alert body, suppression, Friday-12:00 case ─────────

def _make_summary(reason="Calvin wants to schedule a meeting.",
                   wants="Schedule a meeting.",
                   decide="Choose a time.",
                   options=None,
                   intent="scheduling",
                   proposed=None,
                   prev_proposed=None,
                   latest_msg=""):
    s = {
        "reason": reason,
        "customerWants": wants,
        "operatorNeedsToDecide": decide,
        "recommendedOptions": options or ["Confirm Friday 12:00",
                                            "Suggest another time",
                                            "Switch to human takeover"],
        "extractedDetails": {
            "intent": intent,
            "proposedTimes": proposed or ["Friday 12:00"],
            "topic": "scheduling",
        },
    }
    if prev_proposed is not None:
        s["extractedDetails"]["previousProposedTimes"] = prev_proposed
    if latest_msg:
        s["latestCustomerMessage"] = latest_msg
    return s


def test_alert_body_uses_rich_summary_when_available(monkeypatch):
    """Brief 239: when summary_dict is supplied, body includes reason,
    decision, options, and the latest customer message verbatim."""
    from dashboard import api as dapi
    captured = {}
    def fake_smtp(to, subj, body, **kw): captured.update(to=to, subj=subj, body=body)
    monkeypatch.setattr(dapi, "smtp_send", fake_smtp)
    monkeypatch.setattr(dapi.state_registry, "get_alert_settings",
                         lambda **k: {"channels": {"email": {"enabled": True,
                                                              "destination": "ops@example.com"}}})
    monkeypatch.setattr(dapi.state_registry, "record_alert_delivery",
                         lambda *a, **k: None)
    summary = _make_summary(latest_msg="i changed my mind, i wanna change it to friday 12:00")
    dapi._fire_escalation_alerts(
        escalation_id=1, customer_name="Calvin", channel="whatsapp",
        summary="ignored", mode="soft", summary_dict=summary, is_update=False)
    assert "Reason:" in captured["body"]
    assert "Calvin wants to schedule" in captured["body"]
    assert "i changed my mind" in captured["body"]
    assert "Mode: Agent needs help" in captured["body"]
    assert "- Confirm Friday 12:00" in captured["body"]


def test_alert_body_falls_back_to_vague_when_no_summary(monkeypatch):
    """Brief 239: when summary_dict is None (Claude failed), body uses the
    legacy Brief 217 format so old tests + no-API-key paths still work."""
    from dashboard import api as dapi
    captured = {}
    def fake_smtp(to, subj, body, **kw): captured.update(to=to, subj=subj, body=body)
    monkeypatch.setattr(dapi, "smtp_send", fake_smtp)
    monkeypatch.setattr(dapi.state_registry, "get_alert_settings",
                         lambda **k: {"channels": {"email": {"enabled": True,
                                                              "destination": "ops@example.com"}}})
    monkeypatch.setattr(dapi.state_registry, "record_alert_delivery",
                         lambda *a, **k: None)
    dapi._fire_escalation_alerts(
        escalation_id=1, customer_name="Calvin", channel="whatsapp",
        summary="Marina escalated a whatsapp conversation",
        mode=None, summary_dict=None, is_update=False)
    assert "Marina escalated a whatsapp conversation" in captured["body"]
    assert captured["subj"] == "New escalation: Calvin"


def test_alert_subject_specific_for_scheduling_update(monkeypatch):
    """Brief 239: when intent=scheduling AND is_update AND proposedTimes
    non-empty, subject names the new time."""
    from dashboard import api as dapi
    captured = {}
    def fake_smtp(to, subj, body, **kw): captured.update(subj=subj)
    monkeypatch.setattr(dapi, "smtp_send", fake_smtp)
    monkeypatch.setattr(dapi.state_registry, "get_alert_settings",
                         lambda **k: {"channels": {"email": {"enabled": True,
                                                              "destination": "ops@example.com"}}})
    monkeypatch.setattr(dapi.state_registry, "record_alert_delivery",
                         lambda *a, **k: None)
    summary = _make_summary(proposed=["Friday 12:00"])
    dapi._fire_escalation_alerts(
        escalation_id=1, customer_name="Calvin", channel="whatsapp",
        summary="ignored", mode="soft", summary_dict=summary, is_update=True)
    assert captured["subj"] == "Updated escalation: Calvin changed meeting time to Friday 12:00"


def test_alert_body_surfaces_previous_proposed_times(monkeypatch):
    """Brief 239: when previousProposedTimes is non-empty, body includes a
    'Previously proposed (now retracted): ...' line. Verifies the schema
    field added in Step 1 is consumed by the body builder in Step 4."""
    from dashboard import api as dapi
    captured = {}
    def fake_smtp(to, subj, body, **kw): captured.update(body=body)
    monkeypatch.setattr(dapi, "smtp_send", fake_smtp)
    monkeypatch.setattr(dapi.state_registry, "get_alert_settings",
                         lambda **k: {"channels": {"email": {"enabled": True,
                                                              "destination": "ops@example.com"}}})
    monkeypatch.setattr(dapi.state_registry, "record_alert_delivery",
                         lambda *a, **k: None)
    summary = _make_summary(
        proposed=["Friday 12:00"],
        prev_proposed=["tomorrow evening 17:00", "Monday morning 11:00"],
        latest_msg="i changed my mind, i wanna change it to friday 12:00")
    dapi._fire_escalation_alerts(
        escalation_id=1, customer_name="Calvin", channel="whatsapp",
        summary="ignored", mode="soft", summary_dict=summary, is_update=True)
    assert ("Previously proposed (now retracted): "
            "tomorrow evening 17:00, Monday morning 11:00") in captured["body"]


def test_re_escalation_with_changed_summary_fires_updated_alert(monkeypatch):
    """Brief 239: real round-trip — call create_pending_notification twice
    for the same customer; second call has a materially-different summary;
    second alert fires with is_update=True and the new proposedTimes."""
    from shared import state_registry
    summaries = iter([
        _make_summary(proposed=["Thursday 17:00", "Monday 11:00"],
                       latest_msg="i can do thu 17 or mon 11"),
        _make_summary(proposed=["Friday 12:00"],
                       prev_proposed=["Thursday 17:00", "Monday 11:00"],
                       latest_msg="i changed my mind, i wanna change it to friday 12:00"),
    ])
    monkeypatch.setattr(state_registry, "_summary_dispatcher",
                         lambda *a, **k: next(summaries))
    fired = []
    def fake_dispatch(eid, name, ch, subj, mode=None, summary_dict=None, is_update=False):
        fired.append({"is_update": is_update,
                       "subject": subj,
                       "summary": summary_dict})
    monkeypatch.setattr(state_registry, "_alert_dispatcher", fake_dispatch)
    cid = "test-friday-conv"
    _wipe_escalations_for(cid)
    state_registry.create_pending_notification(
        "escalation", "whatsapp", cid, "Calvin", "Marina escalated", "...",
        mode="soft")
    state_registry.create_pending_notification(
        "escalation", "whatsapp", cid, "Calvin", "Marina escalated", "...",
        mode="soft")
    assert len(fired) == 2
    assert fired[0]["is_update"] is False
    assert fired[1]["is_update"] is True
    assert (fired[1]["summary"]["extractedDetails"]["proposedTimes"]
            == ["Friday 12:00"])
    assert (fired[1]["summary"]["extractedDetails"]["previousProposedTimes"]
            == ["Thursday 17:00", "Monday 11:00"])


def test_re_escalation_with_unchanged_summary_suppresses_alert(monkeypatch):
    """Brief 239: when the regenerated summary is materially identical to
    the previous one, no follow-up alert fires — only the first one."""
    from shared import state_registry
    same = _make_summary(proposed=["Friday 12:00"],
                          latest_msg="i wanna change it to friday 12:00")
    monkeypatch.setattr(state_registry, "_summary_dispatcher",
                         lambda *a, **k: dict(same))
    fired = []
    monkeypatch.setattr(state_registry, "_alert_dispatcher",
                         lambda *a, **k: fired.append((a, k)))
    cid = "test-noop-conv"
    _wipe_escalations_for(cid)
    state_registry.create_pending_notification(
        "escalation", "whatsapp", cid, "Calvin", "subj1", "body1",
        mode="soft")
    state_registry.create_pending_notification(
        "escalation", "whatsapp", cid, "Calvin", "subj2", "body2",
        mode="soft")
    assert len(fired) == 1


def test_mode_set_at_create_persists_and_renders(monkeypatch):
    """Brief 239: passing mode='soft' to create_pending_notification puts
    mode='soft' on the row; the alert dispatcher receives mode='soft';
    the rich body says 'Mode: Agent needs help' (not '(unset)')."""
    from shared import state_registry
    from dashboard import api as dapi
    monkeypatch.setattr(state_registry, "_summary_dispatcher",
                         lambda *a, **k: _make_summary(latest_msg="hi"))
    captured = {}
    def fake_smtp(to, subj, body, **kw): captured.update(body=body)
    monkeypatch.setattr(dapi, "smtp_send", fake_smtp)
    monkeypatch.setattr(dapi.state_registry, "get_alert_settings",
                         lambda **k: {"channels": {"email": {"enabled": True,
                                                              "destination": "ops@example.com"}}})
    monkeypatch.setattr(dapi.state_registry, "record_alert_delivery",
                         lambda *a, **k: None)
    cid = "test-mode-conv"
    _wipe_escalations_for(cid)
    rid = state_registry.create_pending_notification(
        "escalation", "whatsapp", cid, "Calvin", "subj", "body", mode="soft")
    conn = state_registry._get_conn()
    row = conn.execute("SELECT mode FROM pending_notifications WHERE id=?",
                        (rid,)).fetchone()
    conn.close()
    assert row[0] == "soft"
    assert "Mode: Agent needs help" in captured.get("body", "")


# ── Brief 240: operator WhatsApp alerts via Zernio + bootstrap ─────────

def test_wa_alert_unresolved_route_records_skipped_no_zernio_call(monkeypatch):
    """Brief 240: WA enabled + destination configured + Zernio route NOT yet
    resolved → alert dispatcher records 'skipped' with the bootstrap reason
    and does NOT call send_dm_reply or any Meta send function."""
    from dashboard import api as dapi
    from shared import state_registry
    monkeypatch.setattr(state_registry, "get_alert_settings",
                         lambda **k: {"channels": {
                             "email": {"enabled": False, "destination": "", "alternativeDestination": ""},
                             "whatsapp": {"enabled": True, "destination": "+351963618003", "zernioResolved": False},
                         }})
    monkeypatch.setattr(state_registry, "get_resolved_operator_whatsapp_route",
                         lambda: None)
    captured = []
    monkeypatch.setattr(state_registry, "record_alert_delivery",
                         lambda *a, **k: captured.append(a))
    called = {"send_dm_reply": False, "send_whatsapp_message": False}
    monkeypatch.setattr("agents.social.zernio_dm_client.send_dm_reply",
                         lambda *a, **k: called.__setitem__("send_dm_reply", True) or True)
    monkeypatch.setattr(dapi, "send_whatsapp_message",
                         lambda *a, **k: called.__setitem__("send_whatsapp_message", True) or True)
    dapi._fire_escalation_alerts(
        escalation_id=1, customer_name="Calvin", channel="whatsapp",
        summary="ignored", mode="soft",
        summary_dict={"reason": "x", "extractedDetails": {"intent": "scheduling"}},
        is_update=False)
    wa_rows = [a for a in captured if len(a) >= 4 and a[1] == "whatsapp"]
    assert len(wa_rows) == 1
    eid, ch, dest, status = wa_rows[0][:4]
    assert status == "skipped"
    assert dest == "+351963618003"
    reason = wa_rows[0][4] if len(wa_rows[0]) > 4 else ""
    assert "zernio_operator_destination_not_resolved" in reason
    assert called["send_dm_reply"] is False
    assert called["send_whatsapp_message"] is False


def test_wa_alert_resolved_route_calls_zernio_records_sent(monkeypatch):
    """Brief 240: WA enabled + Zernio route resolved → alert dispatcher
    calls send_dm_reply with the route's conv_id + account_id and records
    'sent' on True. Also verifies the Brief 239 rich body is what gets sent."""
    from dashboard import api as dapi
    from shared import state_registry
    from agents.social import zernio_dm_client
    monkeypatch.setattr(state_registry, "get_alert_settings",
                         lambda **k: {"channels": {
                             "email": {"enabled": False, "destination": "", "alternativeDestination": ""},
                             "whatsapp": {"enabled": True, "destination": "+351963618003", "zernioResolved": True},
                         }})
    monkeypatch.setattr(state_registry, "get_resolved_operator_whatsapp_route",
                         lambda: {"conversation_id": "convOPER123",
                                   "account_id": "acctZER999",
                                   "resolved_at": "2026-05-10T04:00:00+00:00"})
    captured_send = {}
    def fake_send(conv, acct, text):
        captured_send.update(conv=conv, acct=acct, text=text)
        return True
    monkeypatch.setattr(zernio_dm_client, "send_dm_reply", fake_send)
    captured_delivery = []
    monkeypatch.setattr(state_registry, "record_alert_delivery",
                         lambda *a, **k: captured_delivery.append(a))
    dapi._fire_escalation_alerts(
        escalation_id=2, customer_name="Calvin", channel="whatsapp",
        summary="ignored", mode="soft",
        summary_dict={"reason": "Calvin needs scheduling decision",
                       "operatorNeedsToDecide": "Choose a time",
                       "recommendedOptions": ["Confirm Friday 12:00"],
                       "extractedDetails": {"intent": "scheduling",
                                              "proposedTimes": ["Friday 12:00"]},
                       "latestCustomerMessage": "i wanna change to friday 12:00"},
        is_update=False)
    assert captured_send["conv"] == "convOPER123"
    assert captured_send["acct"] == "acctZER999"
    assert "Reason:" in captured_send["text"]
    wa_rows = [a for a in captured_delivery if len(a) >= 4 and a[1] == "whatsapp"]
    assert len(wa_rows) == 1
    assert wa_rows[0][3] == "sent"
    assert wa_rows[0][2] == "+351963618003"


def test_wa_alert_zernio_failure_records_failed_with_reason(monkeypatch):
    """Brief 240: Zernio's send_dm_reply returns False → alert dispatcher
    records 'failed' with reason 'zernio_send_dm_reply_returned_false'."""
    from dashboard import api as dapi
    from shared import state_registry
    from agents.social import zernio_dm_client
    monkeypatch.setattr(state_registry, "get_alert_settings",
                         lambda **k: {"channels": {
                             "email": {"enabled": False, "destination": "", "alternativeDestination": ""},
                             "whatsapp": {"enabled": True, "destination": "+351963618003", "zernioResolved": True},
                         }})
    monkeypatch.setattr(state_registry, "get_resolved_operator_whatsapp_route",
                         lambda: {"conversation_id": "convX",
                                   "account_id": "acctY",
                                   "resolved_at": "2026-05-10T04:00:00+00:00"})
    monkeypatch.setattr(zernio_dm_client, "send_dm_reply",
                         lambda *a, **k: False)
    captured = []
    monkeypatch.setattr(state_registry, "record_alert_delivery",
                         lambda *a, **k: captured.append(a))
    dapi._fire_escalation_alerts(
        escalation_id=3, customer_name="Calvin", channel="whatsapp",
        summary="ignored", mode="soft",
        summary_dict={"reason": "x", "extractedDetails": {"intent": "scheduling"}},
        is_update=False)
    wa_rows = [a for a in captured if len(a) >= 4 and a[1] == "whatsapp"]
    assert len(wa_rows) == 1
    eid, ch, dest, status = wa_rows[0][:4]
    assert status == "failed"
    reason = wa_rows[0][4] if len(wa_rows[0]) > 4 else ""
    assert "zernio_send_dm_reply_returned_false" in reason


def test_inbound_wa_from_operator_phone_resolves_zernio_route(monkeypatch):
    """Brief 240: an inbound Zernio WhatsApp webhook whose normalized
    sender_id matches the configured whatsapp_destination triggers
    set_resolved_operator_whatsapp_route with the conv_id + account_id from
    the parsed message. The WhatsApp-only gating in the source is enforced
    by the `if msg.get(\"platform\") == \"whatsapp\":` guard at the call
    site; this test exercises only the positive WhatsApp path."""
    from agents.social import webhook_server
    from shared import state_registry
    payload = {"event": "message.received", "data": {
        "id": "msgB240a", "conversationId": "convOPER123",
        "accountId": "acctZER999", "platform": "whatsapp",
        "text": "hi", "sender": {"name": "Calvin", "id": "+351963618003"}}}
    parsed = {"conversation_id": "convOPER123", "platform": "whatsapp",
              "channel": "whatsapp", "sender_name": "Calvin",
              "sender_id": "+351963618003", "text": "hi",
              "message_id": "msgB240a", "account_id": "acctZER999"}
    monkeypatch.setattr(webhook_server, "parse_zernio_webhook",
                         lambda p: parsed)
    monkeypatch.setattr(webhook_server.state_registry, "wa_has_been_processed",
                         lambda mid: False)
    monkeypatch.setattr(webhook_server.state_registry,
                         "wa_mark_as_processed", lambda mid: None)
    monkeypatch.setattr(webhook_server.state_registry, "get_blocked",
                         lambda cid: False)
    monkeypatch.setattr(state_registry, "get_alert_settings",
                         lambda **k: {"channels": {
                             "whatsapp": {"enabled": True, "destination": "+351963618003"},
                         }})
    monkeypatch.setattr("shared.tenant_guard.config_loader.get_raw",
                         lambda: {})
    captured = {}
    def fake_set_route(conv, acct):
        captured.update(conv=conv, acct=acct)
    monkeypatch.setattr(state_registry,
                         "set_resolved_operator_whatsapp_route", fake_set_route)
    monkeypatch.setattr(webhook_server, "_buffer_message", lambda m: None)
    monkeypatch.setattr(webhook_server, "send_typing_indicator",
                         lambda *a, **k: None)
    webhook_server._process_zernio_event(payload)
    assert captured.get("conv") == "convOPER123"
    assert captured.get("acct") == "acctZER999"


# ── Brief 241: appointment alerts using shared destinations ─────────────

def _wipe_appointments_for(conversation_id: str):
    """Brief 241: wipe appointment row + its alert_deliveries audit rows
    before a test runs. Tests share the dev DB."""
    from shared import state_registry
    conn = state_registry._get_conn()
    rows = conn.execute(
        "SELECT id FROM appointments WHERE conversation_id = ?",
        (conversation_id,)).fetchall()
    for r in rows:
        conn.execute("DELETE FROM alert_deliveries WHERE appointment_id = ?",
                     (r[0],))
        conn.execute("DELETE FROM appointments WHERE id = ?", (r[0],))
    conn.commit()
    conn.close()


def test_appointment_upsert_does_not_fire_dispatcher_for_pending(monkeypatch):
    """Brief 241: status='pending_team_confirmation' on insert does NOT
    fire the appointment alert dispatcher (acceptance #2/#3)."""
    from shared import state_registry
    conv = "test-241-pending"
    _wipe_appointments_for(conv)
    fired = []
    monkeypatch.setattr(state_registry, "_appointment_alert_dispatcher",
                         lambda *a, **k: fired.append(a))
    state_registry.appointment_upsert(
        conv, "whatsapp", "Calvin", "Intake call",
        ["Friday 12:00"], status="pending_team_confirmation")
    assert fired == []


def test_appointment_upsert_fires_dispatcher_on_insert_confirmed(monkeypatch):
    """Brief 241: status='confirmed' on FRESH insert fires the dispatcher
    (acceptance #6)."""
    from shared import state_registry
    conv = "test-241-insert-confirmed"
    _wipe_appointments_for(conv)
    fired = []
    monkeypatch.setattr(state_registry, "_appointment_alert_dispatcher",
                         lambda *a, **k: fired.append(a))
    rid = state_registry.appointment_upsert(
        conv, "whatsapp", "Calvin", "Intake call",
        ["Friday 12:00"], location="Café Paris", status="confirmed")
    assert len(fired) == 1
    assert fired[0][0] == rid
    assert fired[0][1] == "Calvin"
    assert fired[0][2] == "whatsapp"
    appt = fired[0][3]
    assert appt["status"] == "confirmed"
    assert appt["title"] == "Intake call"


def test_appointment_upsert_fires_dispatcher_on_transition_to_confirmed(monkeypatch):
    """Brief 241: pending_team_confirmation → confirmed fires dispatcher
    (acceptance #6 via update path)."""
    from shared import state_registry
    conv = "test-241-transition"
    _wipe_appointments_for(conv)
    state_registry.appointment_upsert(
        conv, "whatsapp", "Calvin", "Intake call",
        ["Friday 12:00"], status="pending_team_confirmation")
    fired = []
    monkeypatch.setattr(state_registry, "_appointment_alert_dispatcher",
                         lambda *a, **k: fired.append(a))
    state_registry.appointment_upsert(
        conv, "whatsapp", "Calvin", "Intake call",
        ["Friday 12:00"], location="Café Paris", status="confirmed")
    assert len(fired) == 1


def test_appointment_upsert_does_not_refire_on_resave_confirmed(monkeypatch):
    """Brief 241: confirmed → confirmed re-save does NOT fire dispatcher
    again (acceptance #11 layer-1 dedup via transition detection)."""
    from shared import state_registry
    conv = "test-241-resave"
    _wipe_appointments_for(conv)
    state_registry.appointment_upsert(
        conv, "whatsapp", "Calvin", "Intake call",
        ["Friday 12:00"], status="confirmed")
    fired = []
    monkeypatch.setattr(state_registry, "_appointment_alert_dispatcher",
                         lambda *a, **k: fired.append(a))
    state_registry.appointment_upsert(
        conv, "whatsapp", "Calvin", "Intake call",
        ["Friday 12:00"], status="confirmed")
    assert fired == []


def test_fire_appointment_alerts_sends_email_with_correct_shape(monkeypatch):
    """Brief 241: dispatcher writes correct subject + body via email,
    records alert_type='appointment', appointment_id=<id> in
    alert_deliveries (acceptance #6, #7, #12)."""
    from dashboard import api as dapi
    from shared import state_registry
    captured_email = {}
    def fake_smtp(to, subj, body, **kw):
        captured_email.update(to=to, subj=subj, body=body)
    monkeypatch.setattr(dapi, "smtp_send", fake_smtp)
    monkeypatch.setattr(state_registry, "get_alert_settings",
                         lambda **k: {
                             "alertTypes": {"escalations": True, "appointments": True},
                             "channels": {"email": {"enabled": True,
                                                     "destination": "ops@example.com",
                                                     "alternativeDestination": ""}}})
    monkeypatch.setattr(state_registry, "appointment_alert_already_sent",
                         lambda *a, **k: False)
    captured_delivery = []
    monkeypatch.setattr(state_registry, "record_alert_delivery",
                         lambda *a, **k: captured_delivery.append((a, k)))
    appt = {"id": 99, "conversation_id": "conv-x", "channel": "whatsapp",
            "customer_name": "Calvin", "title": "Intake call",
            "date_time_label": "Friday 12:00",
            "proposed_times": ["Friday 12:00"],
            "location": "Café Paris", "status": "confirmed"}
    dapi._fire_appointment_alerts(99, "Calvin", "whatsapp", appt)
    assert captured_email["subj"] == "Appointment confirmed: Calvin — Friday 12:00"
    assert "Appointment confirmed" in captured_email["body"]
    assert "Topic: Intake call" in captured_email["body"]
    assert "Time: Friday 12:00" in captured_email["body"]
    assert "Location: Café Paris" in captured_email["body"]
    em_rows = [(a, k) for (a, k) in captured_delivery if a[1] == "email"]
    assert len(em_rows) == 1
    args, kwargs = em_rows[0]
    assert kwargs.get("alert_type") == "appointment"
    assert kwargs.get("appointment_id") == 99
    assert args[0] is None  # escalation_id=None for appointment rows


def test_fire_appointment_alerts_dedup_skips_already_sent(monkeypatch):
    """Brief 241: layer-2 dedup — if appointment_alert_already_sent
    returns True for a destination, the dispatcher does NOT call
    smtp_send for it AND records no new alert_deliveries row
    (acceptance #11)."""
    from dashboard import api as dapi
    from shared import state_registry
    smtp_calls = []
    monkeypatch.setattr(dapi, "smtp_send",
                         lambda to, s, b, **kw: smtp_calls.append(to))
    monkeypatch.setattr(state_registry, "get_alert_settings",
                         lambda **k: {
                             "alertTypes": {"escalations": True, "appointments": True},
                             "channels": {"email": {"enabled": True,
                                                     "destination": "ops@example.com",
                                                     "alternativeDestination": ""}}})
    monkeypatch.setattr(state_registry, "appointment_alert_already_sent",
                         lambda aid, ch, dest: True)
    record_calls = []
    monkeypatch.setattr(state_registry, "record_alert_delivery",
                         lambda *a, **k: record_calls.append((a, k)))
    appt = {"id": 100, "conversation_id": "conv-y", "channel": "whatsapp",
            "customer_name": "Calvin", "title": "Intake call",
            "date_time_label": "Friday 12:00", "proposed_times": ["Friday 12:00"],
            "location": "", "status": "confirmed"}
    dapi._fire_appointment_alerts(100, "Calvin", "whatsapp", appt)
    assert smtp_calls == []
    em_rows = [(a, k) for (a, k) in record_calls if a[1] == "email"]
    assert em_rows == []


# ── Brief 242: operator confirm endpoint flips status + triggers dispatch ─

def test_appointment_confirm_by_id_sets_status_and_fires_dispatcher(monkeypatch):
    """Brief 242: helper SELECTs by id, calls appointment_upsert with
    status='confirmed', which transitively fires the Brief 241
    dispatcher. Returns dict with alreadyConfirmed=False on first call."""
    from shared import state_registry
    conv = "test-242-confirm-fresh"
    _wipe_appointments_for(conv)
    rid = state_registry.appointment_upsert(
        conv, "whatsapp", "Calvin", "Intake call",
        ["Friday 12:00"], status="pending_team_confirmation")
    fired = []
    monkeypatch.setattr(state_registry, "_appointment_alert_dispatcher",
                         lambda *a, **k: fired.append(a))
    result = state_registry.appointment_confirm_by_id(rid)
    assert result is not None
    assert result["id"] == rid
    assert result["status"] == "confirmed"
    assert result["alreadyConfirmed"] is False
    assert "confirmedAt" in result and result["confirmedAt"]
    assert len(fired) == 1
    assert fired[0][0] == rid


def test_appointment_confirm_by_id_idempotent_on_second_call(monkeypatch):
    """Brief 242: a second confirm on an already-confirmed row returns
    alreadyConfirmed=True and does NOT fire the dispatcher again
    (Brief 241 transition detection: confirmed→confirmed = no-fire)."""
    from shared import state_registry
    conv = "test-242-confirm-twice"
    _wipe_appointments_for(conv)
    rid = state_registry.appointment_upsert(
        conv, "whatsapp", "Calvin", "Intake call",
        ["Friday 12:00"], status="confirmed")
    fired = []
    monkeypatch.setattr(state_registry, "_appointment_alert_dispatcher",
                         lambda *a, **k: fired.append(a))
    result = state_registry.appointment_confirm_by_id(rid)
    assert result["status"] == "confirmed"
    assert result["alreadyConfirmed"] is True
    assert fired == []


def test_appointment_confirm_by_id_returns_none_for_missing():
    """Brief 242: helper returns None when appointment_id matches no
    row. Caller surfaces 404."""
    from shared import state_registry
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM appointments WHERE id = 99999999")
    conn.commit()
    conn.close()
    result = state_registry.appointment_confirm_by_id(99999999)
    assert result is None


def test_confirm_endpoint_returns_404_for_missing_appointment():
    """Brief 242: POST /appointments/{id}/confirm returns 404 with
    detail='appointment not found' when the id matches no row in the
    appointments table.

    Uses the real `_login()` pattern from `test_228_appointments.py:55`
    (NOT a monkeypatch on _check_auth — FastAPI's Depends captures the
    callable at decoration time, so module-level monkeypatch does not
    swap the dependency on already-registered routes). Exercises the
    real `appointment_confirm_by_id(<id-with-no-row>)` path so the test
    integrates the helper SELECT + None return + endpoint 404 raise
    end-to-end, not just the endpoint's `if result is None` check."""
    import os
    os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
    from fastapi.testclient import TestClient
    from agents.social.webhook_server import app
    from shared import state_registry
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM appointments WHERE id = 9999991")
    conn.commit()
    conn.close()
    client = TestClient(app)
    login_r = client.post(
        "/dashboard/api/login", json={"password": "testpass"})
    assert login_r.status_code == 200, f"login failed: {login_r.text}"
    token = login_r.json()["token"]
    resp = client.post(
        "/dashboard/api/appointments/9999991/confirm",
        json={"confirmedBy": "operator"},
        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "appointment not found"


# ── Brief 243: HTML CTA buttons + dashboard deep-links in alert emails ─

def test_resolve_dashboard_link_builds_path_when_slug_and_url_present(
        monkeypatch):
    """Brief 243: helper returns f"{base}/{slug}/escalations/{id}" or
    f"{base}/{slug}/appointments/{id}" when business.slug and
    business.dashboard_url are both present in client.json."""
    from dashboard import api as dapi
    from shared import config_loader
    monkeypatch.setattr(config_loader, "get_business",
                         lambda: {"slug": "unboks",
                                   "dashboard_url": "https://dashboard.unboks.org"})
    assert dapi._resolve_dashboard_link("escalation", 42) == \
        "https://dashboard.unboks.org/unboks/escalations/42"
    assert dapi._resolve_dashboard_link("appointment", 99) == \
        "https://dashboard.unboks.org/unboks/appointments/99"
    # Trailing slash on base is normalised
    monkeypatch.setattr(config_loader, "get_business",
                         lambda: {"slug": "unboks",
                                   "dashboard_url": "https://dashboard.unboks.org/"})
    assert dapi._resolve_dashboard_link("escalation", 1) == \
        "https://dashboard.unboks.org/unboks/escalations/1"


def test_resolve_dashboard_link_returns_empty_when_slug_missing(
        monkeypatch):
    """Brief 243: helper returns empty string when business.slug or
    business.dashboard_url is missing — dispatchers fall back to
    plain-text email body, no broken link rendered."""
    from dashboard import api as dapi
    from shared import config_loader
    monkeypatch.setattr(config_loader, "get_business",
                         lambda: {"dashboard_url": "https://dashboard.unboks.org"})
    assert dapi._resolve_dashboard_link("escalation", 42) == ""
    monkeypatch.setattr(config_loader, "get_business",
                         lambda: {"slug": "unboks"})
    assert dapi._resolve_dashboard_link("appointment", 42) == ""
    monkeypatch.setattr(config_loader, "get_business",
                         lambda: {"slug": "unboks",
                                   "dashboard_url": "https://dashboard.unboks.org"})
    assert dapi._resolve_dashboard_link("unknown_kind", 42) == ""


def test_build_alert_html_body_includes_button_and_fallback_url():
    """Brief 243: HTML body contains the CTA <a> button with the
    correct href + label AND a plain-text fallback URL line below
    (so text-stripping clients still get a clickable URL). Plain
    body text is preserved inside <pre>."""
    from dashboard import api as dapi
    text = "Customer: Calvin\nChannel: whatsapp\nAction: review"
    url = "https://dashboard.unboks.org/unboks/escalations/42"
    html = dapi._build_alert_html_body(text, url, "Open escalation")
    assert "<!DOCTYPE html>" in html
    # Button: <a href="..." style="...background-color: #1a73e8...">Open escalation</a>
    assert f'href="{url}"' in html
    assert "background-color: #1a73e8" in html
    assert ">Open escalation</a>" in html
    # Plain-text body inside <pre>
    assert "<pre " in html
    assert "Customer: Calvin" in html  # escaped preserves visible text
    assert "Channel: whatsapp" in html
    # Fallback URL line below the button
    assert "Plain link:" in html
    # The url appears at least twice: once in button href, once in fallback link
    assert html.count(url) >= 2


def test_escalation_dispatcher_passes_html_body_when_link_resolves(
        monkeypatch):
    """Brief 243: when business.slug + dashboard_url are configured,
    _fire_escalation_alerts builds a deep-link and passes html_body=
    to smtp_send. When the helper returns empty, no html_body is
    passed (plain-only fallback)."""
    from dashboard import api as dapi
    from shared import state_registry, config_loader
    captured = []
    def fake_smtp(to, subj, body, **kw):
        captured.append({"to": to, "subj": subj, "body": body,
                          "html_body": kw.get("html_body")})
    monkeypatch.setattr(dapi, "smtp_send", fake_smtp)
    monkeypatch.setattr(state_registry, "get_alert_settings",
                         lambda **k: {
                             "alertTypes": {"escalations": True, "appointments": True},
                             "channels": {"email": {"enabled": True,
                                                     "destination": "ops@example.com",
                                                     "alternativeDestination": ""}}})
    monkeypatch.setattr(state_registry, "record_alert_delivery",
                         lambda *a, **k: None)
    monkeypatch.setattr(config_loader, "get_business",
                         lambda: {"slug": "unboks",
                                   "dashboard_url": "https://dashboard.unboks.org",
                                   "name": "unboks"})
    dapi._fire_escalation_alerts(
        escalation_id=4242,
        customer_name="Calvin",
        channel="whatsapp",
        summary="customer needs help")
    assert len(captured) == 1
    sent = captured[0]
    assert sent["html_body"] is not None
    assert "https://dashboard.unboks.org/unboks/escalations/4242" in sent["html_body"]
    assert ">Open escalation</a>" in sent["html_body"]


def test_appointment_dispatcher_passes_html_body_with_appointment_link(
        monkeypatch):
    """Brief 243: appointment dispatcher builds an appointments deep-link
    and passes html_body= to smtp_send with the 'Open appointment' label."""
    from dashboard import api as dapi
    from shared import state_registry, config_loader
    captured = []
    def fake_smtp(to, subj, body, **kw):
        captured.append({"html_body": kw.get("html_body"), "subj": subj})
    monkeypatch.setattr(dapi, "smtp_send", fake_smtp)
    monkeypatch.setattr(state_registry, "get_alert_settings",
                         lambda **k: {
                             "alertTypes": {"escalations": True, "appointments": True},
                             "channels": {"email": {"enabled": True,
                                                     "destination": "ops@example.com",
                                                     "alternativeDestination": ""}}})
    monkeypatch.setattr(state_registry, "appointment_alert_already_sent",
                         lambda *a, **k: False)
    monkeypatch.setattr(state_registry, "record_alert_delivery",
                         lambda *a, **k: None)
    monkeypatch.setattr(config_loader, "get_business",
                         lambda: {"slug": "unboks",
                                   "dashboard_url": "https://dashboard.unboks.org",
                                   "name": "unboks"})
    appt = {"id": 7777, "conversation_id": "conv-z", "channel": "whatsapp",
            "customer_name": "Calvin", "title": "Intake call",
            "date_time_label": "Friday 12:00",
            "proposed_times": ["Friday 12:00"],
            "location": "Café Paris", "status": "confirmed"}
    dapi._fire_appointment_alerts(7777, "Calvin", "whatsapp", appt)
    assert len(captured) == 1
    sent = captured[0]
    assert sent["html_body"] is not None
    assert "https://dashboard.unboks.org/unboks/appointments/7777" in sent["html_body"]
    assert ">Open appointment</a>" in sent["html_body"]
