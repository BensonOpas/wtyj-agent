# test_216_your_info.py
# Brief 216: Your Info GET/PUT (whitelisted client.json fields, atomic
# write-through with cache invalidate) + Your Info Updates (info_updates
# table with permanent + scheduled flavors + Marina prompt injection).

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from fastapi.testclient import TestClient
from agents.social.webhook_server import app
from shared import config_loader, state_registry

client = TestClient(app)


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _wipe_info_updates():
    """Drop info_updates rows used by Brief 216 tests."""
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM info_updates")
    conn.commit()
    conn.close()


# ── Test 1: GET /settings/your-info returns whitelist only ────────────────────
def test_get_your_info_returns_whitelist_only():
    token = _login()
    r = client.get("/dashboard/api/settings/your-info", headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    expected_keys = set(config_loader.your_info_whitelist())
    assert set(body.keys()) == expected_keys
    # Sanity: known non-whitelisted fields must NOT leak
    assert "services" not in body
    assert "payment" not in body
    assert "agent_signature" not in body


def test_get_your_info_uses_top_level_minimal_tenant_fields(monkeypatch, tmp_path):
    seed = {
        "slug": "lawyer",
        "name": "Lawyer",
        "email": "lawyer@example.com",
        "whatsapp": "+59996945527",
        "website": "https://lawyer.example",
    }
    cfg_path = tmp_path / "client.json"
    cfg_path.write_text(json.dumps(seed))
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(cfg_path))
    monkeypatch.setattr(config_loader, "_cache", {})

    token = _login()
    r = client.get("/dashboard/api/settings/your-info", headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Lawyer"
    assert body["email"] == "lawyer@example.com"
    assert body["support_email"] == "lawyer@example.com"
    assert body["phone"] == "+59996945527"
    assert body["whatsapp"] == "+59996945527"
    assert body["website"] == "https://lawyer.example"


# ── Test 2: PUT /settings/your-info writes through to disk + invalidates cache ─
def test_put_your_info_writes_through_to_disk(monkeypatch, tmp_path):
    seed = {
        "business": {
            "name": "Original Co",
            "email": "old@example.com",
            "phone": "+10000000000",
            "languages": ["English"],
        },
        "services": {"keep": "this"},
    }
    cfg_path = tmp_path / "client.json"
    cfg_path.write_text(json.dumps(seed))

    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(cfg_path))
    monkeypatch.setattr(config_loader, "_cache", {})

    token = _login()
    r = client.put(
        "/dashboard/api/settings/your-info",
        json={"phone": "+12025550100", "name": "New Co"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["phone"] == "+12025550100"
    assert body["name"] == "New Co"

    on_disk = json.loads(cfg_path.read_text())
    assert on_disk["business"]["phone"] == "+12025550100"
    assert on_disk["business"]["name"] == "New Co"
    # Untouched fields preserved
    assert on_disk["business"]["email"] == "old@example.com"
    assert on_disk["services"] == {"keep": "this"}

    # Cache invalidated → next get_business reads from disk
    biz = config_loader.get_business()
    assert biz["phone"] == "+12025550100"


# ── Test 3: update_business_field rejects non-whitelisted keys directly ───────
def test_update_business_field_rejects_non_whitelisted_keys(monkeypatch, tmp_path):
    """Direct unit test on the helper — the whitelist defense exists at
    BOTH the endpoint (Pydantic) and the helper layer. This test exercises
    the helper's defense in case internal code calls it with an arbitrary
    key (e.g., a future feature passing key from a config table)."""
    seed = {"business": {"name": "Co"}, "services": {"sunset": "x"}}
    cfg_path = tmp_path / "client.json"
    cfg_path.write_text(json.dumps(seed))
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(cfg_path))
    monkeypatch.setattr(config_loader, "_cache", {})

    # services is NOT in the whitelist → returns False, file unchanged
    ok = config_loader.update_business_field("services", {"hacked": True})
    assert ok is False
    on_disk = json.loads(cfg_path.read_text())
    assert on_disk["services"] == {"sunset": "x"}

    # name IS in the whitelist → returns True, file updated
    ok = config_loader.update_business_field("name", "New Co")
    assert ok is True
    on_disk = json.loads(cfg_path.read_text())
    assert on_disk["business"]["name"] == "New Co"


def test_agent_name_settings_save_and_validate(monkeypatch, tmp_path):
    seed = {"business": {"name": "Co", "agent_name": "Marina"}}
    cfg_path = tmp_path / "client.json"
    cfg_path.write_text(json.dumps(seed))
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(cfg_path))
    monkeypatch.setattr(config_loader, "_cache", {})

    token = _login()
    r = client.get("/dashboard/api/settings/agent-name", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["effectiveName"] == "Marina"

    r = client.put(
        "/dashboard/api/settings/agent-name",
        json={"agent_name": "Sofia"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["effectiveName"] == "Sofia"
    on_disk = json.loads(cfg_path.read_text())
    assert on_disk["business"]["agent_name"] == "Sofia"

    r = client.put(
        "/dashboard/api/settings/agent-name",
        json={"agent_name": "Official Meta Support"},
        headers=_auth(token),
    )
    assert r.status_code == 400

    r = client.put(
        "/dashboard/api/settings/agent-name",
        json={"agent_name": "ChatGPT"},
        headers=_auth(token),
    )
    assert r.status_code == 400


def test_agent_name_settings_respects_admin_override(monkeypatch, tmp_path):
    seed = {"business": {"name": "Co", "agent_name": "Marina"}}
    cfg_path = tmp_path / "client.json"
    cfg_path.write_text(json.dumps(seed))
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(cfg_path))
    monkeypatch.setattr(config_loader, "_cache", {})

    from shared import icp_overrides

    envelope = {
        "ai_agent_settings": {
            "tone": None,
            "escalation_rules": None,
            "agent_name": {"name": "Sofia", "source": "icp_override"},
        }
    }
    monkeypatch.setattr(icp_overrides, "fetch_overrides", lambda: envelope)

    token = _login()
    r = client.get("/dashboard/api/settings/agent-name", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["source"] == "admin_override"
    assert r.json()["effectiveName"] == "Sofia"

    r = client.put(
        "/dashboard/api/settings/agent-name",
        json={"agent_name": "Pepa"},
        headers=_auth(token),
    )
    assert r.status_code == 409
    on_disk = json.loads(cfg_path.read_text())
    assert on_disk["business"]["agent_name"] == "Marina"


# ── Test 4: info_update_create permanent + scheduled rows ─────────────────────
def test_info_update_create_permanent_and_scheduled():
    try:
        _wipe_info_updates()
        perm_id = state_registry.info_update_create(text="we now offer X")
        sched_id = state_registry.info_update_create(
            text="valentine promo",
            type_="offer",
            start_date="2026-02-13",
            end_date="2026-02-14",
        )
        assert perm_id > 0
        assert sched_id > 0
        rows = state_registry.info_updates_list_all()
        ids_to_rows = {r["id"]: r for r in rows}
        assert perm_id in ids_to_rows
        assert sched_id in ids_to_rows
        # Permanent row: no dates, default type general
        perm = ids_to_rows[perm_id]
        assert perm["startDate"] is None
        assert perm["endDate"] is None
        assert perm["type"] == "general"
        assert perm["active"] is True
        # Scheduled row: has dates + custom type
        sched = ids_to_rows[sched_id]
        assert sched["startDate"] == "2026-02-13"
        assert sched["endDate"] == "2026-02-14"
        assert sched["type"] == "offer"
    finally:
        _wipe_info_updates()


# ── Test 5: get_active_info_updates window filtering ──────────────────────────
def test_get_active_info_updates_window_filtering():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    long_ago = "2020-01-01"
    long_past = "2020-01-31"
    try:
        _wipe_info_updates()
        # (a) permanent active → included
        state_registry.info_update_create(text="permanent active", active=True)
        # (b) permanent inactive → excluded (active=False)
        state_registry.info_update_create(text="permanent inactive", active=False)
        # (c) scheduled in-window → included (today within yesterday..tomorrow)
        state_registry.info_update_create(
            text="scheduled in window",
            start_date=yesterday, end_date=tomorrow,
        )
        # (d) scheduled out-of-window → excluded (end_date in past)
        state_registry.info_update_create(
            text="scheduled past",
            start_date=long_ago, end_date=long_past,
        )

        active = state_registry.get_active_info_updates()
        texts = {r["text"] for r in active}
        assert "permanent active" in texts
        assert "scheduled in window" in texts
        assert "permanent inactive" not in texts
        assert "scheduled past" not in texts
    finally:
        _wipe_info_updates()


def test_info_update_set_active_updates_row():
    try:
        _wipe_info_updates()
        row_id = state_registry.info_update_create(text="temporary promo")
        assert state_registry.info_update_set_active(row_id, False) is True
        rows = state_registry.info_updates_list_all()
        row = next(r for r in rows if r["id"] == row_id)
        assert row["active"] is False
        assert state_registry.info_update_set_active(99999999, True) is False
    finally:
        _wipe_info_updates()


# ── Test 6: Marina prompt includes ACTIVE BUSINESS UPDATES when flag on ───────
def test_marina_prompt_includes_info_updates_when_flag_on():
    from agents.marina import marina_agent

    sentinel = "BRIEF_216_we_close_christmas_unique_marker_xyz"
    original_get_raw = config_loader.get_raw

    def patched_get_raw():
        raw = dict(original_get_raw())
        features = dict(raw.get("features", {}) or {})
        features["info_updates_in_prompt"] = True
        raw["features"] = features
        return raw

    try:
        _wipe_info_updates()
        # Without seeded rows + flag off, prompt has no block
        prompt_off = marina_agent._build_system_prompt(thread_flags={}, channel="email")
        assert "ACTIVE BUSINESS UPDATES" not in prompt_off

        # Seed an active row, enable flag, prompt should now include the block
        state_registry.info_update_create(text=sentinel, type_="holiday")
        with patch.object(config_loader, "get_raw", patched_get_raw):
            prompt_on = marina_agent._build_system_prompt(thread_flags={}, channel="email")

        assert "ACTIVE BUSINESS UPDATES" in prompt_on
        assert sentinel in prompt_on
    finally:
        _wipe_info_updates()
