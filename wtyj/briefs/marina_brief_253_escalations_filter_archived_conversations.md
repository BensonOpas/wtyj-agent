# BRIEF 253 — Filter `get_all_escalations` by `conversation_status.deleted` (Brief 249 follow-up)

**Status:** Draft (round 2) | **Files:** wtyj/shared/state_registry.py, wtyj/tests/social/test_249_server_side_archive.py | **Depends on:** Brief 252 (`cae2213`) | **Blocks:** none

## Context

Issue #22 (Calvin live verification, P1) — stuck escalation row in the dashboard's Escalations tab that can't be archived/deleted. Calvin: "This one is impossible to archive, it's stuck. Please just delete but study what happened. We don't want it to happen again."

**Read-only audit on unboks production state_registry confirmed root cause:**

Calvin's WhatsApp conversation `69efec187aca03948969dc95` has `conversation_status.deleted=1` (archived per Brief 249) AND has **7 escalation rows** (id=15, 19, 20, 22, 24, 25, 29) — 1 status='replied' + 6 status='resolved'. The conversation was archived correctly via Brief 249's endpoint; the dashboard's Messages tab no longer shows it. **But the Escalations tab still shows all 7 rows because `get_all_escalations()` has no filter on `conversation_status.deleted`.** A second Calvin WA conv `69f7cea6e99a2574e014abec` is also archived and contributes 1 more visible escalation (id=21). **Total stuck rows: 8.**

**Verified read-only:**
- `wtyj/shared/state_registry.py:2240` — `get_all_escalations()` SELECT has NO join with `conversation_status` and NO filter on `deleted`. Returns ALL escalation rows from `pending_notifications` regardless of whether their conversation has been archived.
- `wtyj/dashboard/api.py:2074` — `list_escalations` endpoint (Brief 249-extended) accepts `?mode=` and `?status=` filters but neither helps here. The frontend's "active" view sees all rows including those whose conversation was archived.
- `wtyj/shared/state_registry.py:1517` (post-Brief-249) — `wa_list_conversations` correctly LEFT-JOINs `conversation_status` and excludes deleted=1. **Same pattern needs to apply to `get_all_escalations`.** The Brief 249 fix only covered the Messages tab, not the Escalations tab.

**Calvin's exact stuck-row count:** 8 escalation rows total visible in the Escalations tab for archived conversations:
- 7 rows on `69efec187aca03948969dc95` (id=15, 19, 20, 22, 24, 25, 29 — all WhatsApp; 6 status='resolved' + 1 status='replied')
- 1 row on `69f7cea6e99a2574e014abec` (id=21 — WhatsApp, status='resolved')

These match Calvin's screenshot description: WhatsApp channel, Calvin name, no clear way to archive (because the conversation IS archived but the escalation row doesn't know that).

**No data loss risk.** Brief 253's fix is a VIEW filter (LEFT JOIN + WHERE), not a DELETE. The escalation rows stay in `pending_notifications`. If Calvin unarchives the conversation later (Brief 249's `POST .../unarchive`), the escalation rows automatically reappear in the active view.

## Why This Approach

**Considered:** Hard-delete the 8 stuck escalation rows from `pending_notifications`. **Rejected per Calvin's hard rules:** "If item is a bad/orphaned/stale test artifact: prefer marking deleted/resolved/archived over hard delete if that is the product convention." The conversation IS already marked archived; the escalation rows just need to inherit that visibility decision via a view filter. Hard delete would lose audit trail (`alert_deliveries` rows reference these escalation_ids) and prevent future un-archive recovery.

**Considered:** Add a `deleted` column to `pending_notifications` and propagate the conversation's archive state on archive. **Rejected:** would require a schema migration AND a backfill script AND a coordinated update from `wa_set_archived` and `email_set_archived` to mutate every escalation row when archiving. The view-filter approach achieves the same operator-visible behavior with zero schema change and zero data mutation.

**Considered:** Add the filter at the endpoint layer (filter the Python list returned by `get_all_escalations()`). **Rejected:** every caller of `get_all_escalations()` would need to know to apply the filter. Filtering at the SQL layer means new callers automatically get the right behavior without remembering to add the JOIN. Mirrors Brief 249's `wa_list_conversations` LEFT JOIN approach.

