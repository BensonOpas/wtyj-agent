"""Tests for Brief 235 — escalation summary readback works on production
data shape (status='sent') and dispatcher registers in the email_poller
process via the shared module side-effect import."""
import json
from unittest.mock import patch

from shared import state_registry


def _reset(prefix: str = "test235"):
    conn = state_registry._get_conn()
    conn.execute(
        "DELETE FROM pending_notifications WHERE customer_id LIKE ?",
        (f"{prefix}%",))
    conn.execute(
        "DELETE FROM conversation_status WHERE conversation_id LIKE ?",
        (f"{prefix}%",))
    conn.commit()
    conn.close()


def _insert_escalation(customer_id: str, status: str, summary_dict=None):
    """Insert directly to bypass the dispatcher — we want to test the
    READBACK on a row whose status reflects production reality."""
    from datetime import datetime, timezone
    conn = state_registry._get_conn()
    conn.execute(
        "INSERT INTO pending_notifications "
        "(notification_type, channel, customer_id, customer_name, "
        "subject, body, status, created_at, escalation_summary) "
        "VALUES ('escalation', 'whatsapp', ?, 'Test', 'subj', 'body', ?, ?, ?)",
        (customer_id, status,
         datetime.now(timezone.utc).isoformat(),
         json.dumps(summary_dict) if summary_dict else None))
    conn.commit()
    conn.close()


def test_readback_finds_sent_row_with_summary():
    """Brief 235: get_active_escalation_summary_for must return the
    summary for a row with status='sent' (the actual production state
    after Brief 217's alert dispatcher transitions pending → sent)."""
    _reset()
    customer_id = "test235-alice@example.com"
    summary = {
        "reason": "Alice wants to schedule a call",
        "customerWants": "Activation meeting",
        "operatorNeedsToDecide": "Confirm time",
        "recommendedOptions": ["Confirm Thursday 09:00"],
        "extractedDetails": {"intent": "scheduling",
                             "proposedTimes": ["Thursday 09:00"],
                             "topic": "activation call"},
    }
    _insert_escalation(customer_id, status="sent", summary_dict=summary)
    result = state_registry.get_active_escalation_summary_for(customer_id)
    assert result is not None
    assert result["customerWants"] == "Activation meeting"
    assert result["recommendedOptions"] == ["Confirm Thursday 09:00"]


def test_readback_still_finds_pending_row():
    """Brief 235: backward compat — 'pending' rows (rare race window
    between insert and dispatcher) still match the new IN filter."""
    _reset()
    customer_id = "test235-bob@example.com"
    summary = {"reason": "Bob's escalation", "customerWants": "x",
               "operatorNeedsToDecide": "y", "recommendedOptions": [],
               "extractedDetails": {"intent": "other",
                                    "proposedTimes": [], "topic": "z"}}
    _insert_escalation(customer_id, status="pending", summary_dict=summary)
    result = state_registry.get_active_escalation_summary_for(customer_id)
    assert result is not None
    assert result["reason"] == "Bob's escalation"


def test_readback_skips_replied_row():
    """Brief 235: 'replied' rows are explicit operator-answered state
    and must NOT show up as active escalations. Tests the EXCLUSION
    side of the new IN filter."""
    _reset()
    customer_id = "test235-carol@example.com"
    summary = {"reason": "old", "customerWants": "x",
               "operatorNeedsToDecide": "y", "recommendedOptions": [],
               "extractedDetails": {"intent": "other",
                                    "proposedTimes": [], "topic": "z"}}
    _insert_escalation(customer_id, status="replied", summary_dict=summary)
    result = state_registry.get_active_escalation_summary_for(customer_id)
    assert result is None


def test_dedup_updates_existing_sent_row():
    """Brief 235: when a customer triggers a second escalation while one
    is still 'sent' (alert fired but operator hasn't replied), dedup
    must UPDATE the existing row instead of inserting a new one."""
    _reset()
    customer_id = "test235-dan@example.com"
    _insert_escalation(customer_id, status="sent")
    conn = state_registry._get_conn()
    before = conn.execute(
        "SELECT COUNT(*) FROM pending_notifications WHERE customer_id = ?",
        (customer_id,)).fetchone()[0]
    conn.close()
    assert before == 1

    with patch.object(state_registry, "_alert_dispatcher", None), \
         patch.object(state_registry, "_summary_dispatcher", None):
        new_id = state_registry.create_pending_notification(
            notification_type="escalation",
            channel="whatsapp",
            customer_id=customer_id,
            customer_name="Dan",
            subject="second escalation",
            body="another alert body")

    conn = state_registry._get_conn()
    after = conn.execute(
        "SELECT COUNT(*), MAX(subject) FROM pending_notifications "
        "WHERE customer_id = ?", (customer_id,)).fetchone()
    conn.close()
    assert after[0] == 1
    assert after[1] == "second escalation"


def test_shared_dispatcher_module_registers_on_import():
    """Brief 235: importing shared.escalation_dispatcher installs the
    summary generator in this process. Validates the side-effect import
    pattern that fixes the email_poller process."""
    state_registry._summary_dispatcher = None
    assert state_registry._summary_dispatcher is None

    import importlib
    from shared import escalation_dispatcher
    importlib.reload(escalation_dispatcher)

    assert state_registry._summary_dispatcher is not None
    assert state_registry._summary_dispatcher.__name__ == "_generate_escalation_summary"
