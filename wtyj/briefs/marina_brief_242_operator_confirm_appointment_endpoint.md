# BRIEF 242 — Operator Confirm appointment endpoint (TASK-074 follow-up)

**Status:** Draft | **Files:** `wtyj/shared/state_registry.py` (new `appointment_confirm_by_id` helper near line 2200, immediately after `appointment_upsert` and before `appointments_list`), `wtyj/dashboard/api.py` (new `ConfirmAppointmentRequest` Pydantic model + new `POST /appointments/{appointment_id}/confirm` endpoint near line 1949 after the existing `GET /appointments`), `wtyj/tests/social/test_217_alert_delivery.py` (EXTEND with 4 confirm-flow tests; reuse `_wipe_appointments_for` helper from Brief 241) | **Depends on:** Brief 228 (appointments table + `appointment_upsert` + `appointments_list`), Brief 241 (`_appointment_alert_dispatcher` global + `set_appointment_alert_dispatcher` setter, transition-to-confirmed detection inside `appointment_upsert`, two-layer dedup via `appointment_alert_already_sent` + transition guard, `alertTypes.appointments` gate). **No** Brief 240 changes (Brief 240's Zernio operator route is consumed transitively when the dispatcher fires; this endpoint never calls Zernio directly). **No** Brief 238 changes (this endpoint is dashboard-API-side; tenant_guard governs inbound webhooks, not dashboard reads/writes within a tenant container). | **Blocks:** Frontend "Confirm" button work (SR territory — backend contract documented in this brief and on issue #5).

## Context

Brief 241 (TASK-074) shipped the appointment alert dispatcher and trigger. Verified at the code level + tests, but **dormant in production** because no code path currently calls `appointment_upsert(..., status='confirmed', ...)`. Calvin/Jr2 picked option A from Brief 241's "Decision needed": operator clicks Confirm in the dashboard. (Option B — Marina auto-detection of customer "yes" replies — is deferred to a separate future brief.)

This brief adds the smallest safe backend endpoint that flips an appointment to `'confirmed'`, which transitively triggers the Brief 241 dispatcher.

### Existing code shape (verified read-only)

`appointment_upsert(conversation_id, channel, customer_name, title, proposed_times, location, status='detected') -> int` at `wtyj/shared/state_registry.py:2125-2198`:
- Keyed on `conversation_id` (UNIQUE constraint on the table at line 499). Not on `id`.
- UPDATEs all fields if a row exists for that conversation_id; INSERTs otherwise.
- Detects transition: insert with `status='confirmed'` OR update where `old_status != 'confirmed' AND new_status == 'confirmed'`.
- On transition, fires `_appointment_alert_dispatcher(row_id, customer_name, channel, appointment_dict)` best-effort, gated on tenant `alertTypes.appointments`.
- Re-saves of `confirmed` status do NOT fire (transition detection at line 2157-2169).

`appointments_list()` at `state_registry.py:2201`: read-only listing in SR's frontend shape (camelCase keys).

`GET /appointments` endpoint at `wtyj/dashboard/api.py:1949-1956`: `state_registry.appointments_list()` wrapped in `{items, appointments}` envelope.

`record_alert_delivery` at `state_registry.py:1858-1881`: post-Brief-241 generalized signature `(escalation_id, channel, destination, status, error=None, alert_type='escalation', appointment_id=None)`.

`appointment_alert_already_sent(appointment_id, channel, destination) -> bool` at `state_registry.py:1899-1925`: layer-2 dedup helper. Returns True when a previous appointment-alert delivery already exists for the (appointment_id, channel, destination) tuple with terminal status (`sent` or `failed`).

### Why a new helper instead of inline endpoint logic

Three options were considered for where the confirm logic lives:

**A — Inline in the dashboard endpoint, calling `appointment_upsert` directly (rejected).** Requires the endpoint to SELECT the appointment row first to derive the conversation_id + other fields needed by `appointment_upsert`'s wide signature. Couples the dashboard module to appointment-row column knowledge. Hard to test without spinning up FastAPI's TestClient.

**B — New helper `appointment_confirm_by_id(appointment_id, ...)` in `state_registry.py` (chosen).** Single-responsibility helper. Endpoint becomes a thin auth + 404 + JSON wrapper. Helper is unit-testable without a TestClient. Mirrors the pattern of every other state_registry helper (one logical operation per function).

**C — Add a generic `appointment_set_status(appointment_id, status)` setter (rejected).** Too generic — would require callers to know which statuses are valid + which transitions fire alerts. Hides the semantic operation ("operator confirms") behind a generic setter. Easier to misuse later.

### Idempotency design

Two reasonable behaviors when an operator clicks Confirm twice in a row (or two operators confirm simultaneously):

**i — Re-call `appointment_upsert` with status='confirmed' both times.** The transition detector inside `appointment_upsert` correctly classifies the second call as `confirmed → confirmed` = no-fire. Wastes one DB write but exercises the existing transition logic with no special case. Behavior is unambiguous: idempotent at the dispatcher level via the transition check. **Chosen for the new helper.**

**ii — Short-circuit in the helper if `status='confirmed'` already.** Saves one DB write but introduces a code branch that bypasses `appointment_upsert`'s transition logic. If a future change adds side effects to `appointment_upsert` (other than the alert dispatch), short-circuiting would silently skip them. Rejected as a fragile optimization.

Either way, the helper returns a dict including `alreadyConfirmed: bool` so the dashboard can render appropriate UI ("Confirmed at 12:34" vs "Already confirmed").

### Out of scope (deferred per issue #5)

- **Marina/customer-side auto-confirm detection.** Separate future brief.
- **Storing `confirmed_by` / `note` audit columns.** API accepts them for forward compat; this brief does not add schema columns to persist them. A later brief can ALTER ADD COLUMN if Calvin needs an audit trail.
- **Reverse-confirm or "un-confirm" endpoint.** This brief only flips forward to confirmed.
- **Updating other appointment fields.** This endpoint ONLY flips status. Other fields remain whatever `appointment_upsert` was last called with.
- **BlueMarlin** — deprecated per Brief 238 + CTO directive. Not touched.

## Why This Approach

The summary-reuse decision and idempotency design are documented in Context. One additional architectural decision worth flagging:

**Returning the Brief 241 transition-detection delegation in the endpoint response.**

The endpoint response includes `alreadyConfirmed: bool` derived from the row's pre-update status. This lets the dashboard UI distinguish a fresh confirm (alerts dispatched) from a duplicate confirm (no alerts because transition didn't fire). The two-layer dedup from Brief 241 protects against double-fire regardless, but surfacing `alreadyConfirmed` lets the frontend skip a redundant toast notification when the operator clicks Confirm twice quickly.

