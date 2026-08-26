# bluemarlin/agents/social/webhook_server.py
# Created: Brief 067
# Last modified: Brief 138
# Purpose: FastAPI webhook receiver for Meta WhatsApp Cloud API

import json as _json
import hashlib
import os
import time
import threading
from fastapi import BackgroundTasks, FastAPI, Request, Query
from fastapi.responses import PlainTextResponse

from shared.bm_logger import log
from shared import state_registry
from shared import config_loader
from shared import response_timing
from shared import icp_overrides
from agents.social.whatsapp_client import parse_webhook_payload, send_text_message
from agents.social.social_agent import handle_incoming_whatsapp_message
from agents.social.zernio_dm_client import (
    parse_zernio_failed_webhook,
    parse_zernio_webhook,
    parse_zernio_sent_webhook,
    verify_webhook_signature,
    send_dm_reply,
    send_dm_quote_confirmation,
    send_dm_vehicle_recommendation,
    send_typing_indicator,
)
from agents.social.dm_agent import handle_incoming_dm
from agents.social.channels import ZERNIO_CHANNELS, DEFAULT_ZERNIO_CHANNEL
from agents.social.senders import send_reply
from agents.social.ali_quote_workflow import (
    QUOTE_CONFIRMATION_FALLBACK_INSTRUCTION,
    commit_ali_turn_delivery,
    mark_quote_confirmation_failure_recovered,
    reconcile_quote_confirmation_failure,
)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    # Brief 190: content pipeline archived — scheduler only starts when explicitly enabled
    if config_loader.get_raw().get("features", {}).get("content_pipeline", False):
        from agents.social.scheduler import start_scheduler
        start_scheduler()
    from agents.social.ali_quote_workflow import resume_pending_processing
    resume_pending_processing()
    yield