**Considered:** Add a new `?include_archived=true` flag to `list_escalations` for the rare case where an operator wants to see escalations on archived conversations. **Rejected for this brief:** no observed use case yet. Brief 249's `?status=resolved` already provides a Resolved/History view that operators can use. If the use case materializes ("I archived the conv but want to revisit the escalation"), a future brief can add the flag — and the Brief 253 SQL change supports it via an `include_archived` parameter on `get_all_escalations()` defaulting to False. Defer until needed.

**Tradeoff — escalations on conversations that have NO `conversation_status` row at all (most active conversations).** The `LEFT JOIN ... WHERE cs.deleted IS NULL OR cs.deleted = 0` pattern (same as Brief 249's `wa_list_conversations` fix) preserves these. Most active conversations don't have a `conversation_status` row until something triggers status creation (escalation open, archive, block). The LEFT JOIN handles missing rows correctly.

**Tradeoff — escalations on EMAIL conversations with conversation_id like `calvin@gaimin.io`.** Brief 249's archive endpoint for emails sets `flags.deleted=true` in `email_thread_state.json`, NOT `conversation_status.deleted=1`. So Brief 253's filter only catches WhatsApp/IG/FB conversations (which use `conversation_status`). Email-archived escalations still show. **This is acceptable** because: (a) Calvin's specific stuck row is WhatsApp; (b) the email-side analog (filtering escalations whose `email_thread_state.json` has flags.deleted=true) requires loading + parsing that JSON inside the SQL-style query, which isn't a simple JOIN. Defer to a follow-up brief if the same problem materializes for email.

## Instructions

### Step 1 — Modify `get_all_escalations` SQL to filter archived conversations

In `wtyj/shared/state_registry.py:2240` (verified — the function spans roughly 50 lines from the def line), the current code reads:

```python
def get_all_escalations() -> list:
    """Return all escalation notifications, newest first.
    Brief 181: contact_type. Brief 183: customer_contact. Brief 188:
    conversation_status. Brief 213: mode. Brief 211: routable phone field.
    Brief 227: escalation_summary parsed and surfaced as escalationSummary +
    recommendedOptions + extractedDetails."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, notification_type, relay_token, channel, customer_id, "
        "customer_name, subject, body, status, created_at, mode, "
        "escalation_summary "
        "FROM pending_notifications ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    ...
```

Modify the SQL to add a LEFT JOIN against `conversation_status` and exclude rows where the conversation is archived (`deleted=1`):

```python
def get_all_escalations() -> list:
    """Return all escalation notifications, newest first.
    Brief 181: contact_type. Brief 183: customer_contact. Brief 188:
    conversation_status. Brief 213: mode. Brief 211: routable phone field.
    Brief 227: escalation_summary parsed and surfaced as escalationSummary +
    recommendedOptions + extractedDetails.
    Brief 253: excludes escalations whose WhatsApp/IG/FB conversation has
    been archived via Brief 249's archive endpoint
    (conversation_status.deleted=1). Email-channel archives use a
    different mechanism (flags.deleted in email_thread_state.json) and
    are NOT filtered by this JOIN — see Brief 253 out-of-scope notes."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT pn.id, pn.notification_type, pn.relay_token, pn.channel, "
        "pn.customer_id, pn.customer_name, pn.subject, pn.body, pn.status, "
        "pn.created_at, pn.mode, pn.escalation_summary "
        "FROM pending_notifications pn "
        # Brief 253: LEFT JOIN to drop escalations on archived conversations.
        # LEFT JOIN preserves rows whose conversation has no
        # conversation_status entry at all (most active conversations).
        "LEFT JOIN conversation_status cs ON pn.customer_id = cs.conversation_id "
        "WHERE cs.deleted IS NULL OR cs.deleted = 0 "
        "ORDER BY pn.created_at DESC"
    ).fetchall()
    conn.close()
    ...
```

The rest of the function body (rows iteration + summary parsing + dict construction) is unchanged. Only the SELECT query changes.

### Step 2 — Add 2 new tests to existing `test_249_server_side_archive.py`

Per Brief 236 rule: extend `wtyj/tests/social/test_249_server_side_archive.py` (the existing per-module test file for archive-related behavior). Append:

```python


# ── Brief 253: get_all_escalations excludes rows on archived conversations ─

def test_escalations_on_archived_wa_conversation_excluded_from_get_all():
    """Brief 253: when a WhatsApp conversation is archived via Brief
    249's wa_set_archived (conversation_status.deleted=1), its
    escalation rows are excluded from get_all_escalations() — fixing
    the issue #22 stuck-row symptom where Calvin's archived
    conversation kept showing escalations in the dashboard
    Escalations tab."""
    from shared import state_registry
    phone = "253_archived_conv_phone"
    _wipe_wa_phone(phone)

    # Seed an escalation row for this conversation
    eid = state_registry.create_pending_notification(
        notification_type="escalation", channel="whatsapp",
        customer_id=phone, customer_name="Brief 253 Test",
        subject="Stuck escalation test", body="body", mode="hard")
    try:
        # Pre-archive: escalation IS in get_all_escalations() output
        rows_before = state_registry.get_all_escalations()
        assert any(r["id"] == eid for r in rows_before), (
            f"escalation {eid} must be visible BEFORE archive; "
            f"got {[r['id'] for r in rows_before[:5]]}")

        # Archive the conversation
        state_registry.wa_set_archived(phone, True)

        # Post-archive: escalation MUST NOT appear
        rows_after = state_registry.get_all_escalations()
        assert not any(r["id"] == eid for r in rows_after), (
            f"escalation {eid} must be excluded AFTER archive; "
            f"the LEFT JOIN with conversation_status.deleted=1 should "
            f"have filtered it out")

        # Unarchive: escalation reappears (no data destroyed)
        state_registry.wa_set_archived(phone, False)
        rows_unarchived = state_registry.get_all_escalations()
        assert any(r["id"] == eid for r in rows_unarchived), (
            f"escalation {eid} must reappear after unarchive — "
            f"Brief 253 is a view filter, not a delete")
    finally:
        # Cleanup the escalation row
        conn = state_registry._get_conn()
        conn.execute("DELETE FROM pending_notifications WHERE id = ?", (eid,))
        conn.commit()
        conn.close()
        _wipe_wa_phone(phone)


def test_escalations_on_conversation_without_status_row_still_returned():
    """Brief 253: many active WhatsApp conversations have no
    conversation_status row at all. The LEFT JOIN must preserve these
    via `WHERE cs.deleted IS NULL OR cs.deleted = 0`.

    NOTE: create_pending_notification (state_registry.py:1656) calls
    set_conversation_status which UPSERTs a row, so the "no status row"
    scenario CANNOT be created via the helper. This test bypasses the
    helper with a direct SQL INSERT so the LEFT JOIN's NULL branch is
    genuinely exercised (round-1 reviewer caught the original test
    using the helper — the cs row was always being created, so the
    test never hit the NULL branch it claimed to cover)."""
    from shared import state_registry
    from datetime import datetime, timezone
    phone = "253_no_status_row_phone"
    _wipe_wa_phone(phone)
    # Defensive: ensure no conversation_status row exists for this phone.
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?",
                 (phone,))
    conn.commit()
    conn.close()

    # Direct SQL INSERT bypasses create_pending_notification and its
    # set_conversation_status side-effect.
    now = datetime.now(timezone.utc).isoformat()
    conn = state_registry._get_conn()
    cur = conn.execute(
        "INSERT INTO pending_notifications "
        "(notification_type, channel, customer_id, customer_name, "
        "subject, body, status, created_at, mode) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("escalation", "whatsapp", phone, "Brief 253 NoStatus",
         "No status row test", "body", "sent", now, "hard"))
    eid = cur.lastrowid
    conn.commit()
    conn.close()

    try:
        # Confirm no conversation_status row exists for this phone
        # (the test's whole premise).
        conn = state_registry._get_conn()
        cs_row = conn.execute(
            "SELECT 1 FROM conversation_status WHERE conversation_id = ?",
            (phone,)).fetchone()
        conn.close()
        assert cs_row is None, (
            f"test setup error: conversation_status row exists for "
            f"{phone!r}; the direct-INSERT path was supposed to bypass "
            f"set_conversation_status; defensive cleanup at start of "
            f"test must have failed")

        # Brief 253 LEFT JOIN's `cs.deleted IS NULL` branch should
        # preserve this row.
        rows = state_registry.get_all_escalations()
        assert any(r["id"] == eid for r in rows), (
            f"escalation {eid} on conversation with NO status row must "
            f"be returned; LEFT JOIN's `cs.deleted IS NULL` branch "
            f"failed to preserve it")
    finally:
        conn = state_registry._get_conn()
        conn.execute("DELETE FROM pending_notifications WHERE id = ?", (eid,))
        conn.commit()
        conn.close()
        _wipe_wa_phone(phone)
```

**Test design notes:**
- Test 1 exercises the full archive → reappear cycle: pre-archive (visible) → archive (excluded) → unarchive (reappears). Proves it's a view filter, not a delete. Uses `create_pending_notification` (which UPSERTs a `conversation_status` row with `deleted=0` via `set_conversation_status`); that row exists and the LEFT JOIN's `cs.deleted = 0` branch keeps the escalation visible until `wa_set_archived` flips it to 1.
- Test 2 covers the LEFT JOIN's NULL-handling — the common case where a conversation has NO `conversation_status` row at all. **Bypasses** `create_pending_notification` (which would auto-create the cs row via its `set_conversation_status` side-effect — round 1 reviewer caught this) and uses a direct SQL INSERT into `pending_notifications` instead. Asserts no cs row exists at test time so the LEFT JOIN's `cs.deleted IS NULL` branch is the one being exercised.
- Both tests use `_wipe_wa_phone` (already defined in this file at line ~30) for cleanup at start AND end.
- Both tests DELETE the escalation row in `finally` so cleanup runs even on assertion failure.

### Step 3 — Out of scope (documented for future briefs)

- **Email-channel archive filter** — escalations on email-archived conversations (Brief 249's `flags.deleted=true` in `email_thread_state.json`) still appear. Different mechanism; would require loading + parsing the JSON inside the query, which isn't a clean SQL JOIN. Defer; if Calvin observes the same problem with email-archived conversations, a follow-up brief adds Python-side post-fetch filtering.
- **Hard-delete the 8 historical stuck rows on Calvin's archived WA conversations** — not needed; Brief 253's filter hides them. Rows stay in `pending_notifications` for audit trail + reappear if Calvin unarchives.
- **`?include_archived=true` flag on `list_escalations`** — defer until use case materializes.
- **Propagate archive state to escalations table** (set a new `deleted` column on `pending_notifications` when conversation archived) — schema-heavier alternative; defer.
- **Resolved/History view** — Brief 249's `?status=resolved` already provides this. Brief 253's filter ALSO applies to that view (resolved escalations on archived conversations no longer appear). That's actually cleaner — operators don't see "ghost" history of conversations they intentionally archived.

## Tests

2 new tests appended to `wtyj/tests/social/test_249_server_side_archive.py` (extends existing per-module file per Brief 236).

Expected after-test count: **1083 passing / 0 failures** (1081 baseline + 2 new = 1083).

## Success Condition

After this brief lands:
1. `get_all_escalations()` returns rows EXCLUDING those whose `customer_id` matches a `conversation_status` row with `deleted=1`.
2. Conversations with NO `conversation_status` row at all continue to have their escalations returned (LEFT JOIN preserves).
3. Calvin's 8 stuck WA escalation rows (7 on `69efec187aca03948969dc95` + 1 on `69f7cea6e99a2574e014abec`) are excluded from the dashboard's Escalations view after deploy + Calvin refreshes.
4. No data destroyed — escalation rows remain in `pending_notifications`; reappear if Calvin unarchives the conversation.
5. Existing escalation-related tests still pass: `test_249_server_side_archive.py:test_get_escalations_status_filter_returns_only_resolved`, `test_213_escalation_control.py`, `test_211_dashboard_contract_fields.py`.
6. 1083 tests passing.
7. Calvin verifies in production: archived conversations no longer leave stuck escalation rows in the Escalations tab.

## Rollback

```
git revert <brief-253-commit-sha>
git push origin main
```

This restores `get_all_escalations`'s pre-Brief-253 SELECT (no JOIN). The 8 stuck rows reappear in the dashboard. CI re-deploys in ~90s. No data migration; the escalation rows have been safely preserved throughout.
