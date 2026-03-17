# bluemarlin/agents/social/webhook_server.py
# Created: Brief 067
# Last modified: Brief 099
# Purpose: FastAPI webhook receiver for Meta WhatsApp Cloud API

import os
import time
import threading
from fastapi import BackgroundTasks, FastAPI, Request, Query
from fastapi.responses import PlainTextResponse

from shared.bm_logger import log
from shared import state_registry
from agents.social.whatsapp_client import parse_webhook_payload, send_text_message
from agents.social.social_agent import handle_incoming_whatsapp_message

app = FastAPI(title="BlueMarlin Social Webhook", docs_url=None, redoc_url=None)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "https://api.wetakeyourjob.com", "https://bluemarlindashboard.replit.app"],
    allow_origin_regex=r"https://.*\.replit\.dev$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from dashboard.api import router as dashboard_router
app.include_router(dashboard_router)

_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
_last_cleanup_ts = 0

_DEBOUNCE_SECONDS = 2.0
_MAX_BATCH_SECONDS = 5.0

_message_buffers = {}   # phone -> {"messages": [...], "timer": Timer, "started": float}
_buffer_lock = threading.Lock()


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
    try:
        reply_text = handle_incoming_whatsapp_message(final_msg)
        # Always store user message — even if reply is empty, context must be preserved
        state_registry.wa_store_message(phone, "user", combined_text)
        if reply_text:
            send_text_message(to=phone, text=reply_text)
            state_registry.wa_store_message(phone, "assistant", reply_text)
    except Exception as e:
        log("webhook_process_error", source="meta_whatsapp", error=str(e),
            phone=phone)


@app.get("/health")
async def health():
    """Health check for monitoring."""
    return {"status": "ok"}
