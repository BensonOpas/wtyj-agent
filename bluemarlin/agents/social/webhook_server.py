# bluemarlin/agents/social/webhook_server.py
# Created: Brief 067
# Last modified: Brief 067
# Purpose: FastAPI webhook receiver for Meta WhatsApp Cloud API

import os
from fastapi import FastAPI, Request, Response, Query
from fastapi.responses import PlainTextResponse

from shared.bm_logger import log

app = FastAPI(title="BlueMarlin Social Webhook", docs_url=None, redoc_url=None)

_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")


@app.get("/webhooks/meta/whatsapp")
async def verify_webhook(
    response: Response,
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
async def receive_webhook(request: Request):
    """Receive WhatsApp webhook events — log payload, return 200 immediately."""
    try:
        payload = await request.json()
    except Exception:
        payload = {"raw": (await request.body()).decode("utf-8", errors="replace")}
    log("webhook_received", source="meta_whatsapp", payload=payload)
    return PlainTextResponse(content="OK", status_code=200)


@app.get("/health")
async def health():
    """Health check for monitoring."""
    return {"status": "ok"}
