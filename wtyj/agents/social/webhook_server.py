# bluemarlin/agents/social/webhook_server.py
# Created: Brief 067
# Last modified: Brief 138
# Purpose: FastAPI webhook receiver for Meta WhatsApp Cloud API

import json as _json
import os
import time
import threading
from fastapi import BackgroundTasks, FastAPI, Request, Query
from fastapi.responses import PlainTextResponse

from shared.bm_logger import log
from shared import state_registry
from shared import config_loader
from agents.social.whatsapp_client import parse_webhook_payload, send_text_message
from agents.social.social_agent import handle_incoming_whatsapp_message
from agents.social.zernio_dm_client import parse_zernio_webhook, verify_webhook_signature, send_dm_reply, send_typing_indicator
from agents.social.dm_agent import handle_incoming_dm
from agents.social.channels import ZERNIO_CHANNELS, DEFAULT_ZERNIO_CHANNEL
from agents.social.senders import send_reply

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    # Brief 190: content pipeline archived — scheduler only starts when explicitly enabled
    if config_loader.get_raw().get("features", {}).get("content_pipeline", False):
        from agents.social.scheduler import start_scheduler
        start_scheduler()
    yield

app = FastAPI(title="WTYJ Agent", docs_url=None, redoc_url=None, lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "https://api.wetakeyourjob.com", "https://wetakeyourjob.com", "https://wtyj-dashboard.replit.app", "https://unboks.org"],
    allow_origin_regex=r"https://.*\.(replit\.(dev|app)|wetakeyourjob\.com|unboks\.org)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from dashboard.api import router as dashboard_router
app.include_router(dashboard_router)

# Brief 207: Tasks API mounted at root level (/tasks/*) so SR's frontend's
# /api/unboks/tasks calls (after nginx prefix-strip → /tasks) hit it directly.
from dashboard.tasks_api import router as tasks_router
app.include_router(tasks_router)

_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
_last_cleanup_ts = 0

# Brief 161: _DEBOUNCE_SECONDS coalesces rapid customer messages into a single
# Claude call. It does NOT protect against concurrent orchestrator access —
# that's what the per-phone lock below is for. Two different problems.
_DEBOUNCE_SECONDS = 2.0
_MAX_BATCH_SECONDS = 5.0

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


def _maybe_run_cleanup():
    """Run stale data cleanup at most once per hour."""
    global _last_cleanup_ts
    now = time.time()
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
            log("whatsapp_message_normalized", **msg)
            # Only buffer text messages
            if msg.get("text") is None:
                log("whatsapp_non_text_skipped", source="meta_whatsapp",
                    message_type=msg.get("message_type"), message_id=message_id)
                continue
            _buffer_message(msg)
    except Exception as e:
        log("webhook_process_error", source="meta_whatsapp", error=str(e))


def _buffer_message(msg):
    """Add message to per-phone debounce buffer. Schedule flush after window."""
    phone = msg["from"]
    now = time.time()
    with _buffer_lock:
        if phone not in _message_buffers:
            _message_buffers[phone] = {
                "messages": [],
                "timer": None,
                "started": now,
            }
        buf = _message_buffers[phone]
        buf["messages"].append(msg)
        log("whatsapp_message_buffered", phone=phone,
            buffered_count=len(buf["messages"]))

        # Cancel existing timer
        if buf["timer"] is not None:
            buf["timer"].cancel()

        # Calculate delay: min of debounce window or remaining hard cap
        elapsed = now - buf["started"]
        remaining_cap = max(0.1, _MAX_BATCH_SECONDS - elapsed)
        delay = min(_DEBOUNCE_SECONDS, remaining_cap)

        buf["timer"] = threading.Timer(delay, _flush_buffer, args=[phone])
        buf["timer"].daemon = True
        buf["timer"].start()