**Tenant-template friendly.** The endpoint signature, the helper, and the response shape contain no tenant-specific logic. Any tenant whose container loads this code gets the endpoint at `https://api.unboks.org/api/{tenant}/dashboard/api/appointments/{id}/confirm`. The appointment row was created by this tenant's `appointment_upsert` (called from the per-tenant escalation_dispatcher); the confirm operates on the same per-tenant DB; the alert dispatcher reads this tenant's `alert_settings`.

## Instructions

### Step 1 — New helper in `wtyj/shared/state_registry.py`

Place immediately after `appointment_upsert` ends (around line 2199) and before `appointments_list` starts:

```python
def appointment_confirm_by_id(appointment_id: int,
                               confirmed_by: str = "operator",
                               note: str | None = None) -> dict | None:
    """Brief 242: flip an appointment's status to 'confirmed' by id.
    Re-uses appointment_upsert (keyed on conversation_id) so the Brief
    241 transition detection fires the appointment alert dispatcher
    exactly once - second/duplicate confirm calls find old_status ==
    'confirmed' and the transition guard correctly classifies them as
    no-fire.

    Returns:
        {"id": int, "status": "confirmed", "confirmedAt": iso_str,
         "alreadyConfirmed": bool} on success.
        None when no appointment row matches the given id (caller
        surfaces 404).

    confirmed_by + note are accepted for forward API compat (frontend
    can pass operator identity / note text) but are NOT persisted in
    this brief - no schema column for them yet. A future brief can
    ALTER ADD COLUMN if an audit trail of WHO confirmed is needed."""
    if not appointment_id:
        return None
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, conversation_id, channel, customer_name, title, "
        "proposed_times_json, location, status "
        "FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
    conn.close()
    if not row:
        return None
    (rid, conv_id, channel, customer_name, title, ptj, location,
     old_status) = row
    already_confirmed = (old_status == "confirmed")
    try:
        proposed_times = json.loads(ptj) if ptj else []
    except (json.JSONDecodeError, TypeError):
        proposed_times = []
    # Re-call appointment_upsert with status='confirmed'. Brief 241's
    # transition detection inside that function handles fire/no-fire
    # correctly. No special case here.
    appointment_upsert(
        conversation_id=conv_id,
        channel=channel,
        customer_name=customer_name or "",
        title=title or "",
        proposed_times=proposed_times,
        location=location or "",
        status="confirmed",
    )
    # Read updated_at after the upsert wrote (it bumps updated_at on
    # every save, even no-op confirmed→confirmed). Use this as the
    # confirmedAt timestamp for the response.
    conn = _get_conn()
    ts_row = conn.execute(
        "SELECT updated_at FROM appointments WHERE id = ?",
        (appointment_id,)).fetchone()
    conn.close()
    confirmed_at = ts_row[0] if ts_row else datetime.now(
        timezone.utc).isoformat()
    return {
        "id": rid,
        "status": "confirmed",
        "confirmedAt": confirmed_at,
        "alreadyConfirmed": already_confirmed,
    }
```

