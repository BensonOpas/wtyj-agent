# BRIEF 226 — Alternative email destination for escalation alerts
**Status:** Draft | **Files:** `wtyj/dashboard/api.py`, `wtyj/shared/state_registry.py`, `wtyj/tests/social/test_226_alternative_email_destination.py` | **Depends on:** Brief 217 (escalation alert delivery + `alert_settings` table + `_fire_escalation_alerts` dispatcher) | **Blocks:** SR's "Alternative email" field rendering on the escalation-alerts settings panel

## Context

Brief 217 shipped `alert_settings` (singleton row) + `_fire_escalation_alerts` dispatcher with one email destination per tenant — defaulted to `business.support_email` from `client.json`. SR's frontend already wires an `alternativeDestination` field through `useEscalationNotificationPreferences` (api.ts:230 reads from many key shapes: `alternativeEmail`, `alternative_email`, `secondaryEmail`, `secondary_email`, `backupEmail`, `backup_email`, `alternativeDestination`). On PUT it sends the canonical `alternativeDestination` key. Backend currently strips that field on the way in and returns nothing for it on the way out.

Per SR's task: "Client can add an alternative email address. Both emails should receive escalation alerts: (1) default support/account email, (2) alternative email if provided. Both delivery audit rows. If default succeeds but alternative fails, do not block the escalation. Empty alternativeDestination is allowed. Invalid alternative email should return 400 on PUT. Do not overwrite support_email with alternativeDestination."

## Why This Approach

**Chosen:** add a single column `email_alternative_destination` (idempotent ALTER on `alert_settings`), expose it under `channels.email.alternativeDestination` in the GET response, accept it on PUT, and have `_fire_escalation_alerts` send to BOTH the primary and the alternative when both are set — each with its own row in `alert_deliveries`.

**Schema choice — one extra column on `alert_settings`, not a new junction table.**
A separate `alert_email_recipients` junction table would scale to N recipients but introduces JOIN cost on every alert read and a schema-migration burden out of proportion to the requirement. SR asked for **one** alternative ("Frontend will render this as 'Alternative email'"). One column captures the requirement exactly. If future requirements grow this to "N alternatives," the right move is a junction table; today, one column wins.

**Validation choice — Pydantic field validator that allows empty + rejects invalid.**
Per the task: empty allowed, invalid rejects 400. Validation lives on the Pydantic model (`AlertChannelConfig`) so FastAPI returns 422 with a clean error body for any non-empty non-email value. Empty string and absent field both pass through (interpreted as "no alternative configured").

**Delivery semantics — best-effort independent.**
The Brief 217 dispatcher already follows "one delivery row per channel attempt, log failures, never raise." We mirror that for the alternative: try primary first, log row 1, then try alternative if configured, log row 2. Failure on either does not affect the other or the escalation row insertion. The task explicitly says "If default email succeeds but alternative fails, do not block the escalation. Log alternative failure in alert_deliveries."

**Rejected:** allow `alternativeDestination` to OVERWRITE `email.destination` when set. SR said "Do not overwrite support_email with alternativeDestination. alternativeDestination is only a notification backup address." That's a clear product rule — keep them as two parallel fields.

**Rejected:** unify primary + alternative into a single `email.destinations: list[str]`. Cleaner shape on paper but the frontend types and the existing `email.destination` API contract would all change. SR's wire shape is `email.destination` + `email.alternativeDestination`, two distinct fields. Match it.

**Rejected:** put email validation in `state_registry.save_alert_settings`. State registry is dumb persistence — Brief 217 deliberately kept it config-loader-agnostic. Pydantic at the API boundary is where input validation belongs.

## Instructions

### 1. Schema migration (idempotent ALTER)

Open `wtyj/shared/state_registry.py`. Find the `_get_conn()` block where Brief 217's `alert_settings` table is created (around line 397). After the existing `CREATE TABLE IF NOT EXISTS alert_settings` block, add:

```python
    # Brief 226: alternative email destination for escalation alerts. Optional
    # second recipient that receives a copy of every email alert. ALTER instead
    # of expanding CREATE TABLE so existing tenant DBs migrate without a drop.
    try:
        conn.execute(
            "ALTER TABLE alert_settings "
            "ADD COLUMN email_alternative_destination TEXT NOT NULL DEFAULT ''"
        )
    except sqlite3.OperationalError:
        pass  # column already exists
```