def _flush_buffer(phone):
    """Flush buffered messages: concatenate texts, process as single message."""
    with _buffer_lock:
        buf = _message_buffers.pop(phone, None)
    if not buf or not buf["messages"]:
        return
    messages = buf["messages"]
    # Concatenate all text messages
    texts = [m["text"] for m in messages if m.get("text")]
    combined_text = "\n".join(texts)
    # Use last message's metadata
    final_msg = messages[-1].copy()
    final_msg["text"] = combined_text
    batched_count = len(messages)
    if batched_count > 1:
        log("whatsapp_batch_flushed", phone=phone, count=batched_count,
            combined_length=len(combined_text))
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
                # Brief 213: ai_muted check for Zernio WhatsApp (debounce-buffered path).
                if state_registry.get_ai_muted(_zernio_conv):
                    state_registry.dm_store_message(
                        conversation_id=_zernio_conv, channel=_zernio_channel,
                        role="user", text=combined_text, sender_name=_zernio_sender)
                    log("whatsapp_zernio_ai_muted", conversation_id=_zernio_conv[:20])
                    return  # exits the with _phone_lock block; _flush_buffer returns
                # Zernio WhatsApp — check booking_flow toggle
                _booking_flow_on = config_loader.get_raw().get("features", {}).get("booking_flow", True)
                if _booking_flow_on:
                    reply_text = handle_incoming_whatsapp_message(final_msg, channel=_zernio_channel)
                    # Store user message after orchestrator (same ordering as DM path)
                    state_registry.dm_store_message(
                        conversation_id=_zernio_conv,
                        channel=_zernio_channel,
                        role="user",
                        text=combined_text,
                        sender_name=_zernio_sender,
                    )
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
                if reply_text:
                    send_reply(_zernio_channel, _zernio_conv, _zernio_acct, reply_text)
                    state_registry.dm_store_message(
                        conversation_id=_zernio_conv,
                        channel=_zernio_channel,
                        role="assistant",
                        text=reply_text,
                    )
            else:
                # Brief 213: ai_muted check for Meta legacy WhatsApp.
                if state_registry.get_ai_muted(phone):
                    state_registry.wa_store_message(phone, "user", combined_text)
                    log("whatsapp_meta_ai_muted", phone=phone[:20])
                    return  # exits the with _phone_lock block; _flush_buffer returns
                # Meta WhatsApp (legacy) — original path
                reply_text = handle_incoming_whatsapp_message(final_msg)
                state_registry.wa_store_message(phone, "user", combined_text)
                if reply_text:
                    send_text_message(to=phone, text=reply_text)
                    state_registry.wa_store_message(phone, "assistant", reply_text)
        except Exception as e:
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


def _process_zernio_event(payload: dict):
    """Background task: parse Zernio webhook, dedup, route DM to booking or Q&A."""
    try:
        msg = parse_zernio_webhook(payload)
        if not msg:
            return  # Not a message event or unparseable

        message_id = msg["message_id"]
        # Reuse whatsapp_processed table for dedup
        if state_registry.wa_has_been_processed(message_id):
            log("webhook_duplicate_skipped", source="zernio", message_id=message_id)
            return
        state_registry.wa_mark_as_processed(message_id)

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
                    return

        text = msg.get("text", "")
        if not text:
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
                return

            # Route based on booking_flow toggle
            _booking_flow_on = config_loader.get_raw().get("features", {}).get("booking_flow", True)

            if _booking_flow_on:
                # Full booking flow — route through orchestrator
                # NOTE: store user message AFTER orchestrator call, not before.
                # The orchestrator reads wa_get_history(conversation_id) internally.
                # If we store before, Marina sees the message twice (once in history,
                # once as the current inbound). This matches the WhatsApp _flush_buffer
                # pattern which also stores after the call.
                adapter_cls = ZERNIO_CHANNELS.get(channel, DEFAULT_ZERNIO_CHANNEL)
                orchestrator_msg = adapter_cls.from_zernio(msg)
                reply_text = handle_incoming_whatsapp_message(orchestrator_msg, channel=channel)
                # Store user message after orchestrator (same as WhatsApp path)
                state_registry.dm_store_message(
                    conversation_id=conversation_id,
                    channel=channel,
                    role="user",
                    text=text,
                    sender_name=msg["sender_name"],
                )
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

            if reply_text:
                # Send reply via the sender registry (Brief 187 — dispatched by channel)
                send_reply(channel, conversation_id, account_id, reply_text)
                # Store assistant reply
                state_registry.dm_store_message(
                    conversation_id=conversation_id,
                    channel=channel,
                    role="assistant",
                    text=reply_text,
                )
    except Exception as e:
        log("webhook_process_error", source="zernio", error=str(e))


@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    """Health check for monitoring. Supports HEAD for UptimeRobot."""
    return {"status": "ok"}