The `confirmed_by` and `note` parameters are intentionally unused in the body (accepted for API contract). Document this in the docstring (already done above).

### Step 2 — New endpoint in `wtyj/dashboard/api.py`

Place a `ConfirmAppointmentRequest` Pydantic model + the endpoint immediately after the existing `GET /appointments` endpoint (around line 1956). Mirror the existing endpoint patterns (auth, response shape, exception handling).

```python
class ConfirmAppointmentRequest(BaseModel):
    """Brief 242: optional fields for the operator confirm action.
    confirmedBy and note are accepted for forward compat (frontend can
    surface operator identity / a confirm note) but are NOT persisted
    in this brief - the appointments table has no audit columns for
    them yet. A future brief can ALTER ADD COLUMN if needed."""
    confirmedBy: str = "operator"
    note: str | None = None


@router.post("/appointments/{appointment_id}/confirm",
              dependencies=[Depends(_check_auth)])
async def confirm_appointment_endpoint(
        appointment_id: int,
        req: ConfirmAppointmentRequest = ConfirmAppointmentRequest()):
    """Brief 242: flip an appointment to 'confirmed'. Triggers the
    Brief 241 appointment alert dispatcher on the first call (status
    transition); subsequent duplicate confirm calls return
    alreadyConfirmed=true and do NOT resend alerts (Brief 241's
    two-layer dedup: layer 1 = transition detection in
    appointment_upsert, layer 2 = appointment_alert_already_sent
    audit-log check)."""
    result = state_registry.appointment_confirm_by_id(
        appointment_id,
        confirmed_by=req.confirmedBy,
        note=req.note)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="appointment not found")
    return result
```

The default-instantiated `ConfirmAppointmentRequest()` lets clients call `POST /confirm` with an empty body and still get sensible defaults (`confirmedBy="operator"`, `note=None`).

### Step 3 — Tests in `wtyj/tests/social/test_217_alert_delivery.py` (EXTEND)

Add 4 new tests at the bottom. Reuse `_wipe_appointments_for(conversation_id)` helper from Brief 241.