Place this immediately AFTER the `alert_settings` `CREATE TABLE` and BEFORE the `alert_deliveries` `CREATE TABLE` so the dependency order is clear.

### 2. Read path — `get_alert_settings`

Update the SELECT statement to include the new column and emit `alternativeDestination` under `email`:

```python
def get_alert_settings(default_email_destination: str = "") -> dict:
    """Brief 226: response now includes channels.email.alternativeDestination
    (always present — empty string when not configured)."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT email_enabled, email_destination, whatsapp_enabled, "
        "whatsapp_destination, telegram_enabled, telegram_destination, "
        "messenger_enabled, messenger_destination, "
        "email_alternative_destination FROM alert_settings "
        "WHERE id = 1").fetchone()
    conn.close()
    if not row:
        return {
            "channels": {
                "email":     {"enabled": True,  "destination": default_email_destination or "",
                              "alternativeDestination": ""},
                "whatsapp":  {"enabled": False, "destination": ""},
                "telegram":  {"enabled": False, "destination": ""},
                "messenger": {"enabled": False, "destination": ""},
            }
        }
    email_dest = row[1] or ""
    if email_dest in ("", "default"):
        email_dest = default_email_destination or ""
    return {
        "channels": {
            "email":     {
                "enabled": bool(row[0]),
                "destination": email_dest,
                "alternativeDestination": row[8] or "",
            },
            "whatsapp":  {"enabled": bool(row[2]), "destination": row[3] or ""},
            "telegram":  {"enabled": bool(row[4]), "destination": row[5] or ""},
            "messenger": {"enabled": bool(row[6]), "destination": row[7] or ""},
        }
    }
```

### 3. Write path — `save_alert_settings`

Add the alternative destination to the upsert:

```python
def save_alert_settings(channels: dict) -> None:
    """Brief 217 + 226: upsert alert_settings singleton row.
    channels.email.alternativeDestination persists in
    email_alternative_destination column."""
    now = datetime.now(timezone.utc).isoformat()
    em = channels.get("email", {}) or {}
    wa = channels.get("whatsapp", {}) or {}
    tg = channels.get("telegram", {}) or {}
    ms = channels.get("messenger", {}) or {}
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO alert_settings "
        "(id, email_enabled, email_destination, whatsapp_enabled, whatsapp_destination, "
        "telegram_enabled, telegram_destination, messenger_enabled, messenger_destination, "
        "email_alternative_destination, updated_at) "
        "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1 if em.get("enabled") else 0, em.get("destination", ""),
         1 if wa.get("enabled") else 0, wa.get("destination", ""),
         1 if tg.get("enabled") else 0, tg.get("destination", ""),
         1 if ms.get("enabled") else 0, ms.get("destination", ""),
         em.get("alternativeDestination", "") or "",
         now))
    conn.commit()
    conn.close()
```

### 4. Pydantic model + validator

In `wtyj/dashboard/api.py` around line 748, replace `AlertChannelConfig` with:

```python
class AlertChannelConfig(BaseModel):
    enabled: bool = False
    destination: str = ""
    # Brief 226: alternative email destination. Only used by the email channel;
    # ignored on whatsapp/telegram/messenger. Empty string = not configured.
    alternativeDestination: str = ""

    @field_validator("alternativeDestination")
    @classmethod
    def _validate_alternative(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            return ""
        # Minimal sanity check — must contain @ and a dot AFTER it.
        # Stricter than "@" alone, looser than full RFC-5322.
        if "@" not in v:
            raise ValueError("alternativeDestination must be a valid email address")
        local, _, domain = v.partition("@")
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("alternativeDestination must be a valid email address")
        return v
```

Add `field_validator` to the existing `pydantic` import:
```python
from pydantic import BaseModel, Field, field_validator
```
(Verify the existing import line first — if `field_validator` is already imported, leave it alone.)

### 5. Dispatcher — fire to alternative too

In `wtyj/dashboard/api.py:1369-1385` replace the email block of `_fire_escalation_alerts` with:

