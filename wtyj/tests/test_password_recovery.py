import json
import os
import re

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "old-password")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from fastapi.testclient import TestClient

from agents.social.webhook_server import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_config_cache():
    yield
    from shared import config_loader

    config_loader._cache = {}


def _client_config(tmp_path, monkeypatch, email="owner@example.com"):
    from shared import config_loader, state_registry

    path = tmp_path / "client.json"
    path.write_text(
        json.dumps({"slug": "demo", "business": {"name": "Demo", "email": email}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(path))
    config_loader._cache = {}
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))


def test_forgot_password_unknown_email_is_generic(tmp_path, monkeypatch):
    _client_config(tmp_path, monkeypatch)
    sent = []
    monkeypatch.setattr("agents.marina.email_adapter.smtp_send", lambda *a, **k: sent.append(a))

    r = client.post("/dashboard/api/auth/forgot-password", json={"email": "nobody@example.com"})

    assert r.status_code == 200
    assert "If this email exists" in r.json()["message"]
    assert sent == []


def test_password_reset_success_invalidates_old_password(tmp_path, monkeypatch):
    _client_config(tmp_path, monkeypatch)
    sent = []

    def fake_send(to_addr, subject, body, *args, **kwargs):
        sent.append({"to": to_addr, "subject": subject, "body": body})

    monkeypatch.setattr("agents.marina.email_adapter.smtp_send", fake_send)
    requested = client.post(
        "/dashboard/api/auth/forgot-password",
        json={"email": "owner@example.com"},
    )
    assert requested.status_code == 200
    assert len(sent) == 1
    token = re.search(r"token=([^&\s]+)", sent[0]["body"]).group(1)

    reset = client.post(
        "/dashboard/api/auth/reset-password",
        json={
            "token": token,
            "newPassword": "new-password-123",
            "confirmPassword": "new-password-123",
        },
    )
    assert reset.status_code == 200

    old_login = client.post("/dashboard/api/login", json={"password": "old-password"})
    assert old_login.status_code == 401
    new_login = client.post("/dashboard/api/login", json={"password": "new-password-123"})
    assert new_login.status_code == 200

    reused = client.post(
        "/dashboard/api/auth/reset-password",
        json={
            "token": token,
            "newPassword": "another-password-123",
            "confirmPassword": "another-password-123",
        },
    )
    assert reused.status_code == 400


def test_password_reset_rejects_weak_password(tmp_path, monkeypatch):
    _client_config(tmp_path, monkeypatch)
    r = client.post(
        "/dashboard/api/auth/reset-password",
        json={"token": "wrong", "newPassword": "short", "confirmPassword": "short"},
    )
    assert r.status_code == 400
    assert "at least" in r.json()["detail"]