```python
# ── Brief 242: operator confirm endpoint flips status + triggers dispatch ─

def test_appointment_confirm_by_id_sets_status_and_fires_dispatcher(monkeypatch):
    """Brief 242: helper SELECTs by id, calls appointment_upsert with
    status='confirmed', which transitively fires the Brief 241
    dispatcher. Returns dict with alreadyConfirmed=False on first call."""
    from shared import state_registry
    conv = "test-242-confirm-fresh"
    _wipe_appointments_for(conv)
    # Seed a non-confirmed appointment
    rid = state_registry.appointment_upsert(
        conv, "whatsapp", "Calvin", "Intake call",
        ["Friday 12:00"], status="pending_team_confirmation")
    # Replace the dispatcher with a recorder
    fired = []
    monkeypatch.setattr(state_registry, "_appointment_alert_dispatcher",
                         lambda *a, **k: fired.append(a))
    result = state_registry.appointment_confirm_by_id(rid)
    assert result is not None
    assert result["id"] == rid
    assert result["status"] == "confirmed"
    assert result["alreadyConfirmed"] is False
    assert "confirmedAt" in result and result["confirmedAt"]
    # Dispatcher fired exactly once on the transition
    assert len(fired) == 1
    assert fired[0][0] == rid


def test_appointment_confirm_by_id_idempotent_on_second_call(monkeypatch):
    """Brief 242: a second confirm on an already-confirmed row returns
    alreadyConfirmed=True and does NOT fire the dispatcher again
    (Brief 241 transition detection: confirmed→confirmed = no-fire)."""
    from shared import state_registry
    conv = "test-242-confirm-twice"
    _wipe_appointments_for(conv)
    rid = state_registry.appointment_upsert(
        conv, "whatsapp", "Calvin", "Intake call",
        ["Friday 12:00"], status="confirmed")  # already confirmed
    fired = []
    monkeypatch.setattr(state_registry, "_appointment_alert_dispatcher",
                         lambda *a, **k: fired.append(a))
    result = state_registry.appointment_confirm_by_id(rid)
    assert result["status"] == "confirmed"
    assert result["alreadyConfirmed"] is True
    assert fired == []  # transition detection blocks re-fire


def test_appointment_confirm_by_id_returns_none_for_missing(monkeypatch):
    """Brief 242: helper returns None when appointment_id matches no
    row. Caller surfaces 404."""
    from shared import state_registry
    # Wipe any leftover row to be safe
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM appointments WHERE id = 99999999")
    conn.commit()
    conn.close()
    result = state_registry.appointment_confirm_by_id(99999999)
    assert result is None


def test_confirm_endpoint_returns_404_for_missing_appointment():
    """Brief 242: POST /appointments/{id}/confirm returns 404 with
    detail='appointment not found' when the id matches no row in the
    appointments table.

    Uses the real `_login()` pattern from `test_228_appointments.py:55`
    (NOT a monkeypatch on _check_auth — FastAPI's Depends captures the
    callable at decoration time, so module-level monkeypatch does not
    swap the dependency on already-registered routes). Exercises the
    real `appointment_confirm_by_id(<id-with-no-row>)` path so the test
    integrates the helper SELECT + None return + endpoint 404 raise
    end-to-end, not just the endpoint's `if result is None` check."""
    import os
    os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
    from fastapi.testclient import TestClient
    from agents.social.webhook_server import app
    from shared import state_registry
    # Wipe any leftover row at this absurd test id to guarantee
    # appointment_confirm_by_id returns None for the right reason.
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM appointments WHERE id = 9999991")
    conn.commit()
    conn.close()
    client = TestClient(app)
    # Real login flow — same pattern as test_228_appointments.py
    login_r = client.post(
        "/dashboard/api/login", json={"password": "testpass"})
    assert login_r.status_code == 200, f"login failed: {login_r.text}"
    token = login_r.json()["token"]
    resp = client.post(
        "/dashboard/api/appointments/9999991/confirm",
        json={"confirmedBy": "operator"},
        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "appointment not found"
```

