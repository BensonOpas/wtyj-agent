# BRIEF 229 — Data retention settings (storage + endpoints, cleanup deferred)
**Status:** Draft | **Files:** `wtyj/shared/state_registry.py`, `wtyj/dashboard/api.py`, `wtyj/tests/social/test_229_data_retention.py` | **Depends on:** Brief 216 (whitelisted-field settings pattern + atomic write idiom) | **Blocks:** SR's `useDataRetentionSettings` hook moving from `localStorage` to a real backend

## Context

SR's task `ab7d8f1eb97c` ("Jr, we need backend support for Data Retention & Archive settings"):
> "GET/PUT /settings/data-retention. Allowed values: activeInboxArchiveAfterDays in {30, 60, 90, 180, null}; archiveRetentionMonths in {12, 24, 36, 60, null}; endOfRetentionAction in {anonymize, delete, keep}; keepApprovedLearnings boolean; auditLogRetentionMonths in {12, 24, 36, 60}. Manual actions: POST archive-now, POST export, POST delete-customer-data. Return clear status and counts. No silent fail. No fake success."

Frontend today: `use-data-retention-settings.ts` is purely localStorage with `status.policyActive: false` to be honest about not yet being wired to a backend. The frontend never calls the backend; defaults match SR's spec verbatim (90 / 24 months / anonymize / true / 24).

**Scope choice for tonight: settings storage + GET/PUT only. Action endpoints (archive-now, export, delete-customer-data) return 501 with a clear message.** The actions need real cleanup logic — a cron job that walks `whatsapp_threads`, `email_thread_state.json`, `pending_notifications`, and `learning_entries`, applies the policy, anonymizes/deletes per setting, and produces audit rows. That's a multi-brief project (per my recommendation when this work was scoped). Shipping settings persistence first lets SR's frontend stop using localStorage; shipping cleanup actions safely needs its own brief with real test coverage on actual data destruction.

## Why This Approach

