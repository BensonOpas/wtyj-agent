# BRIEF 254 — Clear orphan escalation flags on resolve + delete (email + WhatsApp)

**Status:** Draft | **Files:** wtyj/shared/state_registry.py, wtyj/tests/social/test_188_conversation_status.py | **Depends on:** Brief 253 (`6d329af`) | **Blocks:** none

## Context

Issue #23 (Calvin live verification + Sonia read-only audit at issue #24) — email conversation shows `escalated=true` + decision-needed summary in the Email channel, but does NOT appear in the Escalations list/count. Sonia's audit (#24) identified the root cause:

**`delete_escalation` and `resolve_conversation_from_escalation` leave orphan flags:**

- `wtyj/shared/state_registry.py:3076-3085` — `delete_escalation(escalation_id)` does `DELETE FROM pending_notifications WHERE id = ?`. **That's it.** No cleanup of `conversation_status.status` or `email_thread_state.json.flags.fully_escalated` or `whatsapp_booking_state.flags_json.fully_escalated`.
- `wtyj/shared/state_registry.py:2139-2176` — `resolve_conversation_from_escalation(escalation_id)` (called by `POST /escalations/{id}/resolve` at `api.py:2157`) DOES set `conversation_status.status='resolved'` AND clear `whatsapp_booking_state.flags_json.fully_escalated=false` — **but does NOT clear `email_thread_state.json.flags.fully_escalated` for email-channel escalations.**

**Symptom chain for an EMAIL escalation that's been deleted or resolved:**
- `pending_notifications` row: GONE (delete) or `status='resolved'` (resolve).
- `conversation_status.status`: 'open' if deleted (never cleared); 'resolved' if resolved-path (cleared correctly by `resolve_conversation_from_escalation`).
- `email_thread_state.json.flags.fully_escalated`: **True** (never cleared on either path).

**What the dashboard does with the orphan state:**
- `email_list_conversations` at `state_registry.py:1106` returns `status="escalated"` when `flags.get("fully_escalated") OR flags.get("awaiting_relay")` is truthy. So a resolved email shows `status='escalated'` forever in the Inbox list.
- Email detail endpoint `_conversation_status_fields` at `api.py:1303` returns `escalated = (conversation_status.status == "open")`. So a DELETED email (no resolve fire, so conversation_status.status stays 'open') shows `escalated=true` forever in the detail view.
- `/escalations` returns NOTHING for that customer_id (deleted) or the resolved row with status='resolved' (which the frontend filters out as `e.resolved=true`).

Result: Email/Inbox shows escalation badge + decision-needed summary, but Escalations list/count is empty. Calvin's exact symptom.

**Verified read-only:**
- `state_registry.py:3076` `delete_escalation` — confirmed: just `DELETE FROM pending_notifications`. No flag cleanup.
- `state_registry.py:2139-2176` `resolve_conversation_from_escalation` — confirmed: clears `conversation_status` + WA `whatsapp_booking_state.flags_json.fully_escalated` only. No email flag cleanup.
- `state_registry.py:1156-1159` `email_list_conversations` — confirmed: derives `status='escalated'` from `flags.get("fully_escalated") OR flags.get("awaiting_relay")`.
- `api.py:1303` `_conversation_status_fields` — confirmed: `escalated = (status == "open")` from `conversation_status` table.
- Existing tests at `wtyj/tests/social/test_188_conversation_status.py:74-103` cover the WhatsApp branch of `resolve_conversation_from_escalation` (test 4: `test_resolve_clears_fully_escalated`). No test covers the email branch (because there's no email cleanup code to test). No test covers `delete_escalation` flag cleanup (because there's no cleanup code).

## Why This Approach

**Considered:** Make the dashboard's email detail endpoint stop deriving `escalated=true` from orphan flags (i.e., REQUIRE a live `pending_notifications` row to claim escalation status). **Rejected:** would change Brief 188's existing read-side contract — many other code paths assume `conversation_status.status='open'` AND `email_thread_state.flags.fully_escalated=true` are coupled to live escalation rows. The cleanup belongs at the WRITE side (delete + resolve) so all readers downstream see consistent state.

**Considered:** Have the email_poller periodically sweep orphan flags. **Rejected:** background sweeps are eventual-consistency band-aids. Operator actions (resolve, delete) should produce immediate-consistency state on every read.