Four tests. All exercise real branches:
1. Helper SELECTs + calls `appointment_upsert` + dispatcher fires + result shape correct.
2. Idempotency: second confirm returns `alreadyConfirmed=True`, dispatcher does NOT re-fire.
3. Helper returns None for missing id.
4. Endpoint returns 404 with the documented detail string for missing id.

Tests use real `appointment_upsert` (no mock-the-thing-you-test) so the round-trip through Brief 241's transition detection is exercised end-to-end. Test 4 uses TestClient + auth stub since the assertion is HTTP-layer (404 + detail).

**Regression baseline:** 1038 passing / 0 failures (per Brief 241 system_state). After this brief: **1042 passing / 0 failures** (1038 + 4 new).

## Success Condition

After execution:

1. `python3 -m pytest wtyj/tests/social/test_217_alert_delivery.py -q` passes (existing 25 + 4 new = 29).
2. `python3 -m pytest wtyj/tests/ -q` reports 1042 passing / 0 failures.
3. After deploy: `curl -sf -X POST https://api.unboks.org/api/unboks/dashboard/api/appointments/<real-id>/confirm -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{}'` returns `{"id": <id>, "status": "confirmed", "confirmedAt": "<iso>", "alreadyConfirmed": false}` on first call. `docker exec wtyj-unboks sqlite3 /app/data/state_registry.db "SELECT status FROM appointments WHERE id=<id>;"` returns `confirmed`.
4. After step 3, immediately POST again: returns `alreadyConfirmed: true` and `docker exec wtyj-unboks sqlite3 /app/data/state_registry.db "SELECT COUNT(*) FROM alert_deliveries WHERE alert_type='appointment' AND appointment_id=<id>;"` shows the same row count as after step 3 (no new rows; Brief 241 dedup confirmed working).
5. POST to a non-existent id returns HTTP 404 with `detail="appointment not found"`.
6. CI green; all 4 containers healthy; Brief 238 tenant guard / Brief 239 rich body / Brief 240 Zernio route / Brief 241 dispatcher all preserved.

## Rollback

Code-only rollback: `git revert <this brief's source commit>` and push. Pipeline auto-deploys (~90s). The endpoint disappears; the helper disappears; the appointments table is unchanged (no schema migration in this brief). Any appointment rows that were already flipped to `'confirmed'` by this endpoint stay confirmed (the alert was sent, the audit log row exists). To "un-confirm" a row after a revert: `docker exec wtyj-unboks sqlite3 /app/data/state_registry.db "UPDATE appointments SET status='pending_team_confirmation' WHERE id=<id>;"` (does not re-trigger any alerts since `appointment_upsert` is the trigger path, not direct UPDATE).

If only the new endpoint is misbehaving (e.g., 404 logic broken, helper returns wrong shape), the helper can be left in place and the endpoint can be temporarily disabled by commenting out the `@router.post` decorator + `docker compose restart wtyj-unboks`. Existing `appointment_upsert` callers (currently only the escalation_dispatcher path) are unaffected.

### Frontend / SR contract (non-rollback note for the issue report)

```
POST  /dashboard/api/appointments/{appointment_id}/confirm
Auth: Bearer token (existing dashboard auth)

Request body (all optional):
{
  "confirmedBy": "operator",   // free string; not persisted yet
  "note": "free text"          // string | null; not persisted yet
}

200 Response:
{
  "id": 42,
  "status": "confirmed",
  "confirmedAt": "2026-05-10T08:01:23.456789+00:00",
  "alreadyConfirmed": false   // true on second/duplicate call
}

404 Response:
{
  "detail": "appointment not found"
}
```

Frontend should treat `alreadyConfirmed: true` as "no-op success" — display a quieter toast than for a fresh confirm. Both 200 cases should refresh the appointments list to pick up the new `status='confirmed'`.
