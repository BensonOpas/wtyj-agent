# bluemarlin/tests/social/test_067_webhook.py
# Created: Brief 067
# Purpose: Tests for WhatsApp webhook server

import os
import sys
import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

os.environ["WHATSAPP_VERIFY_TOKEN"] = "test_token_067"

from fastapi.testclient import TestClient
from agents.social.webhook_server import app

client = TestClient(app)


def test_verify_valid_token():
    """GET with correct token returns 200 + challenge."""
    r = client.get("/webhooks/meta/whatsapp", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "test_token_067",
        "hub.challenge": "challenge_abc123",
    })
    assert r.status_code == 200
    assert r.text == "challenge_abc123"


def test_verify_wrong_token():
    """GET with wrong token returns 403."""
    r = client.get("/webhooks/meta/whatsapp", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "wrong_token",
        "hub.challenge": "challenge_abc123",
    })
    assert r.status_code == 403


def test_verify_missing_mode():
    """GET with missing hub.mode returns 403."""
    r = client.get("/webhooks/meta/whatsapp", params={
        "hub.verify_token": "test_token_067",
        "hub.challenge": "challenge_abc123",
    })
    assert r.status_code == 403


def test_verify_wrong_mode():
    """GET with wrong hub.mode returns 403."""
    r = client.get("/webhooks/meta/whatsapp", params={
        "hub.mode": "unsubscribe",
        "hub.verify_token": "test_token_067",
        "hub.challenge": "challenge_abc123",
    })
    assert r.status_code == 403


def test_post_json_payload():
    """POST with JSON body returns 200."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "967346842390828", "changes": []}]
    }
    r = client.post("/webhooks/meta/whatsapp", json=payload)
    assert r.status_code == 200
    assert r.text == "OK"


def test_post_empty_body():
    """POST with empty body returns 200 (never reject Meta)."""
    r = client.post("/webhooks/meta/whatsapp", content=b"", headers={"content-type": "application/json"})
    assert r.status_code == 200


def test_health_endpoint():
    """GET /health returns ok."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