**Considered:** Extend `update_notification_status('resolved')` to call `resolve_conversation_from_escalation` automatically when status is 'resolved'. **Rejected:** `update_notification_status` is called from many internal paths (e.g., 'replied' status when operator replies via dashboard — see `api.py:2496, 2547, 2592, 2679, 2751`). Adding side-effects to a low-level UPDATE helper risks unintended cascades. The dashboard's `resolve_escalation` endpoint already calls `resolve_conversation_from_escalation` explicitly — that's the right hook point.

**Considered:** Re-using `resolve_conversation_from_escalation` from inside `delete_escalation` (since delete should clear everything resolve does PLUS the actual delete). **Accepted.** Cleaner than duplicating the cleanup logic; ensures delete + resolve produce structurally identical orphan-flag-cleared state.

**Tradeoff — email thread key matching.** Multiple `email_thread_state.json` thread_keys exist per customer email (one per subject). When clearing `fully_escalated`, we must clear it across ALL threads for that customer email — not just the one matching a specific subject. The new helper walks every thread whose `thread_key.split(':')[1] == customer_email` and clears the flag. This matches the existing behavior of `_find_email_thread_key_for(customer_email)` at `state_registry.py:1206` which returns just the first match — but for cleanup we want ALL matches (most customers have 1-2 threads; rare cases with many threads still resolve correctly).

**Tradeoff — order of operations in `delete_escalation`.** The cleanup needs the customer_id + channel from the row BEFORE deleting. New flow: (1) SELECT customer_id + channel; (2) call resolve_conversation_from_escalation-equivalent cleanup; (3) DELETE the row. Pre-Brief-254 the function did just (3). Brief 254 reorders: (1) → (2) → (3).

## Instructions

### Step 1 — Add `email_clear_fully_escalated_flag` helper to `state_registry.py`

Insert above `resolve_conversation_from_escalation` (around line 2139):

```python
def email_clear_fully_escalated_flag(customer_email: str) -> int:
    """Brief 254: clear flags.fully_escalated AND flags.awaiting_relay
    on ALL email_thread_state.json threads matching this customer email.
    Used by resolve_conversation_from_escalation + delete_escalation to
    prevent orphan escalation flags after the underlying pending_notifications
    row is resolved/deleted.

    Without this cleanup, email_list_conversations derives status='escalated'
    forever from `flags.get('fully_escalated') OR flags.get('awaiting_relay')`
    (state_registry.py:1156-1159) and the Inbox row shows an escalation
    badge with no matching row in /escalations -- the symptom Calvin
    reported in issue #23.

    Returns the count of threads whose flags were cleared (0 if no
    matching threads OR if email_thread_state.json could not be loaded;
    callers should treat this as best-effort cleanup, not a critical
    failure path)."""
    if not customer_email:
        return 0
    path = _get_email_state_path()
    if not os.path.exists(path):
        return 0
    try:
        with open(path, "r") as f:
            state = json.load(f)
    except Exception:
        return 0
    threads = state.get("threads") or {}
    cleared = 0
    for thread_key, th in threads.items():
        # thread_key shape: "subj:{customer_email}:{normalized_subject}"
        parts = thread_key.split(":", 2)
        if len(parts) < 3 or parts[0] != "subj":
            continue
        if parts[1] != customer_email:
            continue
        flags = th.setdefault("flags", {})
        if flags.get("fully_escalated") or flags.get("awaiting_relay"):
            flags["fully_escalated"] = False
            flags.pop("awaiting_relay", None)
            cleared += 1
    if cleared == 0:
        return 0
    try:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        return 0
    return cleared
```

### Step 2 — Extend `resolve_conversation_from_escalation` to clear email flag

In `wtyj/shared/state_registry.py:2139-2176`, the current function clears WA flags only. Add an email branch after the WA `UPDATE whatsapp_booking_state ...` block (around line 2173):