**Chosen:** add a singleton `data_retention_settings` row keyed on fixed `id=1` (matches Brief 217's `alert_settings` pattern). Pydantic validates the discrete value sets at the API layer (FastAPI returns 422 on bad values). Action endpoints return 501 with explicit `Cleanup automation not implemented yet. Settings are stored.` — SR's frontend already has graceful 404/501 handling per his task's "No fake success" rule.

**Rejected: implement archive/anonymize/export tonight.** Multi-hour work each, and each touches real customer data — needs careful test design including "active unresolved escalation does not get archived" guards (per SR's spec). Worth its own brief.

**Rejected: store as JSON blob in a single TEXT column.** Discrete enums are easier to query and validate as columns. The five fields are stable per the spec; not adding a sixth tomorrow.

**Rejected: reuse `alert_settings` row.** Different domain, different validation, different audit-log story. Separate concerns.

**Tradeoff: `status.policyActive` is hardcoded `false` in the response until the cleanup job ships.** Honest. SR explicitly designed his frontend to respect this — it shows a "Settings saved but automation not yet running" copy when `policyActive: false`.

**Validation strategy:** Pydantic model with `Literal[...]` types and `field_validator`. `null` (Python `None`) is allowed for `activeInboxArchiveAfterDays` and `archiveRetentionMonths` per SR's spec. The other three fields are required.

## Instructions

### 1. Schema

In `wtyj/shared/state_registry.py`, add the table to `_get_conn()` after the `appointments` CREATE block (Brief 228, around line 471):

```python
    # Brief 229: data retention settings (singleton row, fixed id=1).
    # Active inbox archive threshold + archive retention + end-of-retention
    # action + keep-approved-learnings + audit log retention.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS data_retention_settings ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "active_inbox_archive_after_days INTEGER, "
        "archive_retention_months INTEGER, "
        "end_of_retention_action TEXT NOT NULL DEFAULT 'anonymize', "
        "keep_approved_learnings INTEGER NOT NULL DEFAULT 1, "
        "audit_log_retention_months INTEGER NOT NULL DEFAULT 24, "
        "updated_at TEXT NOT NULL DEFAULT ''"
        ")"
    )
```

`active_inbox_archive_after_days` and `archive_retention_months` are nullable (SQLite INTEGER columns without NOT NULL accept NULL) — `null` represents "never archive / never delete."

### 2. State-registry helpers

Place next to `appointments_list` (Brief 228, around line 1900):

```python
def get_data_retention_settings() -> dict:
    """Brief 229: return retention settings in SR's frontend shape
    (camelCase, status.policyActive=false until cleanup is implemented).
    Synthesizes a default row when none exists yet — defaults match
    SR's `DEFAULT_DATA_RETENTION` constant verbatim."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT active_inbox_archive_after_days, archive_retention_months, "
        "end_of_retention_action, keep_approved_learnings, "
        "audit_log_retention_months FROM data_retention_settings WHERE id = 1"
    ).fetchone()
    conn.close()
    if not row:
        return {
            "activeInboxArchiveAfterDays": 90,
            "archiveRetentionMonths": 24,
            "endOfRetentionAction": "anonymize",
            "keepApprovedLearnings": True,
            "auditLogRetentionMonths": 24,
            "status": {"policyActive": False},
        }
    return {
        "activeInboxArchiveAfterDays": row[0],
        "archiveRetentionMonths": row[1],
        "endOfRetentionAction": row[2] or "anonymize",
        "keepApprovedLearnings": bool(row[3]),
        "auditLogRetentionMonths": row[4] or 24,
        "status": {"policyActive": False},
    }


def save_data_retention_settings(active_inbox_archive_after_days,
                                  archive_retention_months: object,
                                  end_of_retention_action: str,
                                  keep_approved_learnings: bool,
                                  audit_log_retention_months: int) -> None:
    """Brief 229: upsert the singleton retention settings row at id=1
    (mirrors Brief 217's INSERT OR REPLACE pattern). Caller is
    responsible for validating discrete value sets — this helper trusts
    its inputs."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO data_retention_settings "
        "(id, active_inbox_archive_after_days, archive_retention_months, "
        "end_of_retention_action, keep_approved_learnings, "
        "audit_log_retention_months, updated_at) "
        "VALUES (1, ?, ?, ?, ?, ?, ?)",
        (active_inbox_archive_after_days, archive_retention_months,
         end_of_retention_action,
         1 if keep_approved_learnings else 0,
         audit_log_retention_months, now))
    conn.commit()
    conn.close()
```

### 3. Pydantic models + endpoints

In `wtyj/dashboard/api.py`, around the Brief 216 Settings section (after the `info-updates` DELETE handler, ~line 870), add:

```python
# --- Brief 229: Data retention settings ---
# Storage + GET/PUT only this brief. Cleanup automation (archive-now,
# export, delete-customer-data) returns 501 — implementation lives in
# a future brief that handles actual data destruction safely.

from typing import Literal


class DataRetentionUpdate(BaseModel):
    activeInboxArchiveAfterDays: Literal[30, 60, 90, 180, None] = 90
    archiveRetentionMonths: Literal[12, 24, 36, 60, None] = 24
    endOfRetentionAction: Literal["anonymize", "delete", "keep"] = "anonymize"
    keepApprovedLearnings: bool = True
    auditLogRetentionMonths: Literal[12, 24, 36, 60] = 24


@router.get("/settings/data-retention", dependencies=[Depends(_check_auth)])
async def get_data_retention():
    """Brief 229: return retention settings in SR's expected shape."""
    return state_registry.get_data_retention_settings()


@router.put("/settings/data-retention", dependencies=[Depends(_check_auth)])
async def put_data_retention(req: DataRetentionUpdate):
    """Brief 229: persist retention settings. Pydantic Literal types
    enforce discrete value sets — invalid values return 422 with a
    clear field-level error message."""
    state_registry.save_data_retention_settings(
        active_inbox_archive_after_days=req.activeInboxArchiveAfterDays,
        archive_retention_months=req.archiveRetentionMonths,
        end_of_retention_action=req.endOfRetentionAction,
        keep_approved_learnings=req.keepApprovedLearnings,
        audit_log_retention_months=req.auditLogRetentionMonths,
    )
    return state_registry.get_data_retention_settings()


@router.post("/data-retention/archive-now",
             dependencies=[Depends(_check_auth)])
async def data_retention_archive_now():
    """Brief 229: not implemented yet — cleanup automation lives in a
    future brief. Honest 501 per SR's 'No fake success' rule."""
    raise HTTPException(
        status_code=501,
        detail=("Cleanup automation not implemented yet. Settings are "
                "stored. Archive will run when the cleanup job ships in "
                "a follow-up brief."))


@router.post("/data-retention/export",
             dependencies=[Depends(_check_auth)])
async def data_retention_export():
    """Brief 229: not implemented yet."""
    raise HTTPException(
        status_code=501,
        detail=("Data export not implemented yet. Will ship in a "
                "follow-up brief alongside cleanup automation."))


@router.post("/data-retention/delete-customer-data",
             dependencies=[Depends(_check_auth)])
async def data_retention_delete_customer():
    """Brief 229: not implemented yet."""
    raise HTTPException(
        status_code=501,
        detail=("Customer data deletion not implemented yet. Will ship "
                "in a follow-up brief alongside cleanup automation."))
```

(Verify `from typing import Literal` is not duplicated — if `typing.Literal` is already imported elsewhere in api.py, skip the new import.)

## Tests

Place at `wtyj/tests/social/test_229_data_retention.py`:

```python
"""Tests for Brief 229 — data retention settings storage + GET/PUT."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from fastapi.testclient import TestClient
from agents.social.webhook_server import app
from shared import state_registry

client = TestClient(app)


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _reset():
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM data_retention_settings")
    conn.commit()
    conn.close()


def test_get_returns_defaults_when_no_row_exists():
    """Brief 229: GET returns SR's DEFAULT_DATA_RETENTION shape when
    nothing has been saved yet."""
    _reset()
    token = _login()
    r = client.get("/dashboard/api/settings/data-retention",
                   headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["activeInboxArchiveAfterDays"] == 90
    assert body["archiveRetentionMonths"] == 24
    assert body["endOfRetentionAction"] == "anonymize"
    assert body["keepApprovedLearnings"] is True
    assert body["auditLogRetentionMonths"] == 24
    assert body["status"] == {"policyActive": False}


def test_put_persists_full_settings():
    """Brief 229: PUT round-trips through DB and the next GET returns
    the same values."""
    _reset()
    token = _login()
    payload = {
        "activeInboxArchiveAfterDays": 60,
        "archiveRetentionMonths": 36,
        "endOfRetentionAction": "delete",
        "keepApprovedLearnings": False,
        "auditLogRetentionMonths": 12,
    }
    r = client.put("/dashboard/api/settings/data-retention",
                   json=payload, headers=_auth(token))
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["activeInboxArchiveAfterDays"] == 60
    assert saved["archiveRetentionMonths"] == 36
    assert saved["endOfRetentionAction"] == "delete"
    assert saved["keepApprovedLearnings"] is False
    assert saved["auditLogRetentionMonths"] == 12
    # Re-GET to confirm DB persistence.
    r2 = client.get("/dashboard/api/settings/data-retention",
                    headers=_auth(token))
    assert r2.json()["endOfRetentionAction"] == "delete"
    assert r2.json()["keepApprovedLearnings"] is False


def test_put_accepts_null_for_inbox_and_archive():
    """Brief 229: null is the 'never archive / never delete' value for
    activeInboxArchiveAfterDays and archiveRetentionMonths."""
    _reset()
    token = _login()
    payload = {
        "activeInboxArchiveAfterDays": None,
        "archiveRetentionMonths": None,
        "endOfRetentionAction": "keep",
        "keepApprovedLearnings": True,
        "auditLogRetentionMonths": 60,
    }
    r = client.put("/dashboard/api/settings/data-retention",
                   json=payload, headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["activeInboxArchiveAfterDays"] is None
    assert body["archiveRetentionMonths"] is None
    assert body["endOfRetentionAction"] == "keep"


def test_put_422_on_invalid_inbox_value():
    """Brief 229: only {30, 60, 90, 180, null} are accepted for
    activeInboxArchiveAfterDays."""
    _reset()
    token = _login()
    r = client.put(
        "/dashboard/api/settings/data-retention",
        json={
            "activeInboxArchiveAfterDays": 45,  # not in allowed set
            "archiveRetentionMonths": 24,
            "endOfRetentionAction": "anonymize",
            "keepApprovedLearnings": True,
            "auditLogRetentionMonths": 24,
        }, headers=_auth(token))
    assert r.status_code == 422


def test_put_422_on_invalid_action():
    """Brief 229: endOfRetentionAction enum validated."""
    _reset()
    token = _login()
    r = client.put(
        "/dashboard/api/settings/data-retention",
        json={
            "activeInboxArchiveAfterDays": 90,
            "archiveRetentionMonths": 24,
            "endOfRetentionAction": "purge",  # not allowed
            "keepApprovedLearnings": True,
            "auditLogRetentionMonths": 24,
        }, headers=_auth(token))
    assert r.status_code == 422


def test_put_422_on_invalid_audit_value():
    """Brief 229: auditLogRetentionMonths must be in {12, 24, 36, 60}."""
    _reset()
    token = _login()
    r = client.put(
        "/dashboard/api/settings/data-retention",
        json={
            "activeInboxArchiveAfterDays": 90,
            "archiveRetentionMonths": 24,
            "endOfRetentionAction": "anonymize",
            "keepApprovedLearnings": True,
            "auditLogRetentionMonths": 6,  # not allowed
        }, headers=_auth(token))
    assert r.status_code == 422


def test_action_endpoints_return_501():
    """Brief 229: cleanup actions are unimplemented; honest 501 per SR's
    'No fake success' rule."""
    token = _login()
    for path in ("/dashboard/api/data-retention/archive-now",
                 "/dashboard/api/data-retention/export",
                 "/dashboard/api/data-retention/delete-customer-data"):
        r = client.post(path, headers=_auth(token))
        assert r.status_code == 501, f"{path} -> {r.status_code}"
        assert "not implemented" in r.json()["detail"].lower()
```

## Success Condition

After deploy, GET `/settings/data-retention` returns SR's exact `DEFAULT_DATA_RETENTION` shape when nothing's saved. PUT accepts the discrete value sets, rejects out-of-range values with 422, and round-trips through DB. The three action endpoints exist but return 501 with explicit "not implemented" messages so SR's frontend gets a clear contract instead of a 404. Full suite stays at 1059 + 7 new = 1066 passing / 0 failures.

## Rollback

`git revert <commit>`. The `data_retention_settings` table survives revert (CREATE IF NOT EXISTS, no DROP). All endpoints disappear; SR's frontend gracefully falls back to its existing localStorage path. No data migration.
