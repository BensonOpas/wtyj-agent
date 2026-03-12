# bluemarlin/agents/social/webhook_server.py
# Created: Brief 067
# Last modified: Brief 073
# Purpose: FastAPI webhook receiver for Meta WhatsApp Cloud API

import os
import time
from fastapi import BackgroundTasks, FastAPI, Request, Query
from fastapi.responses import PlainTextResponse

from shared.bm_logger import log
from shared import state_registry
from agents.social.whatsapp_client import parse_webhook_payload, send_text_message
from agents.social.social_agent import handle_incoming_whatsapp_message

app = FastAPI(title="BlueMarlin Social Webhook", docs_url=None, redoc_url=None)

_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
_last_cleanup_ts = 0


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
    """Background task: parse messages, dedup, call agent, send reply."""
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
            # Only process text messages
            if msg.get("text") is None:
                log("whatsapp_non_text_skipped", source="meta_whatsapp",
                    message_type=msg.get("message_type"), message_id=message_id)
                continue
            # Agent generates reply (reads history + state internally)
            reply_text = handle_incoming_whatsapp_message(msg)
            if reply_text:
                state_registry.wa_store_message(msg["from"], "user", msg["text"])
                send_text_message(to=msg["from"], text=reply_text)
                state_registry.wa_store_message(msg["from"], "assistant", reply_text)
    except Exception as e:
        log("webhook_process_error", source="meta_whatsapp", error=str(e))


@app.get("/health")
async def health():
    """Health check for monitoring."""
    return {"status": "ok"}