```python
def resolve_conversation_from_escalation(escalation_id: int) -> None:
    """Brief 188: when operator resolves an escalation, set conversation status
    to 'resolved' AND clear fully_escalated from booking state flags so the
    conversation returns to AI mode on the next customer message.

    Uses json_set() to avoid a read-modify-write cycle within this function.
    Note: a concurrent message thread that already loaded flags before this call
    may overwrite the clear via wa_save_booking_state — low severity, see brief.

    Brief 254: ALSO clears flags.fully_escalated in email_thread_state.json
    for the customer's email threads. Pre-Brief-254 the resolve path only
    cleared WA flags; email-channel escalations left orphan flags driving
    the Inbox status='escalated' forever (issue #23 root cause)."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT customer_id, channel FROM pending_notifications WHERE id = ?",
        (escalation_id,)
    ).fetchone()
    if not row:
        conn.close()
        return
    customer_id, esc_channel = row

    # Set conversation status to resolved
    conn.execute(
        "INSERT INTO conversation_status (conversation_id, channel, status, updated_at) "
        "VALUES (?, ?, 'resolved', ?) "
        "ON CONFLICT(conversation_id) DO UPDATE SET status = 'resolved', "
        "updated_at = excluded.updated_at",
        (customer_id, esc_channel or "whatsapp",
         datetime.now(timezone.utc).isoformat())
    )

    # Atomically clear fully_escalated in booking state flags (WhatsApp / IG / FB)
    conn.execute(
        "UPDATE whatsapp_booking_state "
        "SET flags_json = json_set(COALESCE(flags_json, '{}'), '$.fully_escalated', json('false')) "
        "WHERE phone = ?",
        (customer_id,)
    )

    conn.commit()
    conn.close()

    # Brief 254: also clear email flags when channel=email. Done OUTSIDE the
    # DB connection because email_thread_state.json is a file write.
    if esc_channel == "email" and customer_id:
        email_clear_fully_escalated_flag(customer_id)
```

### Step 3 — Make `delete_escalation` clear orphan state before DELETE

In `wtyj/shared/state_registry.py:3076-3085`, the current implementation is:

```python
def delete_escalation(escalation_id: int) -> bool:
    """Brief 172: hard-delete a pending_notifications row. Returns True if a
    row was deleted. Used by the dashboard Escalations page trash button (SR's
    UX — archive first, then from archive view you can delete permanently)."""
    conn = _get_conn()
    cur = conn.execute("DELETE FROM pending_notifications WHERE id = ?", (escalation_id,))
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed
```

Replace with:

```python
def delete_escalation(escalation_id: int) -> bool:
    """Brief 172: hard-delete a pending_notifications row. Returns True if a
    row was deleted. Used by the dashboard Escalations page trash button (SR's
    UX — archive first, then from archive view you can delete permanently).

    Brief 254: BEFORE the DELETE, clear orphan escalation state via
    resolve_conversation_from_escalation so:
      - conversation_status.status flips to 'resolved' (drives email detail's
        escalated=false), and
      - whatsapp_booking_state.flags_json.fully_escalated cleared (drives WA),
      - email_thread_state.json.flags.fully_escalated cleared (drives email list).
    Without this cleanup the dashboard shows escalated=true forever with
    no matching /escalations row -- issue #23 root cause."""
    # Brief 254: clear orphan flags BEFORE the DELETE.
    # resolve_conversation_from_escalation reads customer_id + channel from
    # the row, so it must run while the row still exists.
    resolve_conversation_from_escalation(escalation_id)

    conn = _get_conn()
    cur = conn.execute("DELETE FROM pending_notifications WHERE id = ?", (escalation_id,))
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed
```

### Step 4 — Add 4 new tests to `wtyj/tests/social/test_188_conversation_status.py`

Per Brief 236 — that file already has `test_resolve_clears_fully_escalated` at line 74, the existing test for `resolve_conversation_from_escalation` (WhatsApp branch). Append new tests for the email branch + delete path:

```python


# ── Brief 254: email-side flag cleanup + delete cleanup ─

def test_resolve_clears_email_fully_escalated_flag(monkeypatch, tmp_path):
    """Brief 254: resolve_conversation_from_escalation now ALSO clears
    email_thread_state.json.flags.fully_escalated for email-channel
    escalations. Pre-Brief-254 this was only cleared for WhatsApp;
    email escalations left orphan flags driving Inbox status='escalated'
    forever (issue #23)."""
    import json
    from shared import state_registry

    customer_email = "brief254_email@example.com"
    thread_key = f"subj:{customer_email}:test subject"
    fake_state = {
        "threads": {
            thread_key: {
                "messages": [{"role": "customer", "ts": "2026-05-11T00:00:00+00:00",
                              "body": "test"}],
                "fields": {"customer_name": "Brief 254 Test"},
                "flags": {"fully_escalated": True, "awaiting_relay": True},
            }
        }
    }
    state_path = tmp_path / "email_thread_state.json"
    state_path.write_text(json.dumps(fake_state))
    monkeypatch.setattr(state_registry, "_get_email_state_path",
                         lambda: str(state_path))

    # Seed an email-channel escalation row for this customer
    eid = state_registry.create_pending_notification(
        notification_type="escalation", channel="email",
        customer_id=customer_email, customer_name="Brief 254 Test",
        subject="[ESCALATION] test", body="body", mode="hard")
    try:
        # Pre-resolve: email flags are set
        with open(state_path) as f:
            pre = json.load(f)
        assert pre["threads"][thread_key]["flags"].get("fully_escalated") is True
        assert pre["threads"][thread_key]["flags"].get("awaiting_relay") is True

        state_registry.resolve_conversation_from_escalation(eid)

        # Post-resolve: email flags MUST be cleared
        with open(state_path) as f:
            post = json.load(f)
        flags = post["threads"][thread_key]["flags"]
        assert flags.get("fully_escalated") is False, (
            f"flags.fully_escalated must be False after resolve; got {flags}")
        assert "awaiting_relay" not in flags or flags.get("awaiting_relay") is None, (
            f"flags.awaiting_relay must be cleared after resolve; got {flags}")
    finally:
        conn = state_registry._get_conn()
        conn.execute("DELETE FROM pending_notifications WHERE id = ?", (eid,))
        conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?",
                     (customer_email,))
        conn.commit()
        conn.close()


def test_delete_escalation_clears_email_flags_before_deleting(monkeypatch, tmp_path):
    """Brief 254: delete_escalation now calls
    resolve_conversation_from_escalation BEFORE the DELETE, so all
    orphan flags get cleared. Pre-Brief-254 delete only did the
    DELETE — leaving conversation_status.status='open' and
    email_thread_state.flags.fully_escalated=true orphaned (issue #23
    root cause per Sonia's audit at issue #24)."""
    import json
    from shared import state_registry

    customer_email = "brief254_delete_email@example.com"
    thread_key = f"subj:{customer_email}:delete test"
    fake_state = {
        "threads": {
            thread_key: {
                "messages": [{"role": "customer", "ts": "2026-05-11T00:00:00+00:00",
                              "body": "test"}],
                "fields": {"customer_name": "Brief 254 Delete Test"},
                "flags": {"fully_escalated": True},
            }
        }
    }
    state_path = tmp_path / "email_thread_state.json"
    state_path.write_text(json.dumps(fake_state))
    monkeypatch.setattr(state_registry, "_get_email_state_path",
                         lambda: str(state_path))

    eid = state_registry.create_pending_notification(
        notification_type="escalation", channel="email",
        customer_id=customer_email, customer_name="Brief 254 Delete Test",
        subject="[ESCALATION] delete test", body="body", mode="hard")

    try:
        result = state_registry.delete_escalation(eid)
        assert result is True

        # pending_notifications row should be GONE
        conn = state_registry._get_conn()
        row = conn.execute(
            "SELECT 1 FROM pending_notifications WHERE id = ?", (eid,)).fetchone()
        conn.close()
        assert row is None, "delete_escalation should have removed the row"

        # conversation_status.status MUST be 'resolved' (not 'open')
        conn = state_registry._get_conn()
        cs = conn.execute(
            "SELECT status FROM conversation_status WHERE conversation_id = ?",
            (customer_email,)).fetchone()
        conn.close()
        assert cs is not None and cs[0] == "resolved", (
            f"conversation_status.status must be 'resolved' after delete; "
            f"got {cs[0] if cs else None!r}")

        # email_thread_state.json flags.fully_escalated MUST be cleared
        with open(state_path) as f:
            post = json.load(f)
        assert post["threads"][thread_key]["flags"].get("fully_escalated") is False, (
            f"flags.fully_escalated must be False after delete; "
            f"got {post['threads'][thread_key]['flags']}")
    finally:
        conn = state_registry._get_conn()
        conn.execute("DELETE FROM pending_notifications WHERE id = ?", (eid,))
        conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?",
                     (customer_email,))
        conn.commit()
        conn.close()


def test_delete_escalation_clears_whatsapp_flags_before_deleting():
    """Brief 254: delete_escalation also clears WhatsApp
    whatsapp_booking_state.flags_json.fully_escalated via the
    resolve_conversation_from_escalation call. Pre-Brief-254 this was
    not done on the delete path."""
    from shared import state_registry
    phone = "254_delete_wa_phone"

    # Setup: booking state with fully_escalated=True
    state_registry.wa_save_booking_state(
        phone, {"service_key": "test"}, {"fully_escalated": True}, [])
    pre_state = state_registry.wa_get_booking_state(phone)
    assert pre_state["flags"].get("fully_escalated") is True

    eid = state_registry.create_pending_notification(
        notification_type="escalation", channel="whatsapp",
        customer_id=phone, customer_name="Brief 254 WA Delete",
        subject="WA test", body="body", mode="hard")
    try:
        ok = state_registry.delete_escalation(eid)
        assert ok is True

        # WA booking state's fully_escalated MUST be False
        post_state = state_registry.wa_get_booking_state(phone)
        assert post_state["flags"].get("fully_escalated") is False, (
            f"WhatsApp fully_escalated must be False after delete; "
            f"got {post_state['flags']}")

        # conversation_status.status MUST be 'resolved'
        conn = state_registry._get_conn()
        cs = conn.execute(
            "SELECT status FROM conversation_status WHERE conversation_id = ?",
            (phone,)).fetchone()
        conn.close()
        assert cs is not None and cs[0] == "resolved"
    finally:
        conn = state_registry._get_conn()
        conn.execute("DELETE FROM pending_notifications WHERE id = ?", (eid,))
        conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?",
                     (phone,))
        conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?",
                     (phone,))
        conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
        conn.commit()
        conn.close()


def test_delete_escalation_returns_false_for_missing_row():
    """Brief 254 regression: delete_escalation still returns False when
    no row matches the escalation_id. Pre-Brief-254 behavior preserved —
    only the cleanup-before-delete logic is new."""
    from shared import state_registry
    # 99999999 is well above any real auto-increment id; safe sentinel.
    result = state_registry.delete_escalation(99999999)
    assert result is False, (
        "delete_escalation should return False for non-existent id; "
        "Pre-Brief-254 behavior must be preserved")
```

