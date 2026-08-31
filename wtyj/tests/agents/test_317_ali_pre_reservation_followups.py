"""Brief 317: Meta-safe pre-reservation WhatsApp follow-ups."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from agents.marina import marina_agent
from agents.social import ali_lead_follow_up as follow_up
from agents.social import zernio_dm_client
from shared import state_registry


BASE = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
CONFIG = {
    "slug": "ali-car-rental",
    "features": {"ali_pre_reservation_reminders_enabled": True},
    "workflow": {
        "type": "ali_quote",
        "pre_reservation_follow_up": {
            "reminder_hours": [3, 8, 22],
            "quiet_hours_start": "20:30",
            "quiet_hours_end": "08:30",
            "default_timezone": "America/Curacao",
            "messages": {
                "en": {
                    "3": "Three-hour check-in",
                    "8": "Eight-hour check-in",
                    "22": "Final in-window check-in",
                },
            },
        },
    },
}


@pytest.fixture
def lead_db(monkeypatch, tmp_path):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(follow_up.config_loader, "get_raw", lambda: CONFIG)
    follow_up.ensure_schema(now=BASE)
    return tmp_path / "state.db"


def _set_time(table: str, where: str, values: tuple, stamp: datetime) -> None:
    conn = state_registry._get_conn()
    conn.execute(
        f"UPDATE {table} SET created_at=?, updated_at=? WHERE {where}",
        (stamp.isoformat(), stamp.isoformat(), *values),
    )
    conn.commit()
    conn.close()


def _seed_turn(
    conversation_id: str,
    stamp: datetime,
    *,
    message_id: str = "wamid-inbound-1",
    assistant_at: datetime | None = None,
) -> None:
    state_registry.wa_save_booking_state(
        conversation_id,
        {"conversation_language": "en"},
        {},
    )
    state_registry.dm_store_message(
        conversation_id,
        "whatsapp",
        "user",
        "I may need a car",
        created_at=stamp.isoformat(),
    )
    state_registry.dm_store_message(
        conversation_id,
        "whatsapp",
        "assistant",
        "How can I help?",
        created_at=(assistant_at or stamp + timedelta(seconds=1)).isoformat(),
    )
    state_registry.inbound_processing_record(
        message_id,
        conversation_id,
        "whatsapp",
        status="completed",
        payload={
            "message_id": message_id,
            "account_id": "account-1",
            "sender_id": "+59990000000",
            "sent_at": stamp.isoformat(),
        },
    )
    _set_time(
        "inbound_processing_events",
        "message_id=?",
        (message_id,),
        stamp,
    )


def _webhook_module(monkeypatch):
    # webhook_server captures this value at import time. Keep the suite's
    # canonical value so importing the scheduler here cannot pollute the
    # later webhook verification tests.
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "test_token_067")
    from agents.social import webhook_server

    return webhook_server


def test_reminders_follow_latest_customer_message_at_3_8_and_22_hours(
    lead_db, monkeypatch,
):
    settings = CONFIG["workflow"]["pre_reservation_follow_up"]
    monkeypatch.setitem(settings, "quiet_hours_start", "00:00")
    monkeypatch.setitem(settings, "quiet_hours_end", "00:00")
    anchor = BASE + timedelta(minutes=1)
    _seed_turn("conversation-1", anchor)

    first = follow_up.claim_due_follow_ups(now=anchor + timedelta(hours=3))
    assert [item["milestoneSeconds"] for item in first] == [3 * 3600]
    assert first[0]["message"] == "Three-hour check-in"
    follow_up.record_delivery_result(first[0], status="sent", now=anchor + timedelta(hours=3))

    second = follow_up.claim_due_follow_ups(now=anchor + timedelta(hours=8))
    assert [item["milestoneSeconds"] for item in second] == [8 * 3600]
    follow_up.record_delivery_result(second[0], status="sent", now=anchor + timedelta(hours=8))

    final = follow_up.claim_due_follow_ups(now=anchor + timedelta(hours=22))
    assert [item["milestoneSeconds"] for item in final] == [22 * 3600]
    assert datetime.fromisoformat(final[0]["windowExpiresAt"]) == (
        anchor + timedelta(hours=23, minutes=50)
    )


def test_internal_system_audit_after_nick_reply_does_not_suppress_reminder(
    lead_db, monkeypatch,
):
    settings = CONFIG["workflow"]["pre_reservation_follow_up"]
    monkeypatch.setitem(settings, "quiet_hours_start", "00:00")
    monkeypatch.setitem(settings, "quiet_hours_end", "00:00")
    anchor = BASE + timedelta(minutes=2)
    _seed_turn("conversation-system-audit", anchor)
    state_registry.dm_store_message(
        "conversation-system-audit",
        "whatsapp",
        "system",
        "Ali vehicle recommendation sent: synthetic audit",
        created_at=(anchor + timedelta(seconds=2)).isoformat(),
    )

    due = follow_up.claim_due_follow_ups(now=anchor + timedelta(hours=3))

    assert [item["conversationId"] for item in due] == [
        "conversation-system-audit"
    ]
    assert due[0]["message"] == "Three-hour check-in"


def test_customer_reply_resets_the_entire_schedule(lead_db):
    first_anchor = BASE + timedelta(minutes=1)
    _seed_turn("conversation-reset", first_anchor)
    first = follow_up.claim_due_follow_ups(now=first_anchor + timedelta(hours=3))
    follow_up.record_delivery_result(first[0], status="sent", now=first_anchor + timedelta(hours=3))

    second_anchor = first_anchor + timedelta(hours=4)
    _seed_turn(
        "conversation-reset",
        second_anchor,
        message_id="wamid-inbound-2",
    )
    assert follow_up.claim_due_follow_ups(
        now=second_anchor + timedelta(hours=2, minutes=59),
    ) == []
    reset = follow_up.claim_due_follow_ups(
        now=second_anchor + timedelta(hours=3),
    )
    assert [item["milestoneSeconds"] for item in reset] == [3 * 3600]
    assert reset[0]["anchorMessageId"] == "wamid-inbound-2"


def test_quiet_hours_defer_and_coalesce_without_crossing_meta_window(lead_db):
    anchor = datetime(2026, 9, 1, 23, 0, tzinfo=timezone.utc)  # 19:00 Curaçao
    _seed_turn("conversation-quiet", anchor)

    assert follow_up.claim_due_follow_ups(
        now=anchor + timedelta(hours=3),  # 22:00 Curaçao
    ) == []
    resumed = follow_up.claim_due_follow_ups(
        now=datetime(2026, 9, 2, 12, 30, tzinfo=timezone.utc),  # 08:30 Curaçao
    )
    assert [item["milestoneSeconds"] for item in resumed] == [8 * 3600]


def test_expired_window_is_terminal_and_never_claimed(lead_db):
    anchor = BASE + timedelta(minutes=1)
    _seed_turn("conversation-expired", anchor)
    assert follow_up.claim_due_follow_ups(
        now=anchor + timedelta(hours=23, minutes=51),
    ) == []

    conn = state_registry._get_conn()
    statuses = {
        row[0]
        for row in conn.execute(
            "SELECT status FROM ali_lead_follow_up_deliveries "
            "WHERE conversation_id='conversation-expired'"
        ).fetchall()
    }
    conn.close()
    assert statuses == {"skipped_window"}


def test_rollout_is_non_retroactive_and_reservation_or_stop_cancels(lead_db):
    _seed_turn("before-rollout", BASE - timedelta(minutes=1), message_id="old")
    assert follow_up.claim_due_follow_ups(now=BASE + timedelta(hours=4)) == []

    active_anchor = BASE + timedelta(minutes=1)
    _seed_turn("stopped", active_anchor, message_id="stopped-inbound")
    follow_up.record_customer_action(
        "stopped",
        {"anchor_message_id": "follow-up-anchor"},
        "stop",
        now=active_anchor + timedelta(hours=1),
    )

    _seed_turn("reserved", active_anchor, message_id="reserved-inbound")
    conn = state_registry._get_conn()
    conn.execute(
        "INSERT INTO ali_reservations (public_id, tenant_slug, quote_public_id, "
        "quote_snapshot_id, quote_reference, conversation_id, zernio_account_id, "
        "status, availability_status, identity_status, agreement_status, "
        "payment_status, created_at, updated_at) VALUES "
        "('reservation-1', 'ali-car-rental', 'quote-1', 'snapshot-1', 'ALI-Q1', "
        "'reserved', 'account-1', 'requirements_pending', 'approved', "
        "'requested', 'not_sent', 'not_requested', ?, ?)",
        (active_anchor.isoformat(), active_anchor.isoformat()),
    )
    conn.commit()
    conn.close()

    assert follow_up.claim_due_follow_ups(
        now=active_anchor + timedelta(hours=3),
    ) == []


def test_customer_reply_to_reminder_is_classified_once(lead_db):
    anchor = BASE + timedelta(minutes=1)
    _seed_turn("conversation-action", anchor)
    plan = follow_up.claim_due_follow_ups(now=anchor + timedelta(hours=3))[0]
    sent_at = anchor + timedelta(hours=3)
    follow_up.record_delivery_result(plan, status="sent", now=sent_at)
    state_registry.dm_store_message(
        "conversation-action",
        "whatsapp",
        "user",
        "Please continue",
        created_at=(sent_at + timedelta(minutes=1)).isoformat(),
    )

    context = follow_up.pending_reply_context("conversation-action")
    assert context == {
        "anchor_message_id": "wamid-inbound-1",
        "milestone_hours": 3.0,
    }
    follow_up.record_customer_action(
        "conversation-action", context, "continue", now=sent_at + timedelta(minutes=1),
    )
    assert follow_up.pending_reply_context("conversation-action") is None


@pytest.mark.parametrize(
    ("reason", "expected_status"),
    [
        ("provider_unavailable", "failed"),
        ("window_closed", "skipped_window"),
    ],
)
def test_scheduler_fails_closed_when_provider_window_cannot_be_verified(
    monkeypatch, reason, expected_status,
):
    webhook_server = _webhook_module(monkeypatch)
    plan = {
        "conversationId": "conversation-1",
        "accountId": "account-1",
        "anchorMessageId": "wamid-1",
        "latestInboundAt": BASE.isoformat(),
        "milestoneSeconds": 3 * 3600,
        "message": "Check in",
        "idempotencyKey": "follow-up-1",
    }
    monkeypatch.setattr(follow_up, "enabled", lambda: True)
    monkeypatch.setattr(follow_up, "claim_due_follow_ups", lambda: [plan])
    recorded = []
    monkeypatch.setattr(
        follow_up,
        "record_delivery_result",
        lambda item, **kwargs: recorded.append((item, kwargs)),
    )
    monkeypatch.setattr(
        zernio_dm_client,
        "whatsapp_customer_service_window",
        lambda *args: {"open": False, "reason": reason},
    )
    sent = Mock()
    monkeypatch.setattr(webhook_server, "send_reply", sent)

    assert webhook_server._run_ali_lead_follow_up_scheduled_once() == 1
    sent.assert_not_called()
    assert recorded[0][1] == {
        "status": expected_status,
        "error_code": reason,
    }


def test_scheduler_sends_and_persists_only_after_provider_window_check(monkeypatch):
    webhook_server = _webhook_module(monkeypatch)
    plan = {
        "conversationId": "conversation-1",
        "accountId": "account-1",
        "anchorMessageId": "wamid-1",
        "latestInboundAt": BASE.isoformat(),
        "milestoneSeconds": 3 * 3600,
        "message": "Check in",
        "idempotencyKey": "follow-up-1",
    }
    monkeypatch.setattr(follow_up, "enabled", lambda: True)
    monkeypatch.setattr(follow_up, "claim_due_follow_ups", lambda: [plan])
    monkeypatch.setattr(
        zernio_dm_client,
        "whatsapp_customer_service_window",
        lambda *args: {"open": True, "reason": "open"},
    )
    monkeypatch.setattr(webhook_server, "send_reply", lambda *args, **kwargs: True)
    stored = Mock()
    recorded = Mock()
    monkeypatch.setattr(webhook_server.state_registry, "dm_store_message", stored)
    monkeypatch.setattr(follow_up, "record_delivery_result", recorded)

    assert webhook_server._run_ali_lead_follow_up_scheduled_once() == 1
    stored.assert_called_once_with(
        "conversation-1", "whatsapp", "assistant", "Check in",
    )
    recorded.assert_called_once_with(plan, status="sent", error_code="")


def test_provider_window_uses_latest_inbound_and_fails_closed(monkeypatch):
    monkeypatch.setenv("LATE_API_KEY", "test-key")
    current = datetime.now(timezone.utc)
    response = Mock(status_code=200)
    response.json.return_value = {
        "messages": [{
            "direction": "incoming",
            "createdAt": (current - timedelta(hours=1)).isoformat(),
        }],
    }
    monkeypatch.setattr(zernio_dm_client.http_requests, "get", lambda *a, **k: response)
    result = zernio_dm_client.whatsapp_customer_service_window(
        "conversation-1", "account-1",
    )
    assert result["open"] is True

    response.status_code = 503
    unavailable = zernio_dm_client.whatsapp_customer_service_window(
        "conversation-1", "account-1",
    )
    assert unavailable == {"open": False, "reason": "provider_unavailable"}


def test_marina_tool_exposes_structured_continue_stop_decision():
    action = marina_agent.MARINA_TOOL["input_schema"]["properties"][
        "ali_lead_follow_up_action"
    ]
    assert action["enum"] == ["continue", "stop", "none"]
    assert marina_agent._RESPONSE_DEFAULTS["ali_lead_follow_up_action"] == "none"