app = FastAPI(title="WTYJ Agent", docs_url=None, redoc_url=None, lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    # J3-N2-13: replaced the previous mixed allow_origins + regex with
    # the owner-specified spec. Explicit production origin +
    # any-localhost-port via regex (Starlette does not interpret "*"
    # inside an origin string, so "http://localhost:*" can only be
    # honoured via allow_origin_regex).
    allow_origins=["https://dashboard.unboks.org"],
    allow_origin_regex=r"^http://localhost(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _use_whatsapp_orchestrator(channel: str) -> bool:
    """Use the structured agent for booking and dedicated WhatsApp workflows."""
    raw = config_loader.get_raw() or {}
    if (raw.get("features") or {}).get("booking_flow", True):
        return True
    workflow = raw.get("workflow") or {}
    return (
        str(channel or "").strip().lower() == "whatsapp"
        and workflow.get("type") in {"callback_follow_up", "ali_quote"}
    )


def _sanitize_tenant_whatsapp_reply(reply_text: str, channel: str) -> str:
    """Apply tenant-specific safety at the final AI outbound boundary."""
    text = str(reply_text or "").strip()
    if not text or str(channel or "").strip().lower() != "whatsapp":
        return text
    try:
        from agents.social.ali_quote_workflow import (
            sanitize_intake_reply,
            tenant_configured,
        )
        if not tenant_configured():
            return text
        safe_text = sanitize_intake_reply(text)
        if safe_text != text:
            log("ali_quote_outbound_reply_sanitized", channel="whatsapp")
        return safe_text
    except Exception as exc:
        log("ali_quote_outbound_safety_failed", error=str(exc)[:200])
        return ""

from dashboard.api import router as dashboard_router
app.include_router(dashboard_router)

# Brief 207: Tasks API mounted at root level (/tasks/*) so SR's frontend's
# /api/unboks/tasks calls (after nginx prefix-strip → /tasks) hit it directly.
from dashboard.tasks_api import router as tasks_router
app.include_router(tasks_router)


@app.get("/api/public/ali-quote/{public_id}")
async def download_ali_quote(public_id: str, expires: int, signature: str):
    """Serve one private quote through a 60-minute HMAC URL."""
    from agents.social.ali_quote_download import quote_download_response
    return quote_download_response(public_id, expires, signature)

_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
_last_cleanup_ts = 0

# Message batching coalesces rapid customer messages into one Marina call. It
# does NOT protect against concurrent orchestrator access - the per-phone lock
# below solves that different problem. Timing is tenant-configurable via
# client.json/Nr2 and optional Nr3 admin override.

_message_buffers = {}   # phone -> {"messages": [...], "timer": Timer, "started": float}
_buffer_lock = threading.Lock()

# Brief 161: per-phone lock serializes concurrent handle_incoming_whatsapp_message
# calls for the same phone/conversation. Fixes race where msg 2 reads stale state
# before msg 1 has persisted its orchestrator output. Keyed by conversation_id
# (Zernio) or phone (legacy Meta). Registry grows monotonically; locks are cheap.
_phone_locks = {}  # key -> threading.Lock
_phone_locks_registry_lock = threading.Lock()


def _get_phone_lock(key: str) -> threading.Lock:
    """Get or create a per-phone lock for serializing orchestrator calls."""
    with _phone_locks_registry_lock:
        lock = _phone_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _phone_locks[key] = lock
        return lock


def _message_ids(messages: list[dict]) -> list[str]:
    return [m.get("message_id", "") for m in messages or [] if m.get("message_id")]


def _record_inbound(msg: dict, channel: str, conversation_id: str):
    state_registry.inbound_processing_record(
        msg.get("message_id", ""),
        conversation_id=conversation_id or msg.get("from", ""),
        channel=channel,
        status="received",
    )


def _mark_delivery_failed(channel: str, conversation_id: str, customer_name: str,
                          message_ids: list[str], error: str):
    state_registry.inbound_processing_bulk_update(
        message_ids, "send_failed", reason="provider_send_failed", error=error)
    subject = f"[DELIVERY FAILED] {channel}: {conversation_id}"
    body = (
        "A reply was generated, but the provider send call failed.\n\n"
        f"Channel: {channel}\n"
        f"Conversation/customer: {conversation_id}\n"
        "Action taken: The assistant reply was NOT stored as sent. "
        "Operator must review and reply manually or reconnect the provider.\n"
        f"Error: {error or 'provider returned false'}\n"
        f"Inbound message ids: {', '.join(message_ids) or '(missing)'}"
    )
    try:
        state_registry.create_pending_notification(
            "escalation", channel, conversation_id,
            customer_name or "Unknown", subject, body, mode="hard")
    except Exception as exc:
        log("delivery_failure_escalation_create_failed",
            channel=channel, conversation_id=conversation_id[:20],
            error=str(exc)[:200])


def _maybe_run_cleanup():
    """Run stale data cleanup at most once per hour."""
    global _last_cleanup_ts
    now = time.time()
    stale_failures = state_registry.inbound_processing_mark_stale_failures()
    if stale_failures:
        log("inbound_processing_stale_failures", count=stale_failures)
    if now - _last_cleanup_ts < 3600:
        return
    _last_cleanup_ts = now
    result = state_registry.wa_cleanup_stale_data()
    if result["threads_cleaned"] or result["processed_cleaned"]:
        log("whatsapp_cleanup", **result)


@app.get("/webhooks/meta/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification — returns challenge if token matches."""
    if hub_mode == "subscribe" and hub_verify_token == _VERIFY_TOKEN:
        log("webhook_verified", source="meta_whatsapp")
        return PlainTextResponse(content=hub_challenge, status_code=200)
    log("webhook_verify_failed", source="meta_whatsapp", mode=hub_mode)
    return PlainTextResponse(content="Forbidden", status_code=403)


@app.post("/webhooks/meta/whatsapp")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive WhatsApp webhook events — return 200 immediately, process in background."""
    try:
        payload = await request.json()
    except Exception:
        payload = {"raw": (await request.body()).decode("utf-8", errors="replace")}
    log("webhook_received", source="meta_whatsapp", payload=payload)
    background_tasks.add_task(_process_whatsapp_event, payload)
    return PlainTextResponse(content="OK", status_code=200)


def _process_whatsapp_event(payload: dict):
    """Background task: parse messages, dedup, buffer for debounce."""
    _maybe_run_cleanup()
    try:
        messages = parse_webhook_payload(payload)
        for msg in messages:
            message_id = msg.get("message_id", "")
            # Dedup by message ID
            if not message_id or state_registry.wa_has_been_processed(message_id):
                if message_id:
                    log("webhook_duplicate_skipped", source="meta_whatsapp",
                        message_id=message_id)
                continue
            state_registry.wa_mark_as_processed(message_id)
            _record_inbound(msg, "whatsapp", msg.get("from", ""))
            log("whatsapp_message_normalized", **msg)
            # Only buffer text messages
            if msg.get("text") is None:
                state_registry.inbound_processing_update(
                    message_id, "ignored", reason="non_text_message")
                log("whatsapp_non_text_skipped", source="meta_whatsapp",
                    message_type=msg.get("message_type"), message_id=message_id)
                continue
            ignored = state_registry.match_ignored_contact(
                channel="whatsapp",
                sender_id=msg.get("from", ""),
                phone=msg.get("from", ""),
            )
            if ignored:
                state_registry.record_ignored_contact_event(
                    contact_id=ignored.get("id"),
                    channel="whatsapp",
                    sender_identifier=msg.get("from", ""),
                    message_id=message_id,
                )
                log("ignored_contact_inbound_suppressed",
                    channel="whatsapp",
                    sender=(msg.get("from", "") or "")[:50],
                    message_id=message_id,
                    reason="Ignored inbound message because sender is on Excluded Contacts / Ignore List.")
                state_registry.inbound_processing_update(
                    message_id, "ignored", reason="ignored_contact")
                continue
            _buffer_message(msg)
    except Exception as e:
        log("webhook_process_error", source="meta_whatsapp", error=str(e))


def _buffer_message(msg):
    """Add message to per-phone debounce buffer. Schedule flush after window."""
    phone = msg["from"]
    now = time.time()
    effective_timing = _response_timing_for_message(msg)
    with _buffer_lock:
        if phone not in _message_buffers:
            timing = response_timing.runtime_response_timing(effective_timing)
            _message_buffers[phone] = {
                "messages": [],
                "timer": None,
                "started": now,
                "timing": timing,
            }
        buf = _message_buffers[phone]
        timing = buf.get("timing") or response_timing.runtime_response_timing(effective_timing)
        if timing.get("mode") != "random":
            timing = response_timing.runtime_response_timing(effective_timing)
            buf["timing"] = timing
        buf["messages"].append(msg)
        log("whatsapp_message_buffered", phone=phone,
            buffered_count=len(buf["messages"]),
            batch_delay_seconds=timing["delay_seconds"],
            batch_max_wait_seconds=timing["max_wait_seconds"],
            batch_source=timing.get("source"),
            batch_mode=timing.get("mode"),
            batch_random_picked_seconds=timing.get("random_picked_seconds"))

        # Cancel existing timer
        if buf["timer"] is not None:
            buf["timer"].cancel()

        # Calculate delay: min of debounce window or remaining hard cap
        elapsed = now - buf["started"]
        remaining_cap = max(0.1, float(timing["max_wait_seconds"]) - elapsed)
        delay = min(float(timing["delay_seconds"]), remaining_cap)

        buf["timer"] = threading.Timer(delay, _flush_buffer, args=[phone])
        buf["timer"].daemon = True
        buf["timer"].start()


def _response_timing_for_message(msg: dict) -> dict:
    """Return effective response timing for this message.

    Human takeover and already-blocked conversations should not sit in the
    customer-facing debounce window. They still flow through the same flush
    path so storage/blocked handling remains centralized.
    """
    phone = msg.get("from", "")
    conversation_id = msg.get("_zernio_conversation_id") or phone
    if conversation_id and (
        state_registry.get_blocked(conversation_id)
        or state_registry.get_ai_muted(conversation_id)
    ):
        return {
            "message_batching_enabled": False,
            "preset": "immediate",
            "delay_seconds": 0.1,
            "max_wait_seconds": 0.1,
            "source": "immediate_runtime_state",
        }
    try:
        envelope = icp_overrides.fetch_overrides()
    except Exception:
        envelope = None
    return response_timing.effective_response_timing(envelope)


def _flush_buffer(phone):
    """Flush buffered messages: concatenate texts, process as single message."""
    with _buffer_lock:
        buf = _message_buffers.pop(phone, None)
    if not buf or not buf["messages"]:
        return
    messages = buf["messages"]
    ids = _message_ids(messages)
    state_registry.inbound_processing_bulk_update(
        ids, "processing", reason="batch_flush_started")
    # Concatenate all text messages
    texts = [m["text"] for m in messages if m.get("text")]
    combined_text = "\n".join(texts)
    # Use last message's metadata
    final_msg = messages[-1].copy()
    final_msg["text"] = combined_text
    final_msg["_ali_action_id"] = hashlib.sha256(
        "\x1f".join(ids or [str(final_msg.get("message_id") or "")]).encode("utf-8")
    ).hexdigest()
    batched_count = len(messages)
    timing = buf.get("timing") if isinstance(buf, dict) else {}
    if batched_count > 1:
        log("whatsapp_batch_flushed", phone=phone, count=batched_count,
            combined_length=len(combined_text),
            batch_source=timing.get("source") if isinstance(timing, dict) else None)
    # Brief 161: acquire per-phone lock BEFORE the try block so both Zernio
    # and legacy Meta paths are serialized. Lock key: zernio conv id (if
    # present) or phone. Fixes race where msg 2 starts processing while msg
    # 1 is still mid-flight and overwrites msg 1's state.
    _lock_key = final_msg.get("_zernio_conversation_id") or phone
    _phone_lock = _get_phone_lock(_lock_key)
    with _phone_lock:
        try:
            # Check if this came from Zernio (has _zernio metadata)
            _zernio_conv = final_msg.get("_zernio_conversation_id")
            _zernio_acct = final_msg.get("_zernio_account_id")
            _zernio_channel = final_msg.get("_zernio_channel", "whatsapp")
            _zernio_sender = final_msg.get("_zernio_sender_name", "")
            if _zernio_conv:
                ignored = state_registry.match_ignored_contact(
                    channel=_zernio_channel,
                    sender_id=final_msg.get("from", ""),
                    phone=final_msg.get("from", ""),
                ) or state_registry.match_ignored_contact(
                    channel=_zernio_channel,
                    sender_id=_zernio_conv,
                )
                if ignored:
                    state_registry.record_ignored_contact_event(
                        contact_id=ignored.get("id"),
                        channel=_zernio_channel,
                        sender_identifier=final_msg.get("from", "") or _zernio_conv,
                    )
                    log("ignored_contact_inbound_suppressed",
                        channel=_zernio_channel,
                        sender=(final_msg.get("from", "") or _zernio_conv)[:50],
                        reason="Ignored inbound message because sender is on Excluded Contacts / Ignore List.")
                    state_registry.inbound_processing_bulk_update(
                        ids, "ignored", reason="ignored_contact")
                    return
                # Brief 220: per-conversation runtime block. Drop BEFORE
                # storage so the conversation doesn't appear in the inbox.
                if state_registry.get_blocked(_zernio_conv):
                    log("whatsapp_zernio_blocked_conversation", conversation_id=_zernio_conv[:20])
                    state_registry.inbound_processing_bulk_update(
                        ids, "ignored", reason="blocked_conversation")
                    return  # exits the with _phone_lock block
                # Brief 213: ai_muted check for Zernio WhatsApp (debounce-buffered path).
                if state_registry.get_ai_muted(_zernio_conv):
                    state_registry.dm_store_message(
                        conversation_id=_zernio_conv, channel=_zernio_channel,
                        role="user", text=combined_text, sender_name=_zernio_sender)
                    log("whatsapp_zernio_ai_muted", conversation_id=_zernio_conv[:20])
                    state_registry.inbound_processing_bulk_update(
                        ids, "escalated", reason="human_takeover_ai_muted")
                    return  # exits the with _phone_lock block; _flush_buffer returns
                if not icp_overrides.auto_reply_enabled():
                    state_registry.dm_store_message(
                        conversation_id=_zernio_conv,
                        channel=_zernio_channel,
                        role="user",
                        text=combined_text,
                        sender_name=_zernio_sender,
                    )
                    log("tenant_agent_paused",
                        conversation_id=_zernio_conv[:20],
                        channel=_zernio_channel)
                    state_registry.inbound_processing_bulk_update(
                        ids, "paused", reason="tenant_agent_paused")
                    return
                # Callback-follow-up tenants need the structured WhatsApp
                # agent even though they intentionally disable booking_flow.
                _orchestrator_on = _use_whatsapp_orchestrator(_zernio_channel)
                reply_media = None
                reply_vehicle_recommendation = None
                reply_quote_confirmation = None
                ali_turn_commit = None
                if _orchestrator_on:
                    state_registry.dm_store_message(
                        conversation_id=_zernio_conv,
                        channel=_zernio_channel,
                        role="user",
                        text=combined_text,
                        sender_name=_zernio_sender,
                    )
                    reply_result = handle_incoming_whatsapp_message(
                        final_msg, channel=_zernio_channel,
                        inbound_already_stored=True,
                        include_media=True)
                    reply_media = None
                    if isinstance(reply_result, dict):
                        reply_text = str(reply_result.get("text") or "")
                        reply_media = reply_result.get("media") if isinstance(reply_result.get("media"), dict) else None
                        reply_vehicle_recommendation = (
                            reply_result.get("vehicle_recommendation")
                            if isinstance(reply_result.get("vehicle_recommendation"), dict)
                            else None
                        )
                        reply_quote_confirmation = (
                            reply_result.get("quote_confirmation")
                            if isinstance(reply_result.get("quote_confirmation"), dict)
                            else None
                        )
                        ali_turn_commit = (
                            reply_result.get("ali_turn_commit")
                            if isinstance(reply_result.get("ali_turn_commit"), dict)
                            else None
                        )
                    else:
                        reply_text = reply_result
                else:
                    # Q&A only — use DM agent
                    _dm_msg = {
                        "conversation_id": _zernio_conv,
                        "platform": "whatsapp",
                        "channel": _zernio_channel,
                        "sender_name": _zernio_sender,
                        "text": combined_text,
                        "account_id": _zernio_acct,
                        "message_id": final_msg.get("message_id", ""),
                    }
                    # Store user message before DM agent (same as DM path)
                    state_registry.dm_store_message(
                        conversation_id=_zernio_conv,
                        channel=_zernio_channel,
                        role="user",
                        text=combined_text,
                        sender_name=_zernio_sender,
                    )
                    reply_text = handle_incoming_dm(_dm_msg)
                reply_text = _sanitize_tenant_whatsapp_reply(
                    reply_text, _zernio_channel)
                if reply_text:
                    attachment_url = str((reply_media or {}).get("url") or "")
                    recommendation_delivery = None
                    confirmation_delivery = None
                    if (
                        _zernio_channel == "whatsapp"
                        and reply_vehicle_recommendation
                    ):
                        reply_vehicle_recommendation = dict(
                            reply_vehicle_recommendation
                        )
                        reply_vehicle_recommendation["text"] = reply_text
                        recommendation_delivery = send_dm_vehicle_recommendation(
                            _zernio_conv,
                            _zernio_acct,
                            reply_vehicle_recommendation,
                        )
                        ok = bool(recommendation_delivery.get("success"))
                    elif (
                        _zernio_channel == "whatsapp"
                        and reply_quote_confirmation
                    ):
                        reply_quote_confirmation = dict(
                            reply_quote_confirmation
                        )
                        reply_quote_confirmation["text"] = reply_text
                        reply_quote_confirmation["fallback_text"] = (
                            f"{reply_text.rstrip()}\n\n"
                            f"{QUOTE_CONFIRMATION_FALLBACK_INSTRUCTION}"
                        )
                        confirmation_delivery = send_dm_quote_confirmation(
                            _zernio_conv,
                            _zernio_acct,
                            reply_quote_confirmation,
                        )
                        ok = bool(confirmation_delivery.get("success"))
                    else:
                        ok = send_reply(
                            _zernio_channel,
                            _zernio_conv,
                            _zernio_acct,
                            reply_text,
                            attachment_url=attachment_url,
                            attachment_type="image" if attachment_url else "image",
                            confirm_delivery=bool(ali_turn_commit),
                            idempotency_key=(
                                f"ali-turn-{ali_turn_commit['action_id']}"
                                if ali_turn_commit else ""
                            ),
                        )
                    if not ok:
                        log("zernio_reply_send_failed",
                            channel=_zernio_channel,
                            conversation_id=_zernio_conv[:20],
                            media_attached=bool(attachment_url),
                            vehicle_recommendation=bool(reply_vehicle_recommendation))
                        _mark_delivery_failed(
                            _zernio_channel, _zernio_conv, _zernio_sender,
                            ids, "provider returned false")
                        if reply_quote_confirmation:
                            state_registry.create_pending_notification(
                                "escalation", "whatsapp", _zernio_conv,
                                _zernio_sender or "Ali quote customer",
                                "[ALI QUOTE CONFIRMATION DELIVERY FAILED]",
                                "The rental summary and Send my quote control could not be delivered. Open the conversation in Unboks.",
                                mode="hard",
                            )
                        return
                    if ali_turn_commit:
                        commit_ali_turn_delivery(
                            _zernio_conv,
                            ali_turn_commit,
                            reply_text,
                            ids,
                            channel=_zernio_channel,
                            recommendation_state_hash=str(
                                (reply_vehicle_recommendation or {}).get("state_hash") or ""
                            ),
                            recommendation_delivery=str(
                                (recommendation_delivery or {}).get("delivery") or ""
                            ),
                            recommendation_vehicle_ids=[
                                str(option.get("id") or "")
                                for option in (reply_vehicle_recommendation or {}).get("options") or []
                                if isinstance(option, dict)
                            ],
                            recommendation_provider_message_ids=list(
                                (recommendation_delivery or {}).get("provider_message_ids") or []
                            ),
                            confirmation_delivery=str(
                                (confirmation_delivery or {}).get("delivery") or ""
                            ),
                            confirmation_payload=str(
                                ((reply_quote_confirmation or {}).get("button") or {}).get("payload")
                                or ""
                            ),
                            confirmation_provider_message_ids=list(
                                (confirmation_delivery or {}).get("provider_message_ids") or []
                            ),
                        )
                    else:
                        state_registry.dm_store_message(
                            conversation_id=_zernio_conv,
                            channel=_zernio_channel,
                            role="assistant",
                            text=reply_text,
                        )
                    if recommendation_delivery:
                        delivery = str(
                            recommendation_delivery.get("delivery") or ""
                        )
                        state_hash = str(
                            reply_vehicle_recommendation.get("state_hash") or ""
                        )
                        if not ali_turn_commit:
                            state_registry.wa_mark_vehicle_recommendation_delivered(
                                _zernio_conv,
                                state_hash,
                                delivery,
                                [
                                    str(option.get("id") or "")
                                    for option in reply_vehicle_recommendation.get("options") or []
                                    if isinstance(option, dict)
                                ],
                            )
                        state_registry.dm_store_message(
                            conversation_id=_zernio_conv,
                            channel=_zernio_channel,
                            role="system",
                            text=(
                                "Ali vehicle recommendation sent: "
                                f"{delivery}; {len(reply_vehicle_recommendation.get('options') or [])} option(s)"
                            ),
                        )
                    if attachment_url:
                        state_registry.increment_photo_used_count(int(reply_media["id"]))
                        state_registry.dm_store_message(
                            conversation_id=_zernio_conv,
                            channel=_zernio_channel,
                            role="system",
                            text=f"Image sent: {reply_media.get('caption') or reply_media.get('filename')}",
                        )
                    if not ali_turn_commit:
                        state_registry.inbound_processing_bulk_update(
                            ids, "replied", reason="provider_send_ok")
                else:
                    state_registry.inbound_processing_bulk_update(
                        ids, "ignored", reason="no_reply_returned")
            else:
                # Brief 220: per-conversation runtime block (Meta-legacy WhatsApp path).
                if state_registry.get_blocked(phone):
                    log("whatsapp_meta_blocked_conversation", phone=phone[:20])
                    state_registry.inbound_processing_bulk_update(
                        ids, "ignored", reason="blocked_conversation")
                    return
                # Brief 213: ai_muted check for Meta legacy WhatsApp.
                if state_registry.get_ai_muted(phone):
                    state_registry.wa_store_message(phone, "user", combined_text)
                    log("whatsapp_meta_ai_muted", phone=phone[:20])
                    state_registry.inbound_processing_bulk_update(
                        ids, "escalated", reason="human_takeover_ai_muted")
                    return  # exits the with _phone_lock block; _flush_buffer returns
                if not icp_overrides.auto_reply_enabled():
                    state_registry.wa_store_message(phone, "user", combined_text)
                    log("tenant_agent_paused", phone=phone[:20], channel="whatsapp")
                    state_registry.inbound_processing_bulk_update(
                        ids, "paused", reason="tenant_agent_paused")
                    return
                # Meta WhatsApp (legacy) — original path
                state_registry.wa_store_message(phone, "user", combined_text)
                reply_result = handle_incoming_whatsapp_message(
                    final_msg, inbound_already_stored=True)
                ali_turn_commit = None
                if isinstance(reply_result, dict):
                    reply_text = str(reply_result.get("text") or "")
                    ali_turn_commit = (
                        reply_result.get("ali_turn_commit")
                        if isinstance(reply_result.get("ali_turn_commit"), dict)
                        else None
                    )
                else:
                    reply_text = reply_result
                reply_text = _sanitize_tenant_whatsapp_reply(
                    reply_text, "whatsapp")
                if reply_text:
                    ok = send_text_message(to=phone, text=reply_text)
                    if not ok:
                        _mark_delivery_failed(
                            "whatsapp", phone, final_msg.get("from_name", ""),
                            ids, "provider returned false")
                        return
                    if ali_turn_commit:
                        commit_ali_turn_delivery(
                            phone, ali_turn_commit, reply_text, ids,
                            channel="whatsapp",
                        )
                    else:
                        state_registry.wa_store_message(phone, "assistant", reply_text)
                        state_registry.inbound_processing_bulk_update(
                            ids, "replied", reason="provider_send_ok")
                else:
                    state_registry.inbound_processing_bulk_update(
                        ids, "ignored", reason="no_reply_returned")
        except Exception as e:
            state_registry.inbound_processing_bulk_update(
                ids, "processing_failed", reason="exception", error=str(e))
            log("webhook_process_error",
                source="zernio_whatsapp" if final_msg.get("_zernio_conversation_id") else "meta_whatsapp",
                error=str(e), phone=phone)


@app.post("/webhooks/zernio")
async def receive_zernio_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive Zernio webhook events (DMs from IG/FB). Return 200 immediately."""
    body = await request.body()
    signature = request.headers.get("X-Zernio-Signature", "")

    if not verify_webhook_signature(body, signature):
        log("zernio_webhook_signature_invalid")
        return PlainTextResponse(content="Forbidden", status_code=403)

    try:
        payload = _json.loads(body)
    except Exception:
        payload = {"raw": body.decode("utf-8", errors="replace")}
    log("webhook_received", source="zernio", webhook_event=payload.get("event", "unknown"))
    background_tasks.add_task(_process_zernio_event, payload)
    return PlainTextResponse(content="OK", status_code=200)


def _normalize_phone_digits(phone: str) -> str:
    """Brief 208: collapse a phone-like string to ASCII digits only.
    Strips Unicode digits (fullwidth ５９９ etc.), separators, plus signs,
    and the 'ext'/'x'/'#' suffix that some clients add for extensions."""
    if not phone:
        return ""
    s = str(phone)
    # Strip extension suffix and everything after it
    for marker in (" ext ", " x ", "#"):
        idx = s.lower().find(marker)
        if idx >= 0:
            s = s[:idx]
            break
    import re
    return re.sub(r"[^0-9]", "", s)


def _external_operator_message_text(msg: dict) -> str:
    """Return visible text for a phone-app message, including media-only sends."""
    text = str(msg.get("text") or "").strip()
    labels = {
        "image": "📷 Imagen enviada desde WhatsApp",
        "video": "🎥 Vídeo enviado desde WhatsApp",
        "audio": "🎤 Audio enviado desde WhatsApp",
        "voice": "🎤 Nota de voz enviada desde WhatsApp",
        "document": "📎 Documento enviado desde WhatsApp",
        "file": "📎 Archivo enviado desde WhatsApp",
        "sticker": "Sticker enviado desde WhatsApp",
        "location": "📍 Ubicación enviada desde WhatsApp",
        "contact": "👤 Contacto enviado desde WhatsApp",
    }
    media_lines = []
    for attachment in msg.get("attachments") or []:
        if not isinstance(attachment, dict):
            continue
        attachment_type = str(attachment.get("type") or "").lower()
        label = labels.get(attachment_type, "📎 Archivo enviado desde WhatsApp")
        filename = str(attachment.get("filename") or "").strip()
        media_lines.append(f"{label}: {filename}" if filename else label)
    if text and media_lines:
        return text + "\n" + "\n".join(media_lines)
    return text or "\n".join(media_lines)


def _process_zernio_sent_event(payload: dict) -> None:
    """Mirror a secretary reply from the WhatsApp Business app into Unboks.

    Cloud-API echoes are intentionally ignored because Unboks already stores
    its own sent messages. The outgoing event is never passed to Alia.
    """
    msg = parse_zernio_sent_webhook(payload)
    if not msg:
        return
    if (
        msg.get("platform") != "whatsapp"
        or msg.get("direction") != "outgoing"
        or msg.get("source") != "whatsappbusinessapp"
    ):
        log(
            "zernio_sent_event_ignored",
            platform=msg.get("platform", ""),
            direction=msg.get("direction", ""),
            source=msg.get("source", ""),
        )
        return

    from shared.tenant_guard import is_account_allowed
    if not is_account_allowed(msg.get("account_id", ""), direction="inbound"):
        log(
            "zernio_sent_event_account_not_allowlisted",
            account_id=msg.get("account_id", "")[:20],
        )
        return

    visible_text = _external_operator_message_text(msg)
    if not visible_text:
        log(
            "zernio_sent_event_empty",
            conversation_id=msg.get("conversation_id", "")[:20],
            message_id=msg.get("message_id", "")[:30],
        )
        return

    stored = state_registry.wa_store_external_operator_message(
        message_id=msg["message_id"],
        conversation_id=msg["conversation_id"],
        channel=msg.get("channel") or "whatsapp",
        text=visible_text,
        sender_name="Secretaría",
        created_at=msg.get("created_at") or "",
    )
    if not stored:
        log(
            "zernio_sent_event_duplicate",
            conversation_id=msg["conversation_id"][:20],
            message_id=msg["message_id"][:30],
        )
        return

    # A fresh human reply should make an archived thread visible again without
    # overwriting an existing escalation or takeover status.
    state_registry.wa_set_archived(msg["conversation_id"], False)
    log(
        "zernio_whatsapp_app_reply_synced",
        conversation_id=msg["conversation_id"][:20],
        message_id=msg["message_id"][:30],
        sender_name="Secretaría",
    )


def _process_zernio_event(payload: dict):
    """Background task: parse Zernio webhook, dedup, route DM to booking or Q&A."""
    try:
        if payload.get("event") == "message.failed":
            failed = parse_zernio_failed_webhook(payload)
            if failed:
                reconciled = state_registry.wa_reconcile_vehicle_recommendation_failure(
                    failed["conversation_id"], failed["message_id"],
                )
                confirmation_failure = reconcile_quote_confirmation_failure(
                    failed["conversation_id"], failed["message_id"],
                )
                fallback_attempted = False
                fallback_sent = False
                workflow = (config_loader.get_raw() or {}).get("workflow") or {}
                if (
                    workflow.get("type") == "ali_quote"
                    and reconciled
                    and failed.get("recoverable_media")
                    and failed.get("account_id")
                    and failed.get("text")
                ):
                    fallback_attempted = True
                    fallback_key = hashlib.sha256(
                        str(failed["message_id"]).encode("utf-8")
                    ).hexdigest()
                    try:
                        fallback_sent = send_reply(
                            "whatsapp",
                            failed["conversation_id"],
                            failed["account_id"],
                            failed["text"],
                            confirm_delivery=True,
                            idempotency_key=f"ali-late-media-fallback-{fallback_key}",
                        )
                    except Exception as exc:
                        log(
                            "zernio_failed_media_fallback_error",
                            conversation_id=failed["conversation_id"][:20],
                            error=type(exc).__name__,
                        )
                    log(
                        "zernio_failed_media_fallback_sent"
                        if fallback_sent
                        else "zernio_failed_media_fallback_failed",
                        conversation_id=failed["conversation_id"][:20],
                        message_id=failed["message_id"][:30],
                    )
                confirmation_recovery_attempted = False
                confirmation_recovery_sent = False
                if (
                    workflow.get("type") == "ali_quote"
                    and confirmation_failure
                    and confirmation_failure.get("matched")
                    and not confirmation_failure.get("already_recovered")
                    and failed.get("account_id")
                ):
                    confirmation_recovery_attempted = True
                    source_text = str(failed.get("text") or "").strip()
                    if not source_text:
                        history = state_registry.wa_get_full_history(
                            failed["conversation_id"], limit=20,
                        )
                        source_text = next(
                            (
                                str(item.get("text") or "").strip()
                                for item in reversed(history)
                                if item.get("role") == "assistant"
                                and str(item.get("text") or "").strip()
                            ),
                            "",
                        )
                    recovery_text = source_text
                    if QUOTE_CONFIRMATION_FALLBACK_INSTRUCTION not in recovery_text:
                        recovery_text = (
                            f"{source_text}\n\n{QUOTE_CONFIRMATION_FALLBACK_INSTRUCTION}"
                            if source_text
                            else QUOTE_CONFIRMATION_FALLBACK_INSTRUCTION
                        )
                    fallback_key = hashlib.sha256(
                        str(failed["message_id"]).encode("utf-8")
                    ).hexdigest()
                    try:
                        confirmation_recovery_sent = send_reply(
                            "whatsapp",
                            failed["conversation_id"],
                            failed["account_id"],
                            recovery_text,
                            confirm_delivery=True,
                            idempotency_key=(
                                f"ali-late-confirmation-fallback-{fallback_key}"
                            ),
                        )
                    except Exception as exc:
                        log(
                            "ali_quote_confirmation_late_fallback_error",
                            conversation_id=failed["conversation_id"][:20],
                            error=type(exc).__name__,
                        )
                    if confirmation_recovery_sent:
                        mark_quote_confirmation_failure_recovered(
                            failed["conversation_id"], failed["message_id"],
                        )
                    else:
                        state_registry.create_pending_notification(
                            "escalation",
                            "whatsapp",
                            failed["conversation_id"],
                            "Ali quote customer",
                            "[ALI QUOTE CONFIRMATION DELIVERY FAILED]",
                            "The Send my quote control failed and its text fallback could not be delivered. Open the conversation in Unboks.",
                            mode="hard",
                        )
                    log(
                        "ali_quote_confirmation_late_fallback_sent"
                        if confirmation_recovery_sent
                        else "ali_quote_confirmation_late_fallback_failed",
                        conversation_id=failed["conversation_id"][:20],
                        message_id=failed["message_id"][:30],
                    )
                log(
                    "zernio_failed_event_reconciled",
                    conversation_id=failed["conversation_id"][:20],
                    message_id=failed["message_id"][:30],
                    vehicle_recommendation=reconciled,
                    fallback_attempted=fallback_attempted,
                    fallback_sent=fallback_sent,
                    quote_confirmation=bool(confirmation_failure),
                    confirmation_recovery_attempted=confirmation_recovery_attempted,
                    confirmation_recovery_sent=confirmation_recovery_sent,
                    failure_reason=str(failed.get("failure_reason") or "")[:120],
                )
            return
        if payload.get("event") == "message.sent":
            _process_zernio_sent_event(payload)
            return

        msg = parse_zernio_webhook(payload)
        if not msg:
            return  # Not a message event or unparseable

        message_id = msg["message_id"]
        # Reuse whatsapp_processed table for dedup
        if state_registry.wa_has_been_processed(message_id):
            log("webhook_duplicate_skipped", source="zernio", message_id=message_id)
            return
        state_registry.wa_mark_as_processed(message_id)
        _record_inbound(msg, msg.get("channel", ""), msg.get("conversation_id", ""))

        ignored = state_registry.match_ignored_contact(
            channel=msg.get("channel", ""),
            sender_id=msg.get("sender_id", ""),
            phone=msg.get("sender_id", ""),
        ) or state_registry.match_ignored_contact(
            channel=msg.get("channel", ""),
            sender_id=msg.get("conversation_id", ""),
        )
        if ignored:
            state_registry.record_ignored_contact_event(
                contact_id=ignored.get("id"),
                channel=msg.get("channel", ""),
                sender_identifier=msg.get("sender_id") or msg.get("conversation_id", ""),
                message_id=message_id,
            )
            log("ignored_contact_inbound_suppressed",
                channel=msg.get("channel", ""),
                sender=(msg.get("sender_id") or msg.get("conversation_id") or "")[:50],
                message_id=message_id,
                reason="Ignored inbound message because sender is on Excluded Contacts / Ignore List.")
            state_registry.inbound_processing_update(
                message_id, "ignored", reason="ignored_contact")
            return

        # Brief 208: per-tenant ignored_phones list. Drop messages from
        # configured numbers BEFORE any reply-generation path runs.
        _ignored = config_loader.get_raw().get("features", {}).get("ignored_phones", [])
        if _ignored:
            sender_digits = _normalize_phone_digits(msg.get("sender_id", ""))
            for ignored in _ignored:
                if sender_digits and sender_digits == _normalize_phone_digits(str(ignored)):
                    log("zernio_dm_ignored_phone",
                        sender=sender_digits,
                        message_id=message_id)
                    state_registry.inbound_processing_update(
                        message_id, "ignored", reason="ignored_phone")
                    return

        # Brief 220: per-conversation runtime block. Mirrors ignored_phones
        # (which runs above, statically configured) but works on a
        # dashboard-controlled per-conversation_id flag. Drop BEFORE any
        # storage so the conversation doesn't appear in the inbox.
        if state_registry.get_blocked(msg.get("conversation_id", "")):
            log("zernio_dm_blocked_conversation",
                conversation_id=msg.get("conversation_id", "")[:20],
                message_id=message_id)
            state_registry.inbound_processing_update(
                message_id, "ignored", reason="blocked_conversation")
            return

        # Brief 238 — tenant isolation: refuse webhooks for accounts not
        # allowlisted in this tenant's client.json. Strict mode aborts here;
        # permissive mode just logs and keeps going.
        from shared.tenant_guard import is_account_allowed
        if not is_account_allowed(msg.get("account_id", ""), direction="inbound"):
            state_registry.inbound_processing_update(
                message_id, "processing_failed",
                reason="account_not_allowlisted")
            return

        # Brief 240: auto-resolve operator WhatsApp alert route. If this
        # inbound is from the configured operator phone (whatsapp_destination
        # in alert_settings), persist the Zernio conversation_id + account_id
        # so the alert dispatcher can deliver future operator alerts via
        # Zernio (not Meta). WhatsApp-only - DMing the IG/FB account does
        # not bootstrap a WA alert route. Best-effort: never blocks the
        # inbound event from being processed normally.
        if msg.get("platform") == "whatsapp":
            try:
                _alert_settings = state_registry.get_alert_settings(
                    default_email_destination="")
                _wa_dest = (((_alert_settings or {}).get("channels") or {})
                            .get("whatsapp") or {}).get("destination") or ""
                if _wa_dest:
                    _sender_digits = _normalize_phone_digits(
                        msg.get("sender_id", ""))
                    _dest_digits = _normalize_phone_digits(_wa_dest)
                    if _sender_digits and _sender_digits == _dest_digits:
                        state_registry.set_resolved_operator_whatsapp_route(
                            msg.get("conversation_id", ""),
                            msg.get("account_id", ""))
                        log("operator_whatsapp_route_resolved",
                            sender_digits=_sender_digits,
                            conversation_id=msg.get("conversation_id", "")[:20],
                            account_id=msg.get("account_id", "")[:20])
            except Exception as _e:
                log("operator_whatsapp_route_resolve_failed",
                    error=str(_e)[:200])

        text = msg.get("text", "")
        has_whatsapp_interactive_reply = bool(
            msg.get("platform") == "whatsapp"
            and str(msg.get("interactive_id") or "").strip()
        )
        if not text and not has_whatsapp_interactive_reply:
            state_registry.inbound_processing_update(
                message_id, "ignored", reason="non_text_message")
            log("zernio_dm_non_text_skipped", message_id=message_id,
                platform=msg.get("platform"))
            return

        log("zernio_dm_received",
            conversation_id=msg["conversation_id"][:20],
            platform=msg["platform"],
            sender=msg["sender_name"][:30])

        conversation_id = msg["conversation_id"]
        channel = msg["channel"]
        account_id = msg["account_id"]

        # WhatsApp via Zernio: debounce like Meta WhatsApp
        if msg["platform"] == "whatsapp":
            adapter_cls = ZERNIO_CHANNELS.get(channel, DEFAULT_ZERNIO_CHANNEL)
            _wa_msg = adapter_cls.from_zernio(msg)
            send_typing_indicator(conversation_id, account_id)
            _buffer_message(_wa_msg)
            return

        # Send typing indicator (best-effort) — outside the critical section
        send_typing_indicator(conversation_id, account_id)

        # Brief 161: per-phone lock serializes the IG/FB DM path the same way
        # the WhatsApp debounce path is serialized. Required so concurrent
        # Zernio webhooks for the same conversation cannot race on state.
        _dm_lock = _get_phone_lock(conversation_id)
        with _dm_lock:
            # Brief 213: respect ai_muted (operator-takeover state). When a
            # conversation has been muted via /escalations/:id/takeover,
            # store the inbound in the dashboard thread so the operator
            # sees it, but do NOT call the reply handler.
            if state_registry.get_ai_muted(conversation_id):
                state_registry.dm_store_message(
                    conversation_id=conversation_id, channel=channel,
                    role="user", text=text, sender_name=msg["sender_name"])
                log("zernio_dm_ai_muted",
                    conversation_id=conversation_id[:20], channel=channel)
                state_registry.inbound_processing_update(
                    message_id, "escalated", reason="human_takeover_ai_muted")
                return

            if not icp_overrides.auto_reply_enabled():
                state_registry.dm_store_message(
                    conversation_id=conversation_id,
                    channel=channel,
                    role="user",
                    text=text,
                    sender_name=msg["sender_name"],
                )
                log("tenant_agent_paused",
                    conversation_id=conversation_id[:20], channel=channel)
                state_registry.inbound_processing_update(
                    message_id, "paused", reason="tenant_agent_paused")
                return

            # Callback-follow-up tenants need the structured WhatsApp agent
            # even though they intentionally disable booking_flow.
            _orchestrator_on = _use_whatsapp_orchestrator(channel)

            if _orchestrator_on:
                # Full booking flow — route through orchestrator
                # Persist before model/order work so crashes remain visible.
                # handle_incoming_whatsapp_message removes this exact inbound
                # from prompt history when inbound_already_stored=True.
                adapter_cls = ZERNIO_CHANNELS.get(channel, DEFAULT_ZERNIO_CHANNEL)
                orchestrator_msg = adapter_cls.from_zernio(msg)
                state_registry.dm_store_message(
                    conversation_id=conversation_id,
                    channel=channel,
                    role="user",
                    text=text,
                    sender_name=msg["sender_name"],
                )
                reply_result = handle_incoming_whatsapp_message(
                    orchestrator_msg, channel=channel,
                    inbound_already_stored=True,
                    include_media=True)
                reply_media = None
                if isinstance(reply_result, dict):
                    reply_text = str(reply_result.get("text") or "")
                    reply_media = reply_result.get("media") if isinstance(reply_result.get("media"), dict) else None
                else:
                    reply_text = reply_result
            else:
                # Q&A only — use DM agent
                # DM agent reads dm_get_history which is separate, so store before is fine
                state_registry.dm_store_message(
                    conversation_id=conversation_id,
                    channel=channel,
                    role="user",
                    text=text,
                    sender_name=msg["sender_name"],
                )
                reply_text = handle_incoming_dm(msg)
                reply_media = None

            reply_text = _sanitize_tenant_whatsapp_reply(reply_text, channel)
            if reply_text:
                attachment_url = str((reply_media or {}).get("url") or "")
                # Send reply via the sender registry (Brief 187 — dispatched by channel)
                ok = send_reply(
                    channel,
                    conversation_id,
                    account_id,
                    reply_text,
                    attachment_url=attachment_url,
                    attachment_type="image" if attachment_url else "image",
                )
                if not ok:
                    log("zernio_reply_send_failed",
                        channel=channel,
                        conversation_id=conversation_id[:20],
                        media_attached=bool(attachment_url))
                    _mark_delivery_failed(
                        channel, conversation_id, msg.get("sender_name", ""),
                        [message_id], "provider returned false")
                    return
                # Store assistant reply
                state_registry.dm_store_message(
                    conversation_id=conversation_id,
                    channel=channel,
                    role="assistant",
                    text=reply_text,
                )
                if attachment_url:
                    state_registry.increment_photo_used_count(int(reply_media["id"]))
                    state_registry.dm_store_message(
                        conversation_id=conversation_id,
                        channel=channel,
                        role="system",
                        text=f"Image sent: {reply_media.get('caption') or reply_media.get('filename')}",
                    )
                state_registry.inbound_processing_update(
                    message_id, "replied", reason="provider_send_ok")
            else:
                state_registry.inbound_processing_update(
                    message_id, "ignored", reason="no_reply_returned")
    except Exception as e:
        try:
            if "message_id" in locals():
                state_registry.inbound_processing_update(
                    message_id, "processing_failed",
                    reason="exception", error=str(e))
        except Exception:
            pass
        log("webhook_process_error", source="zernio", error=str(e))


@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    """Health check for monitoring. Supports HEAD for UptimeRobot."""
    return {"status": "ok"}