**Test design notes:**
- All 4 tests use real DB + cleanup (try/finally + DELETE WHERE id=eid + conversation_status + whatsapp_booking_state cleanup).
- Tests 1, 2 use `monkeypatch` + `tmp_path` to isolate email_thread_state.json from real production state.
- Test 3 exercises the WhatsApp branch of `delete_escalation`'s new cleanup. Mirrors the existing `test_resolve_clears_fully_escalated` at line 74-103 but for the delete path.
- Test 4 is a regression guard — the pre-Brief-254 behavior of returning False on a missing row must still work after wrapping with cleanup logic.

### Step 5 — Out of scope (documented for future briefs)

- **Backfill the orphan flags on production state.** Calvin's current `calvin@adamus.com` (`flags.fully_escalated=True` on multiple subjects) will auto-clear via Brief 254 ONLY when an operator resolves/deletes one of those escalations. A one-time sweep script could clear orphan flags retroactively but is out of scope — defer until needed.
- **Auto-clear `flags.awaiting_relay` when no active relay token exists.** Brief 254 clears it as a SIDE EFFECT of resolve/delete. A separate consistency sweep could detect orphaned `awaiting_relay=true` without a `relay_token` field. Defer.
- **Update Brief 188's docstring/test name** — Brief 188's existing `resolve_conversation_from_escalation` doc says "WhatsApp" only; Brief 254 extends it to email. Light docstring polish included; no test renames.
- **Frontend localStorage archive migration** — the OTHER half of issue #23 (per my earlier diagnosis at issue #23 comment) is SR migrating from localStorage to Brief 249's server-side archive endpoints. That's a separate frontend brief at `unboks-org/unboks-dashboard-api`.

## Tests

4 new tests appended to `wtyj/tests/social/test_188_conversation_status.py`.

Expected after-test count: **1087 passing / 0 failures** (1083 baseline + 4 new = 1087).

## Success Condition

After this brief lands:
1. `email_clear_fully_escalated_flag(customer_email)` helper exists, walks all matching `subj:{email}:*` threads, clears `flags.fully_escalated=False` and removes `flags.awaiting_relay`.
2. `resolve_conversation_from_escalation` calls the helper when `esc_channel == "email"` — resolving an email escalation clears the orphan email flags.
3. `delete_escalation` calls `resolve_conversation_from_escalation` BEFORE the DELETE — deleting an escalation clears all related orphan state (conversation_status + WA flags + email flags) THEN removes the row.
4. Existing `delete_escalation(non_existent_id)` returns False unchanged.
5. Existing `resolve_conversation_from_escalation` WA-side behavior unchanged (Brief 188's test 4 still passes).
6. 1087 tests passing.
7. Calvin live-verifies: after deploy, a deleted or resolved email escalation no longer shows `escalated=true` in the email detail OR `status='escalated'` in the Inbox list. The Email channel and Escalations tab agree.

## Rollback

```
git revert <brief-254-commit-sha>
git push origin main
```

This restores `delete_escalation` to the bare DELETE (no cleanup) and `resolve_conversation_from_escalation` to WA-only cleanup. The orphan-flag bug (issue #23) returns. No data destroyed; the cleanup didn't run, but no rows were corrupted. CI re-deploys in ~90s.
