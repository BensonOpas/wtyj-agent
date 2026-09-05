"""Durable, action-scoped delivery for operator WhatsApp and email replies.

The provider call cannot share a transaction with SQLite. Persist the exact
payload before that call and reuse its provider idempotency key on every retry.
Only a confirmed provider result may atomically commit the local transcript and
operator effects. Expired workers are fenced by a per-attempt claim token.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Callable

from shared import state_registry


LEASE_SECONDS = 1320.0  # Covers bounded model preparation and provider polling.


class OperatorDeliveryConflict(RuntimeError):
    """An action identity was reused with different original input."""


class OperatorDeliveryBusy(RuntimeError):
    """Another request owns this action, or this worker lost its claim."""


class OperatorDeliveryUnconfirmed(RuntimeError):
    """The provider did not confirm this prepared message."""


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _connect():
    conn = state_registry._get_conn()
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS operator_delivery_outbox ("
        "tenant_id TEXT NOT NULL, action_key TEXT NOT NULL, "
        "conversation_id TEXT NOT NULL, scope TEXT NOT NULL, "
        "request_hash TEXT NOT NULL, anchor TEXT NOT NULL, "
        "payload_json TEXT NOT NULL DEFAULT '', result_json TEXT NOT NULL DEFAULT '', "
        "status TEXT NOT NULL DEFAULT 'prepared', claim_token TEXT NOT NULL DEFAULT '', "
        "lease_until REAL NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '', "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "PRIMARY KEY (tenant_id, action_key))"
    )
    conn.commit()
    return conn


def _anchor(conn, conversation_id: str) -> str:
    row = conn.execute(
        "SELECT id, created_at, source_message_key FROM whatsapp_threads "
        "WHERE phone = ? AND role = 'user' ORDER BY id DESC LIMIT 1",
        (conversation_id,),
    ).fetchone()
    return _json(list(row)) if row else "no-customer-message"


def _check_tenant(tenant_id: str) -> None:
    if state_registry._current_tenant_id() != tenant_id:
        raise OperatorDeliveryConflict("Tenant context changed during delivery")


def _claim(conversation_id: str, scope: str, original: dict, request_id: str) -> dict:
    tenant_id = state_registry._current_tenant_id()
    request_hash = _digest([conversation_id, scope, original])
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        anchor = _anchor(conn, conversation_id)
        action_key = _digest(
            [tenant_id, "request", request_id]
            if request_id else [tenant_id, conversation_id, scope, original, anchor]
        )
        if not request_id:
            # An ambiguous action remains the same action even if the customer
            # writes again before the operator retries an older dashboard UI.
            pending = conn.execute(
                "SELECT action_key FROM operator_delivery_outbox WHERE tenant_id = ? "
                "AND conversation_id = ? AND scope = ? AND request_hash = ? "
                "AND status != 'confirmed' ORDER BY created_at DESC LIMIT 1",
                (tenant_id, conversation_id, scope, request_hash),
            ).fetchone()
            if pending:
                action_key = pending["action_key"]
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO operator_delivery_outbox "
            "(tenant_id, action_key, conversation_id, scope, request_hash, anchor, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (tenant_id, action_key, conversation_id, scope, request_hash, anchor, now, now),
        )
        row = conn.execute(
            "SELECT * FROM operator_delivery_outbox WHERE tenant_id = ? AND action_key = ?",
            (tenant_id, action_key),
        ).fetchone()
        if row["request_hash"] != request_hash:
            raise OperatorDeliveryConflict("request_id was already used with different reply input")
        if row["status"] == "confirmed":
            conn.commit()
            return {**dict(row), "replayed": True}
        if row["claim_token"] and row["lease_until"] > time.time():
            raise OperatorDeliveryBusy("This reply is already being prepared or sent")
        token = uuid.uuid4().hex
        conn.execute(
            "UPDATE operator_delivery_outbox SET claim_token = ?, lease_until = ?, updated_at = ? "
            "WHERE tenant_id = ? AND action_key = ?",
            (token, time.time() + LEASE_SECONDS, now, tenant_id, action_key),
        )
        conn.commit()
        return {**dict(row), "claim_token": token, "replayed": False}
    finally:
        conn.close()


def _claimed_row(conn, claim: dict):
    _check_tenant(claim["tenant_id"])
    row = conn.execute(
        "SELECT * FROM operator_delivery_outbox WHERE tenant_id = ? AND action_key = ?",
        (claim["tenant_id"], claim["action_key"]),
    ).fetchone()
    if (
        row is None or row["claim_token"] != claim["claim_token"]
        or row["lease_until"] <= time.time() or row["status"] == "confirmed"
    ):
        raise OperatorDeliveryBusy("Reply delivery claim expired; retry the same request_id")
    return row


def _freeze_notification_guard(
    conn, claim: dict, payload: dict, *, channel: str,
) -> dict:
    """Bind a prepared reply to the exact operator work-item revision.

    Escalation rows are intentionally reused when another inbound message
    expands the same issue.  The provider call happens outside SQLite, so a
    reply may be in flight while that row is updated.  Persisting the content
    revision with the frozen payload lets finish close the question that was
    actually answered without closing a newer revision.
    """
    notification_id = payload.get("notification_id")
    if notification_id is None or isinstance(payload.get("notification_guard"), dict):
        return payload
    row = conn.execute(
        "SELECT id, customer_id, channel, status, content_revision, relay_token "
        "FROM pending_notifications WHERE id = ?",
        (notification_id,),
    ).fetchone()
    if (
        row is None
        or row["customer_id"] != claim["conversation_id"]
        or row["channel"] != channel
        or row["status"] not in {"pending", "sent"}
    ):
        raise OperatorDeliveryConflict("Operator work item changed before reply preparation")
    expected_revision = payload.get("expected_content_revision")
    if expected_revision is not None and row["content_revision"] != expected_revision:
        raise OperatorDeliveryConflict(
            "Operator work item changed while the reply was being prepared"
        )
    guarded = dict(payload)
    guarded["notification_guard"] = {
        "id": row["id"],
        "customer_id": row["customer_id"],
        "channel": row["channel"],
        "content_revision": row["content_revision"],
    }
    if channel == "whatsapp" and guarded.get("clear_relay"):
        state = conn.execute(
            "SELECT flags_json FROM whatsapp_booking_state WHERE phone = ?",
            (claim["conversation_id"],),
        ).fetchone()
        flags = json.loads(state["flags_json"] or "{}") if state else {}
        guarded["relay_guard"] = {
            "token_present": "relay_token" in flags,
            "token": flags.get("relay_token"),
        }
    return guarded


def _prepare(claim: dict, prepare: Callable[[], dict]) -> dict:
    if claim["payload_json"]:
        payload = json.loads(claim["payload_json"])
    else:
        payload = prepare()
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("text"), str)
        or (not payload["text"].strip() and not payload.get("attachment_url"))
        or len(payload["text"]) > 4096
        or payload.get("role") not in {"operator", "assistant"}
        or not isinstance(payload.get("response"), dict)
    ):
        raise ValueError("Invalid prepared WhatsApp reply")
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _claimed_row(conn, claim)
        payload = _freeze_notification_guard(conn, claim, payload, channel="whatsapp")
        payload_json = _json(payload)
        conn.execute(
            "UPDATE operator_delivery_outbox SET payload_json = ?, status = 'prepared', "
            "lease_until = ?, updated_at = ? WHERE tenant_id = ? AND action_key = ?",
            (payload_json, time.time() + LEASE_SECONDS, datetime.now(timezone.utc).isoformat(),
             claim["tenant_id"], claim["action_key"]),
        )
        conn.commit()
        return json.loads(payload_json)
    finally:
        conn.close()


def _prepare_email(claim: dict, prepare: Callable[[], dict]) -> tuple[dict, str]:
    """Persist one exact email body and retain every post-SMTP retry stage."""
    prepared = json.loads(claim["payload_json"]) if claim["payload_json"] else prepare()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _claimed_row(conn, claim)
        status = str(row["status"] or "prepared")
        if row["payload_json"]:
            payload = json.loads(row["payload_json"])
        else:
            payload = prepared
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("to"), str)
            or "@" not in payload["to"]
            or not isinstance(payload.get("subject"), str)
            or not isinstance(payload.get("text"), str)
            or not payload["text"].strip()
            or len(payload["text"]) > 100_000
            or payload.get("role") not in {"operator", "marina"}
            or not isinstance(payload.get("response"), dict)
            or not isinstance(payload.get("thread_key", ""), str)
        ):
            raise ValueError("Invalid prepared email reply")
        payload = dict(payload)
        payload.setdefault(
            "message_id",
            f"<unboks-operator-{claim['action_key']}@delivery.unboks.local>",
        )
        message_id = str(payload["message_id"])
        if "\r" in message_id or "\n" in message_id or not (
            message_id.startswith("<") and message_id.endswith(">")
        ):
            raise ValueError("Invalid prepared email Message-ID")
        payload = _freeze_notification_guard(conn, claim, payload, channel="email")
        payload_json = _json(payload)
        conn.execute(
            "UPDATE operator_delivery_outbox SET payload_json = ?, status = ?, "
            "lease_until = ?, updated_at = ? WHERE tenant_id = ? AND action_key = ?",
            (
                payload_json,
                status if status in {"provider_confirmed", "effects_committed"} else "prepared",
                time.time() + LEASE_SECONDS,
                datetime.now(timezone.utc).isoformat(),
                claim["tenant_id"],
                claim["action_key"],
            ),
        )
        conn.commit()
        return json.loads(payload_json), status
    finally:
        conn.close()


def _assert_current_claim(claim: dict) -> bool:
    conn = _connect()
    try:
        _claimed_row(conn, claim)
        return True
    finally:
        conn.close()


def _mark_email_provider_confirmed(claim: dict) -> None:
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _claimed_row(conn, claim)
        conn.execute(
            "UPDATE operator_delivery_outbox SET status = 'provider_confirmed', "
            "lease_until = ?, updated_at = ? WHERE tenant_id = ? AND action_key = ?",
            (
                time.time() + LEASE_SECONDS,
                datetime.now(timezone.utc).isoformat(),
                claim["tenant_id"],
                claim["action_key"],
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _complete_guarded_notification(conn, claim: dict, payload: dict, channel: str) -> int:
    notification_id = payload.get("notification_id")
    if notification_id is None:
        return 0
    guard = payload.get("notification_guard")
    if not isinstance(guard, dict):
        # Payloads prepared by this release always carry a guard.  Retain the
        # old anchor fence only for an outbox row created by an older process.
        if channel != "whatsapp" or _anchor(conn, claim["conversation_id"]) != claim["anchor"]:
            return 0
        return conn.execute(
            "UPDATE pending_notifications SET status = 'replied' "
            "WHERE id = ? AND customer_id = ? AND channel = ? "
            "AND status IN ('pending', 'sent')",
            (notification_id, claim["conversation_id"], channel),
        ).rowcount
    if (
        guard.get("id") != notification_id
        or guard.get("customer_id") != claim["conversation_id"]
        or guard.get("channel") != channel
        or not isinstance(guard.get("content_revision"), int)
    ):
        raise OperatorDeliveryConflict("Invalid operator work-item guard")
    return conn.execute(
        "UPDATE pending_notifications SET status = 'replied' "
        "WHERE id = ? AND customer_id = ? AND channel = ? "
        "AND content_revision = ? AND status IN ('pending', 'sent')",
        (
            notification_id,
            claim["conversation_id"],
            channel,
            guard["content_revision"],
        ),
    ).rowcount


def _finish(claim: dict, payload: dict) -> dict:
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _claimed_row(conn, claim)
        now = datetime.now(timezone.utc).isoformat()
        source_key = "operator-action:" + claim["action_key"]
        stored_text = payload["text"] or "[Image sent]"
        conn.execute(
            "INSERT OR IGNORE INTO whatsapp_threads "
            "(phone, role, text, created_at, channel, source_message_key) VALUES (?, ?, ?, ?, 'whatsapp', ?)",
            (claim["conversation_id"], payload["role"], stored_text, now, source_key),
        )
        if payload.get("image_notice") and payload.get("attachment_url"):
            conn.execute(
                "INSERT OR IGNORE INTO whatsapp_threads "
                "(phone, role, text, created_at, channel, source_message_key) "
                "VALUES (?, 'system', 'Image sent', ?, 'whatsapp', ?)",
                (claim["conversation_id"], now, source_key + ":image"),
            )
        if payload.get("attachment_url") and payload.get("media_id"):
            conn.execute(
                "UPDATE photo_library SET used_count = used_count + 1 WHERE id = ?",
                (payload["media_id"],),
            )
        # Finish the exact work-item revision that produced this reply.  A new
        # customer message alone does not strand the old answered item; an
        # updated/re-escalated row fails the revision CAS and remains active.
        anchor_unchanged = _anchor(conn, claim["conversation_id"]) == claim["anchor"]
        completed = _complete_guarded_notification(conn, claim, payload, "whatsapp")
        if payload.get("notification_id") is not None and claim["tenant_id"] == "mermaid":
            state_registry._sync_mermaid_escalation_freezes(
                conn, claim["conversation_id"], "whatsapp", now
            )
        may_clear_relay = bool(completed) or (
            payload.get("notification_id") is None and anchor_unchanged
        )
        if payload.get("clear_relay") and may_clear_relay:
            state = conn.execute(
                "SELECT flags_json FROM whatsapp_booking_state WHERE phone = ?",
                (claim["conversation_id"],),
            ).fetchone()
            if state:
                flags = json.loads(state["flags_json"] or "{}")
                relay_guard = payload.get("relay_guard")
                relay_unchanged = anchor_unchanged
                if isinstance(relay_guard, dict):
                    relay_unchanged = (
                        bool(relay_guard.get("token_present")) == ("relay_token" in flags)
                        and relay_guard.get("token") == flags.get("relay_token")
                    )
                if relay_unchanged:
                    for name in ("awaiting_relay", "relay_token", "relay_question"):
                        flags.pop(name, None)
                    conn.execute(
                        "UPDATE whatsapp_booking_state SET flags_json = ? WHERE phone = ?",
                        (_json(flags), claim["conversation_id"]),
                    )
        result = payload["response"]
        conn.execute(
            "UPDATE operator_delivery_outbox SET status = 'confirmed', result_json = ?, "
            "claim_token = '', lease_until = 0, last_error = '', updated_at = ? "
            "WHERE tenant_id = ? AND action_key = ?",
            (_json(result), now, claim["tenant_id"], claim["action_key"]),
        )
        conn.commit()
        return result
    finally:
        conn.close()


def _finish_email(claim: dict, payload: dict) -> dict:
    """Finish retryable local effects after SMTP has accepted the message.

    The transcript is a JSON sidecar while review state is in SQLite, so one
    transaction cannot cover both.  ``effects_committed`` is a durable stage:
    a retry after either local write fails reuses the transcript key and skips
    SMTP.
    """
    _assert_current_claim(claim)
    source_key = "operator-email-action:" + claim["action_key"]
    state_registry.email_append_assistant_message(
        claim["conversation_id"],
        payload["text"],
        role=payload["role"],
        source_message_key=source_key,
        strict=True,
        thread_key=payload.get("thread_key", ""),
    )

    should_clear_email_review = False
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _claimed_row(conn, claim)
        if row["status"] not in {"provider_confirmed", "effects_committed"}:
            raise OperatorDeliveryUnconfirmed("Email delivery is not provider-confirmed")
        now = datetime.now(timezone.utc).isoformat()
        result = payload["response"]
        if row["status"] == "provider_confirmed":
            if payload.get("notification_id") is not None:
                _complete_guarded_notification(conn, claim, payload, "email")
                if claim["tenant_id"] == "mermaid":
                    has_active_review, _ = state_registry._sync_mermaid_escalation_freezes(
                        conn, claim["conversation_id"], "email", now
                    )
                    should_clear_email_review = not has_active_review
            conn.execute(
                "UPDATE operator_delivery_outbox SET status = 'effects_committed', "
                "result_json = ?, lease_until = ?, last_error = '', updated_at = ? "
                "WHERE tenant_id = ? AND action_key = ?",
                (
                    _json(result),
                    time.time() + LEASE_SECONDS,
                    now,
                    claim["tenant_id"],
                    claim["action_key"],
                ),
            )
        elif payload.get("notification_id") is not None and claim["tenant_id"] == "mermaid":
            has_active_review, _ = state_registry._sync_mermaid_escalation_freezes(
                conn, claim["conversation_id"], "email", now
            )
            should_clear_email_review = not has_active_review
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if should_clear_email_review:
        state_registry.email_clear_fully_escalated_flag(
            claim["conversation_id"],
            strict=True,
            require_no_active_review=True,
        )

    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _claimed_row(conn, claim)
        if row["status"] != "effects_committed":
            raise OperatorDeliveryUnconfirmed("Email delivery effects are not committed")
        now = datetime.now(timezone.utc).isoformat()
        result = payload["response"]
        conn.execute(
            "UPDATE operator_delivery_outbox SET status = 'confirmed', result_json = ?, "
            "claim_token = '', lease_until = 0, last_error = '', updated_at = ? "
            "WHERE tenant_id = ? AND action_key = ?",
            (_json(result), now, claim["tenant_id"], claim["action_key"]),
        )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _release(claim: dict, error: Exception) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE operator_delivery_outbox SET claim_token = '', lease_until = 0, "
            "last_error = ?, updated_at = ? WHERE tenant_id = ? AND action_key = ? "
            "AND claim_token = ? AND status != 'confirmed'",
            (type(error).__name__, datetime.now(timezone.utc).isoformat(),
             claim["tenant_id"], claim["action_key"], claim["claim_token"]),
        )
        conn.commit()
    finally:
        conn.close()


def deliver(
    *, conversation_id: str, scope: str, original: dict,
    prepare: Callable[[], dict], sender: Callable, request_id: str = "",
) -> tuple[dict, bool]:
    """Return the stable response and whether this is a confirmed replay."""
    request_id = str(request_id or "")
    if len(request_id) > 128 or any(ord(char) < 32 for char in request_id):
        raise OperatorDeliveryConflict("Invalid request_id")
    claim = _claim(conversation_id, scope, original, request_id)
    if claim["replayed"]:
        _check_tenant(claim["tenant_id"])
        return json.loads(claim["result_json"]), True
    try:
        _assert_current_claim(claim)
        payload = _prepare(claim, prepare)
        kwargs = {
            "confirm_delivery": True,
            "idempotency_key": "unboks-operator-" + claim["action_key"],
        }
        if payload.get("attachment_url"):
            kwargs.update(attachment_url=payload["attachment_url"], attachment_type="image")
        from agents.social.zernio_dm_client import provider_mutation_scope

        # Explicit operator actions do not inherit an automated worker's AI
        # pause gate. They still recheck their own lease/tenant at every actual
        # provider POST, in addition to the provider's account ownership guard.
        with provider_mutation_scope(lambda: _assert_current_claim(claim)):
            _assert_current_claim(claim)
            sent = sender(conversation_id, payload["text"], **kwargs)
        if sent is not True:
            _assert_current_claim(claim)
            raise OperatorDeliveryUnconfirmed("WhatsApp no confirmó el envío.")
        return _finish(claim, payload), False
    except Exception as exc:
        _release(claim, exc)
        raise


def deliver_email(
    *, conversation_id: str, scope: str, original: dict,
    prepare: Callable[[], dict], sender: Callable, request_id: str = "",
) -> tuple[dict, bool]:
    """Send one durable email action and finish local effects exactly once."""
    request_id = str(request_id or "")
    if len(request_id) > 128 or any(ord(char) < 32 for char in request_id):
        raise OperatorDeliveryConflict("Invalid request_id")
    claim = _claim(conversation_id, scope, original, request_id)
    if claim["replayed"]:
        _check_tenant(claim["tenant_id"])
        return json.loads(claim["result_json"]), True
    try:
        _assert_current_claim(claim)
        payload, status = _prepare_email(claim, prepare)
        if status not in {"provider_confirmed", "effects_committed"}:
            _assert_current_claim(claim)
            sender(
                payload["to"], payload["subject"], payload["text"],
                message_id=payload["message_id"],
            )
            _mark_email_provider_confirmed(claim)
        return _finish_email(claim, payload), False
    except Exception as exc:
        _release(claim, exc)
        raise