```python
    em = channels_cfg.get("email", {})
    if em.get("enabled"):
        primary = em.get("destination", "")
        if primary in ("", "default"):
            primary = default_email
        alternative = (em.get("alternativeDestination") or "").strip()

        # Build the recipient list — primary first, then alternative if set.
        # Each recipient gets its own delivery row (best-effort independent).
        recipients = []
        if primary:
            recipients.append(primary)
        if alternative and alternative != primary:
            recipients.append(alternative)

        if not recipients:
            state_registry.record_alert_delivery(
                escalation_id, "email", "", "skipped",
                "no email destination configured")
        else:
            for dest in recipients:
                try:
                    smtp_send(dest, f"New escalation: {customer_name or 'customer'}", alert_text)
                    state_registry.record_alert_delivery(escalation_id, "email", dest, "sent")
                except Exception as exc:
                    state_registry.record_alert_delivery(
                        escalation_id, "email", dest, "failed", str(exc)[:200])
```

The `alternative != primary` guard prevents a duplicate delivery when an operator types the same address into both fields.

## Tests

Place at `wtyj/tests/social/test_226_alternative_email_destination.py`:

```python
"""Tests for Brief 226 — alternative email destination on escalation alerts."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from unittest.mock import patch
from fastapi.testclient import TestClient
from agents.social.webhook_server import app
from shared import state_registry

client = TestClient(app)


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _reset_alert_settings():
    """Wipe the singleton row + delivery audit so each test starts clean."""
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM alert_settings")
    conn.execute("DELETE FROM alert_deliveries WHERE channel = 'email'")
    conn.commit()
    conn.close()


def test_get_returns_alternative_destination_field():
    """Brief 226: GET response always includes alternativeDestination
    (empty string when not configured)."""
    _reset_alert_settings()
    token = _login()
    r = client.get("/dashboard/api/settings/escalation-alerts",
                   headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert "alternativeDestination" in body["channels"]["email"]
    assert body["channels"]["email"]["alternativeDestination"] == ""


def test_put_persists_alternative_destination():
    """Brief 226: alternativeDestination round-trips through PUT → DB → GET."""
    _reset_alert_settings()
    token = _login()
    payload = {"channels": {
        "email": {"enabled": True, "destination": "primary@example.com",
                  "alternativeDestination": "backup@example.com"},
        "whatsapp": {"enabled": False, "destination": ""},
        "telegram": {"enabled": False, "destination": ""},
        "messenger": {"enabled": False, "destination": ""},
    }}
    r = client.put("/dashboard/api/settings/escalation-alerts",
                   json=payload, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["channels"]["email"]["alternativeDestination"] == "backup@example.com"
    # Re-GET to confirm persistence.
    r2 = client.get("/dashboard/api/settings/escalation-alerts",
                    headers=_auth(token))
    assert r2.json()["channels"]["email"]["alternativeDestination"] == "backup@example.com"


def test_put_400_on_invalid_alternative_email():
    """Brief 226: invalid alternative rejected with 422 (FastAPI's Pydantic
    validation default — frontend treats >=400 the same)."""
    _reset_alert_settings()
    token = _login()
    payload = {"channels": {
        "email": {"enabled": True, "destination": "primary@example.com",
                  "alternativeDestination": "not-an-email"},
        "whatsapp": {"enabled": False, "destination": ""},
        "telegram": {"enabled": False, "destination": ""},
        "messenger": {"enabled": False, "destination": ""},
    }}
    r = client.put("/dashboard/api/settings/escalation-alerts",
                   json=payload, headers=_auth(token))
    assert r.status_code in (400, 422)


def test_put_accepts_empty_alternative():
    """Brief 226: empty alternativeDestination is allowed (means 'not
    configured')."""
    _reset_alert_settings()
    token = _login()
    payload = {"channels": {
        "email": {"enabled": True, "destination": "primary@example.com",
                  "alternativeDestination": ""},
        "whatsapp": {"enabled": False, "destination": ""},
        "telegram": {"enabled": False, "destination": ""},
        "messenger": {"enabled": False, "destination": ""},
    }}
    r = client.put("/dashboard/api/settings/escalation-alerts",
                   json=payload, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["channels"]["email"]["alternativeDestination"] == ""


@patch("dashboard.api.smtp_send")
def test_alert_dispatch_sends_to_both_addresses(mock_smtp):
    """Brief 226: when alternativeDestination is configured, _fire_escalation_alerts
    sends to BOTH primary and alternative, recording one delivery row per attempt."""
    _reset_alert_settings()
    state_registry.save_alert_settings({
        "email": {"enabled": True, "destination": "primary@example.com",
                  "alternativeDestination": "backup@example.com"},
        "whatsapp": {"enabled": False, "destination": ""},
        "telegram": {"enabled": False, "destination": ""},
        "messenger": {"enabled": False, "destination": ""},
    })
    from dashboard.api import _fire_escalation_alerts
    _fire_escalation_alerts(escalation_id=99001, customer_name="Alice",
                            channel="email", summary="testing 226", mode="hard")
    # Both addresses received the alert.
    sent_recipients = [c.args[0] for c in mock_smtp.call_args_list]
    assert sorted(sent_recipients) == ["backup@example.com", "primary@example.com"]
    # Two delivery rows logged.
    conn = state_registry._get_conn()
    rows = conn.execute(
        "SELECT destination, status FROM alert_deliveries "
        "WHERE escalation_id = 99001 AND channel = 'email' ORDER BY destination"
    ).fetchall()
    conn.close()
    assert len(rows) == 2
    assert {r[0] for r in rows} == {"primary@example.com", "backup@example.com"}
    assert all(r[1] == "sent" for r in rows)


@patch("dashboard.api.smtp_send")
def test_alert_dispatch_alternative_failure_does_not_block_primary(mock_smtp):
    """Brief 226: if primary succeeds but alternative fails, the primary
    delivery row is still 'sent' and the alternative row is 'failed'."""
    _reset_alert_settings()
    state_registry.save_alert_settings({
        "email": {"enabled": True, "destination": "primary@example.com",
                  "alternativeDestination": "broken@example.com"},
        "whatsapp": {"enabled": False, "destination": ""},
        "telegram": {"enabled": False, "destination": ""},
        "messenger": {"enabled": False, "destination": ""},
    })

    def smtp_side_effect(to_addr, *args, **kwargs):
        if to_addr == "broken@example.com":
            raise Exception("alternative send failed")
        return None
    mock_smtp.side_effect = smtp_side_effect

    from dashboard.api import _fire_escalation_alerts
    _fire_escalation_alerts(escalation_id=99002, customer_name="Bob",
                            channel="email", summary="testing 226 partial fail",
                            mode="hard")
    conn = state_registry._get_conn()
    rows = conn.execute(
        "SELECT destination, status, error FROM alert_deliveries "
        "WHERE escalation_id = 99002 AND channel = 'email' ORDER BY destination"
    ).fetchall()
    conn.close()
    by_dest = {r[0]: r for r in rows}
    assert by_dest["primary@example.com"][1] == "sent"
    assert by_dest["broken@example.com"][1] == "failed"
    assert "alternative send failed" in (by_dest["broken@example.com"][2] or "")


@patch("dashboard.api.smtp_send")
def test_dispatch_dedupes_when_primary_equals_alternative(mock_smtp):
    """Brief 226: if operator types the same address into both fields,
    we send once and log one delivery row — not two duplicates."""
    _reset_alert_settings()
    state_registry.save_alert_settings({
        "email": {"enabled": True, "destination": "same@example.com",
                  "alternativeDestination": "same@example.com"},
        "whatsapp": {"enabled": False, "destination": ""},
        "telegram": {"enabled": False, "destination": ""},
        "messenger": {"enabled": False, "destination": ""},
    })
    from dashboard.api import _fire_escalation_alerts
    _fire_escalation_alerts(escalation_id=99003, customer_name="Carol",
                            channel="email", summary="testing 226 dedupe",
                            mode="hard")
    assert mock_smtp.call_count == 1
    conn = state_registry._get_conn()
    rows = conn.execute(
        "SELECT destination FROM alert_deliveries "
        "WHERE escalation_id = 99003 AND channel = 'email'"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
```

## Success Condition

After deploy, GET `/settings/escalation-alerts` always returns `channels.email.alternativeDestination` (empty string when unset). PUT accepts a valid `alternativeDestination`, rejects an invalid one with 422, accepts empty. When an escalation row is created with both addresses configured, two `alert_deliveries` rows land — one per recipient — and `_fire_escalation_alerts` calls `smtp_send` twice. New regression tests in `test_226_alternative_email_destination.py` cover GET shape, PUT round-trip, validation, dispatch fan-out, partial failure, primary==alternative dedupe. Full suite stays at 1039 + 7 new = 1046 passing / 0 failures.

## Rollback

`git revert <commit>`. The `email_alternative_destination` column survives the revert (idempotent ALTER, no DROP), so re-applying the change later is a no-op on existing tenant DBs. The reverted code paths simply ignore the column. No data migration needed either way.
