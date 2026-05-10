# BRIEF 249 — Server-side per-conversation archive endpoints + resolved escalations history

**Status:** Draft (round 2) | **Files:** wtyj/shared/state_registry.py, wtyj/dashboard/api.py, wtyj/tests/social/test_249_server_side_archive.py | **Depends on:** Brief 248 (`4bea939`) | **Blocks:** SR's frontend cross-device archive sync

## Context

Issue #18 (Calvin live verification + Sonia audit, P0/P1) — desktop and mobile dashboards show different inbox states. Operator archives a conversation on desktop; mobile keeps showing it. Root cause: archive is `localStorage`-only on the React frontend (no server persistence), so the second device never learns about the hide. Issue requests:
1. Per-conversation manual archive/unarchive endpoints (currently no such endpoints exist — only Brief 237's bulk inactive-sweep `POST /data-retention/archive-now`).
2. Listing endpoint for archived conversations.
3. Resolved escalations history view.

**Verified read-only — existing data model is half-built (Brief 237 established it for the bulk sweep):**

- **Email side:** `email_thread_state.json` per-thread `flags` dict supports `flags.deleted=true` to mean "archived/hidden from active inbox" (set by Brief 237's `archive_inactive_conversations` at `state_registry.py:2444`). `email_list_conversations` at `state_registry.py:1148` already filters: `if flags.get("deleted"): continue`. So email-side archive ALREADY works through the existing `flags.deleted` mechanism — there's just no per-conversation endpoint to set it manually.
- **WhatsApp side (verified, fully broken):** `conversation_status` table source schema at `wtyj/shared/state_registry.py:306-343` defines columns `(conversation_id, channel, status, updated_at, ai_muted, human_takeover_at, blocked)`. **There is NO `deleted` column** — verified by grep (`ALTER TABLE conversation_status ADD COLUMN deleted` returns zero hits in source) and by direct inspection of the live unboks SQLite schema (`PRAGMA table_info(conversation_status)` shows no `deleted` column). Brief 237's sweep at `state_registry.py:2470-2499` writes/reads from a column that does not exist — meaning Brief 237's WhatsApp-side bulk archive has been silently throwing `OperationalError: table conversation_status has no column named deleted` since it shipped. The bug went undetected because (a) `test_229_data_retention.py` only exercises the email path, never the WA branch, and (b) the surrounding code in `archive_inactive_conversations` doesn't have a try/except around the bad SQL — but the function is called from a HTTP handler that itself has a try/except (or the cron job that calls it just logs the error). **Brief 249 must add the missing `deleted` column via ALTER TABLE migration as a prerequisite for any of the new behavior to work.** Once added, the WA-side bulk sweep ALSO becomes operational for the first time.
- **Resolved escalations:** existing `GET /escalations` endpoint at `wtyj/dashboard/api.py:2014` already supports `?mode=soft|hard|all` filter (Brief 213). Adding `?status=resolved|sent|pending|all` is a 1-line extension of the same pattern. `state_registry.get_all_escalations()` at `state_registry.py:2047-2080` already returns the `status` field (column 8 of the SELECT).

**Verified — no naming conflict between "archive" and "delete" conceptually:**
- "Archive" = `flags.deleted=true` (email) / `conversation_status.deleted=1` (WhatsApp). Soft hide; rows stay in DB; recoverable via unarchive. Existing semantic per Brief 218 + Brief 237.
- "Delete" = `DELETE /messages/conversations/{phone}` endpoint at `api.py:1360` calls `wa_delete_conversation` (`state_registry.py:1322`) which HARD-removes rows from the DB. Destructive, no recovery. Different endpoint, different semantic.
- Brief 249 keeps both. Adds new `archive`/`unarchive` endpoints that toggle the existing `flags.deleted` / `conversation_status.deleted` value WITHOUT row removal. The `delete` endpoint is unchanged.

The naming overlap (`flags.deleted` actually means "archived") is unfortunate inherited tech debt from Brief 218; renaming the underlying flag is out of scope (would touch every list-filter site + Brief 237's sweep + tests). Brief 249 builds on the existing semantic; documents the naming-vs-meaning quirk in the new endpoint docstrings so future readers don't get confused.

## Why This Approach

**Considered:** Introduce a NEW `flags.archived` field for email + a NEW `conversation_status.archived` column for WhatsApp, separate from the existing `deleted` flag. **Rejected:** parallel flags with identical semantics is worse than one flag with mildly-confusing naming. Brief 218 + 237 already use `deleted`; `email_list_conversations` already filters on it; bulk sweep already writes it. Adding a parallel flag means updating every reader to check BOTH, plus a migration to populate the new flag from the old one — large surface for negligible naming improvement.

**Considered:** Add a single new endpoint `POST /messages/conversations/{conv_id}/state` accepting `{action: "archive"|"unarchive"|"delete"}` body. **Rejected:** RESTful convention favors verb-as-path-segment for state transitions (`/archive`, `/unarchive`, `/block`, `/unblock` already exist for blocked-conversation state at `api.py:2194,2207`). Two endpoints stays consistent with the existing pattern.

**Considered:** Extend the existing `GET /messages/conversations` with a `?archived=true` query param instead of a new path. **Rejected:** the existing endpoint returns the merged WA + email active list. Shifting to a query-param-driven dual-mode endpoint changes the response shape conditionally, which makes the frontend's React Query cache key more complex (separate URLs cache separately; same URL with different params can collide). New path `GET /messages/conversations/archived` is cleaner — same response shape, different list contents, separate cache key.

**Considered:** Make the `wa_list_conversations` filter-out-deleted change a separate brief. **Rejected:** issue #18 explicitly asks for cross-device archive consistency, and the WhatsApp listing being broken is the SECOND half of the bug Sonia/Calvin observed (the first half being lack of per-conversation endpoint). Both halves shipped together is a smaller behavioral change set than scattering across two briefs.

**Tradeoff — semantics for archiving an escalated conversation:** if a conversation has an active escalation (`conversation_status.status='open'`) AND the operator hits archive, what happens? Issue #18 says "Delete remains stronger than archive and should not block future prospect replies unless explicit block exists." Implication: archive is a UI-hide; the underlying escalation state stays open. Brief 249 follows this — archive sets the deleted flag without touching escalation status. The frontend can choose to gray-out archived-but-still-escalated rows in the Archived view. New customer messages on an archived conversation will trigger the existing escalation/poller flows untouched (the `flags.deleted=true` only affects LIST visibility, not message ingestion).

**Tradeoff — `unarchive` semantics:** unarchive sets the flag back to false (or removes the key). It does NOT restore prior escalation state — that was always preserved separately. The conversation simply re-appears in the active list.

## Instructions

### Step 0 — Add missing `deleted` column to `conversation_status` table

In `wtyj/shared/state_registry.py` find the existing migration block around lines 329-343 (where `ai_muted`, `human_takeover_at`, and `blocked` columns are added via try/except ALTER TABLE). Add a parallel migration for the missing `deleted` column:

```python
    try:
        conn.execute("ALTER TABLE conversation_status ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # already added
```

Insert it RIGHT AFTER the existing `blocked` column ALTER (around line 343) so all four optional columns sit together. The `try/except sqlite3.OperationalError: pass` pattern matches the existing migration style — first deploy adds the column; subsequent boots see the column already exists and the ALTER raises `duplicate column name: deleted` which gets swallowed.

**Why this MUST be Step 0, not Step 1:** Brief 237 has been writing to and reading from this non-existent column for ~weeks (since it shipped). The existing bulk-archive sweep is currently broken at runtime; Brief 249's `wa_set_archived` helper would crash on the same column. Without this migration, every Brief 249 test that touches WA archive (Tests 1, 2, 5) would fail with `OperationalError`.

**Side effect — Brief 237's WA-side sweep starts working for the first time.** This is the right behavior; the sweep was always intended to work. Document this in the deploy verification step: after deploy, the next nightly cron archive-now invocation will (a) succeed end-to-end on WA side instead of throwing, AND (b) start hiding inactive WA conversations from the active list (because Brief 249 also adds the LEFT JOIN filter at Step 2). Operators may see WA conversation count drop after the first sweep — that's the latent backlog finally taking effect.

### Step 1 — Add per-channel archive/unarchive helpers to `state_registry.py`

In `wtyj/shared/state_registry.py`, add after `email_list_conversations` (around line 1164, just before the `_find_email_thread_key_for` function at line 1206):

```python
def email_set_archived(thread_key: str, archived: bool) -> bool:
    """Brief 249: toggle the archive state on an email thread. Sets/clears
    flags.deleted in email_thread_state.json (the existing Brief 218 +
    Brief 237 'archived' semantic — the flag is named 'deleted' for
    historical reasons but semantically means 'hidden from active inbox',
    NOT hard-removed from storage). Returns True if the thread was found
    and updated; False if no matching thread_key in state."""
    path = _get_email_state_path()
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r") as f:
            state = json.load(f)
    except Exception:
        return False
    threads = state.get("threads") or {}
    th = threads.get(thread_key)
    if not th:
        return False
    flags = th.setdefault("flags", {})
    if archived:
        flags["deleted"] = True
    else:
        # Unarchive — remove the key entirely so a future re-read sees
        # the thread as never-archived (clean shape).
        flags.pop("deleted", None)
    try:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def wa_set_archived(conversation_id: str, archived: bool) -> bool:
    """Brief 249: toggle the archive state on a WhatsApp/IG/FB
    conversation. Sets/clears conversation_status.deleted (the existing
    Brief 218 + Brief 237 'archived' semantic). UPSERTs the
    conversation_status row when missing so manual archive works for
    conversations that have no prior status entry. Returns True when
    the row exists or was created; False only on DB error."""
    if not conversation_id:
        return False
    now = datetime.now(timezone.utc).isoformat()
    deleted_int = 1 if archived else 0
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO conversation_status "
            "(conversation_id, channel, status, updated_at, deleted) "
            "VALUES (?, 'whatsapp', ?, ?, ?) "
            "ON CONFLICT(conversation_id) DO UPDATE SET "
            "deleted = excluded.deleted, updated_at = excluded.updated_at",
            (conversation_id, "archived" if archived else "active",
             now, deleted_int))
        conn.commit()
    finally:
        conn.close()
    return True
```

Both helpers are intentionally simple — they toggle the existing flag/column without touching escalation state, ai_muted, blocked, or human_takeover_at.

### Step 2 — Fix `wa_list_conversations` to filter archived rows

In `wtyj/shared/state_registry.py:1342-1395` (`wa_list_conversations`), the current code returns all WhatsApp conversations regardless of `conversation_status.deleted`. Add the archive filter.

The current SQL at lines 1347-1355 is:

```python
    rows = conn.execute(
        "SELECT t.phone, t.text, t.created_at, t.role, t.channel "
        "FROM whatsapp_threads t "
        "INNER JOIN ("
        "  SELECT phone, MAX(created_at) as max_ts "
        "  FROM whatsapp_threads GROUP BY phone"
        ") latest ON t.phone = latest.phone AND t.created_at = latest.max_ts "
        "ORDER BY t.created_at DESC"
    ).fetchall()
```

Change to add a LEFT JOIN against `conversation_status` and exclude archived rows:

```python
    rows = conn.execute(
        "SELECT t.phone, t.text, t.created_at, t.role, t.channel "
        "FROM whatsapp_threads t "
        "INNER JOIN ("
        "  SELECT phone, MAX(created_at) as max_ts "
        "  FROM whatsapp_threads GROUP BY phone"
        ") latest ON t.phone = latest.phone AND t.created_at = latest.max_ts "
        # Brief 249: exclude conversations marked archived
        # (conversation_status.deleted=1 set by Brief 237's bulk sweep
        # OR by Brief 249's manual archive endpoint).
        "LEFT JOIN conversation_status cs ON t.phone = cs.conversation_id "
        "WHERE cs.deleted IS NULL OR cs.deleted = 0 "
        "ORDER BY t.created_at DESC"
    ).fetchall()
```

The `LEFT JOIN` + `IS NULL OR = 0` semantics preserve every conversation that doesn't have a `conversation_status` row at all (most active conversations). Only conversations with an explicit `deleted=1` row are excluded.

### Step 3 — Add `wa_list_archived_conversations` + `email_list_archived_conversations`

In `wtyj/shared/state_registry.py`, add two new helpers:

```python
def email_list_archived_conversations() -> list:
    """Brief 249: return email threads with flags.deleted=true (the
    inverse of email_list_conversations' filter). Same response shape
    as email_list_conversations so the frontend can swap the data
    source by URL without re-mapping fields."""
    path = _get_email_state_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            state = json.load(f)
    except Exception:
        return []
    threads = state.get("threads", {})
    result = []
    for thread_key, th in threads.items():
        messages = th.get("messages", []) or []
        if not messages:
            continue
        flags = th.get("flags", {}) or {}
        # Inverse filter: only archived (deleted=true) rows.
        if not flags.get("deleted"):
            continue
        last = messages[-1]
        last_ts = last.get("ts") or last.get("timestamp") or ""
        last_role = last.get("role", "")
        last_body = (last.get("body") or last.get("text") or "")[:200]
        if last_role == "customer":
            last_role = "user"
        elif last_role == "marina":
            last_role = "assistant"
        fields = th.get("fields", {}) or {}
        customer_name = fields.get("customer_name") or ""
        if not customer_name:
            parts = thread_key.split(":", 2)
            if len(parts) >= 2:
                customer_name = parts[1]
        result.append({
            "phone": f"email::{thread_key}",
            "customer_name": customer_name or "(email customer)",
            "last_message": last_body,
            "last_message_role": last_role,
            "last_message_at": last_ts,
            "status": "archived",
            "message_count": len(messages),
            "channel": "email",
        })
    result.sort(key=lambda r: r["last_message_at"] or "", reverse=True)
    return result


def wa_list_archived_conversations() -> list:
    """Brief 249: return WhatsApp/IG/FB conversations with
    conversation_status.deleted=1 (the inverse of wa_list_conversations'
    new Brief 249 filter). Same response shape as wa_list_conversations."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT t.phone, t.text, t.created_at, t.role, t.channel "
        "FROM whatsapp_threads t "
        "INNER JOIN ("
        "  SELECT phone, MAX(created_at) as max_ts "
        "  FROM whatsapp_threads GROUP BY phone"
        ") latest ON t.phone = latest.phone AND t.created_at = latest.max_ts "
        "INNER JOIN conversation_status cs ON t.phone = cs.conversation_id "
        "WHERE cs.deleted = 1 "
        "ORDER BY t.created_at DESC"
    ).fetchall()
    conversations = []
    for r in rows:
        phone = r[0]
        state_row = conn.execute(
            "SELECT fields_json, flags_json FROM whatsapp_booking_state "
            "WHERE phone = ?", (phone,)
        ).fetchone()
        fields = json.loads(state_row[0] or "{}") if state_row else {}
        name = (fields.get("customer_name") or fields.get("name") or "")
        if not name:
            sender_row = conn.execute(
                "SELECT sender_name FROM whatsapp_threads WHERE phone = ? "
                "AND role = 'user' AND sender_name != '' "
                "ORDER BY created_at DESC LIMIT 1", (phone,)
            ).fetchone()
            if sender_row and sender_row[0]:
                name = sender_row[0]
        if not name:
            name = phone
        count_row = conn.execute(
            "SELECT COUNT(*) FROM whatsapp_threads WHERE phone = ?", (phone,)
        ).fetchone()
        conversations.append({
            "phone": phone,
            "customer_name": name,
            "last_message": (r[1] or "")[:200],
            "last_message_role": r[3] or "",
            "last_message_at": r[2] or "",
            "status": "archived",
            "message_count": count_row[0] if count_row else 0,
            "channel": r[4] if len(r) > 4 and r[4] else "whatsapp",
        })
    conn.close()
    return conversations
```

### Step 4 — Add 3 new endpoints + extend `GET /escalations` with status filter

In `wtyj/dashboard/api.py`, add after the existing `GET /messages/conversations` (line 1287-1300):

```python
@router.get("/messages/conversations/archived",
             dependencies=[Depends(_check_auth)])
async def list_archived_conversations():
    """Brief 249: return archived WhatsApp + email conversations merged.
    Same response shape as GET /messages/conversations so the frontend
    can swap data source by URL. Cross-device-consistent because the
    archive state is server-side (email flags.deleted +
    conversation_status.deleted)."""
    wa = state_registry.wa_list_archived_conversations()
    for c in wa:
        c.setdefault("channel", "whatsapp")
    email = state_registry.email_list_archived_conversations()
    merged = wa + email
    merged.sort(key=lambda r: r.get("last_message_at") or "", reverse=True)
    return merged


@router.post("/messages/conversations/{conversation_id:path}/archive",
              dependencies=[Depends(_check_auth)])
async def archive_conversation(conversation_id: str):
    """Brief 249: per-conversation manual archive. Email conv_id starts
    with 'email::<thread_key>'; WhatsApp/IG/FB uses the bare phone/conv
    id. Sets the existing 'archived' flag (flags.deleted for email,
    conversation_status.deleted=1 for WhatsApp). Idempotent — archiving
    an already-archived conversation succeeds without error.

    Returns {"ok": true, "conversationId": ..., "channel": "email"|"whatsapp",
    "archived": true}. 404 if email thread_key matches no thread."""
    if conversation_id.startswith("email::"):
        thread_key = conversation_id[len("email::"):]
        ok = state_registry.email_set_archived(thread_key, True)
        if not ok:
            raise HTTPException(
                status_code=404,
                detail="email thread not found")
        return {"ok": True, "conversationId": conversation_id,
                "channel": "email", "archived": True}
    state_registry.wa_set_archived(conversation_id, True)
    return {"ok": True, "conversationId": conversation_id,
            "channel": "whatsapp", "archived": True}


@router.post("/messages/conversations/{conversation_id:path}/unarchive",
              dependencies=[Depends(_check_auth)])
async def unarchive_conversation(conversation_id: str):
    """Brief 249: per-conversation manual unarchive. Inverse of
    archive_conversation. Idempotent — unarchiving a not-archived
    conversation succeeds without error."""
    if conversation_id.startswith("email::"):
        thread_key = conversation_id[len("email::"):]
        ok = state_registry.email_set_archived(thread_key, False)
        if not ok:
            raise HTTPException(
                status_code=404,
                detail="email thread not found")
        return {"ok": True, "conversationId": conversation_id,
                "channel": "email", "archived": False}
    state_registry.wa_set_archived(conversation_id, False)
    return {"ok": True, "conversationId": conversation_id,
            "channel": "whatsapp", "archived": False}
```

In `wtyj/dashboard/api.py:2014-2024` (`list_escalations`), extend the existing endpoint signature with a `status` query param:

```python
@router.get("/escalations", dependencies=[Depends(_check_auth)])
async def list_escalations(mode: str = None, status: str = None):
    """List all escalation notifications.
    Brief 210 hotfix: SR's frontend mapper requires string ids.
    Brief 213: support ?mode=soft|hard|all (all = no filter).
    Brief 249: support ?status=resolved|sent|pending|replied|all
    so the frontend can render a Resolved/History view."""
    rows = state_registry.get_all_escalations()
    for r in rows:
        r["id"] = str(r["id"])
    if mode in ("soft", "hard"):
        rows = [r for r in rows if r.get("mode") == mode]
    if status and status != "all":
        rows = [r for r in rows if r.get("status") == status]
    return rows
```

### Step 5 — Add 6 new tests

Create `wtyj/tests/social/test_249_server_side_archive.py`:

```python
"""Brief 249: per-conversation manual archive/unarchive endpoints
+ archived-conversations listing + WhatsApp listing filter regression
+ resolved escalations history filter."""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from fastapi.testclient import TestClient
from agents.social.webhook_server import app

client = TestClient(app)


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _wipe_wa_phone(phone: str):
    from shared import state_registry
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM conversation_status WHERE conversation_id = ?",
                 (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?",
                 (phone,))
    conn.commit()
    conn.close()


def test_archive_whatsapp_excludes_from_active_list_and_includes_in_archived():
    """Brief 249: POST /archive on a WhatsApp conv removes it from
    /messages/conversations and adds it to /messages/conversations/archived."""
    from shared import state_registry
    phone = "249_wa_archive_test_phone"
    _wipe_wa_phone(phone)
    state_registry.wa_store_message(phone, "user", "[QA] hello")

    token = _login()
    # Pre-archive: phone IS in active list
    r = client.get("/dashboard/api/messages/conversations", headers=_auth(token))
    assert r.status_code == 200
    assert any(c["phone"] == phone for c in r.json()), \
        "expected phone in active list before archive"

    # Archive
    r = client.post(f"/dashboard/api/messages/conversations/{phone}/archive",
                     headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["archived"] is True
    assert body["channel"] == "whatsapp"

    # Post-archive: NOT in active list
    r = client.get("/dashboard/api/messages/conversations", headers=_auth(token))
    assert not any(c["phone"] == phone for c in r.json()), \
        "phone must be excluded from active list after archive"

    # Post-archive: IS in archived list
    r = client.get("/dashboard/api/messages/conversations/archived",
                    headers=_auth(token))
    assert r.status_code == 200
    assert any(c["phone"] == phone for c in r.json()), \
        "phone must appear in archived list"

    _wipe_wa_phone(phone)


def test_unarchive_whatsapp_restores_to_active_list():
    """Brief 249: POST /unarchive flips it back to active."""
    from shared import state_registry
    phone = "249_wa_unarchive_test_phone"
    _wipe_wa_phone(phone)
    state_registry.wa_store_message(phone, "user", "[QA] hello")
    state_registry.wa_set_archived(phone, True)

    token = _login()
    r = client.post(
        f"/dashboard/api/messages/conversations/{phone}/unarchive",
        headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["archived"] is False

    r = client.get("/dashboard/api/messages/conversations", headers=_auth(token))
    assert any(c["phone"] == phone for c in r.json()), \
        "phone must reappear in active list after unarchive"
    _wipe_wa_phone(phone)


def test_archive_email_thread_excludes_and_includes(monkeypatch, tmp_path):
    """Brief 249: archive on an email::thread_key conv toggles flags.deleted
    in email_thread_state.json. Uses tmp_path to isolate the test from
    real production state."""
    from shared import state_registry
    fake_state = {
        "threads": {
            "subj:bob@x.com:test 249": {
                "messages": [{"role": "customer", "ts": "2026-05-10T00:00:00+00:00",
                              "body": "[QA] test"}],
                "fields": {"customer_name": "Bob 249"},
                "flags": {},
            }
        }
    }
    state_path = tmp_path / "email_thread_state.json"
    state_path.write_text(json.dumps(fake_state))
    monkeypatch.setattr(state_registry, "_get_email_state_path",
                         lambda: str(state_path))

    token = _login()
    conv_id = "email::subj:bob@x.com:test 249"

    # Pre-archive: in active list
    r = client.get("/dashboard/api/messages/conversations", headers=_auth(token))
    assert any(c["phone"] == conv_id for c in r.json()), \
        "expected email conv in active list before archive"

    # Archive
    r = client.post(
        f"/dashboard/api/messages/conversations/{conv_id}/archive",
        headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["channel"] == "email"

    # Post-archive: gone from active, present in archived
    r = client.get("/dashboard/api/messages/conversations", headers=_auth(token))
    assert not any(c["phone"] == conv_id for c in r.json())
    r = client.get("/dashboard/api/messages/conversations/archived",
                    headers=_auth(token))
    assert any(c["phone"] == conv_id for c in r.json())


def test_archive_email_404_when_thread_key_missing(monkeypatch, tmp_path):
    """Brief 249: archive on a non-existent email thread_key returns 404."""
    from shared import state_registry
    state_path = tmp_path / "email_thread_state.json"
    state_path.write_text(json.dumps({"threads": {}}))
    monkeypatch.setattr(state_registry, "_get_email_state_path",
                         lambda: str(state_path))

    token = _login()
    r = client.post(
        "/dashboard/api/messages/conversations/email::nonexistent/archive",
        headers=_auth(token))
    assert r.status_code == 404
    assert "not found" in r.json()["detail"]


def test_wa_list_conversations_filters_brief_237_archived_rows():
    """Brief 249 regression fix: Brief 237's bulk archive sweep marked
    WhatsApp rows with conversation_status.deleted=1 + status='archived'
    but pre-Brief-249 wa_list_conversations did NOT filter on this flag,
    so archived rows stayed in the active list. After Brief 249's LEFT
    JOIN filter, they're correctly excluded."""
    from shared import state_registry
    phone = "249_wa_brief237_filter_phone"
    _wipe_wa_phone(phone)
    state_registry.wa_store_message(phone, "user", "[QA] hi")
    # Simulate Brief 237's archive-now sweep result
    state_registry.wa_set_archived(phone, True)

    token = _login()
    r = client.get("/dashboard/api/messages/conversations", headers=_auth(token))
    assert not any(c["phone"] == phone for c in r.json()), \
        "Brief 237's archived row must be excluded from wa_list_conversations"
    _wipe_wa_phone(phone)


def test_get_escalations_status_filter_returns_only_resolved():
    """Brief 249: GET /escalations?status=resolved returns only
    notification rows whose status='resolved'. Other statuses excluded."""
    from shared import state_registry
    # Create one escalation, leave it pending (default).
    cust_pending = "249_resolved_filter_pending@example.com"
    eid_pending = state_registry.create_pending_notification(
        notification_type="escalation", channel="email",
        customer_id=cust_pending, customer_name="Pending Test",
        subject="[ESCALATION] pending", body="body", mode="hard")
    # Create another and mark it resolved.
    cust_resolved = "249_resolved_filter_resolved@example.com"
    eid_resolved = state_registry.create_pending_notification(
        notification_type="escalation", channel="email",
        customer_id=cust_resolved, customer_name="Resolved Test",
        subject="[ESCALATION] resolved", body="body", mode="hard")
    state_registry.update_notification_status(eid_resolved, "resolved")

    try:
        token = _login()
        r = client.get("/dashboard/api/escalations?status=resolved",
                        headers=_auth(token))
        assert r.status_code == 200
        rows = r.json()
        ids = [r["id"] for r in rows]
        assert str(eid_resolved) in ids, \
            "resolved escalation must be in status=resolved filter"
        assert str(eid_pending) not in ids, \
            "non-resolved escalation must NOT appear when status=resolved"
    finally:
        # try/finally guarantees cleanup runs even if an assertion fails;
        # otherwise dev DB accumulates rows on every re-run.
        conn = state_registry._get_conn()
        conn.execute("DELETE FROM pending_notifications WHERE id IN (?, ?)",
                     (eid_pending, eid_resolved))
        conn.commit()
        conn.close()
```

**Test design notes:**
- Tests 1, 2, 5 use real DB + clean up before/after to avoid cross-test pollution. The `_wipe_wa_phone` helper handles 3 tables (whatsapp_threads, conversation_status, whatsapp_booking_state).
- Tests 3, 4 use `monkeypatch` + `tmp_path` to isolate email_thread_state.json from real production state — the dev DB's email file may have unrelated threads.
- Test 6 uses real DB + cleanup. The `update_notification_status` helper at `state_registry.py` exists and is the canonical way to mark resolved.
- All tests reuse the existing `_login()` + `_auth(token)` pattern from other test files (mirrors `test_213_escalation_control.py:23-29`).

### Step 6 — Out of scope (documented for future briefs)

- **Renaming `flags.deleted` to `flags.archived`** — purely cosmetic; would touch the bulk sweep + multiple list filters + tests + Brief 218's existing semantic. Future cleanup brief.
- **Pagination on the archived list** — initial implementation returns all archived; if archived volume grows past ~500 rows we add `?limit=&offset=`. Defer until needed.
- **Auto-unarchive on new customer message** — issue #18 says "Delete remains stronger than archive and should not block future prospect replies." The current archive implementation doesn't block ingestion (`flags.deleted` only affects LIST visibility, NOT message processing). A new customer message arriving on an archived conversation today would still trigger Marina + escalation flows. Whether the conversation should auto-unarchive on new inbound activity is a product decision; defer.
- **Frontend integration** — SR's React app needs to call the new endpoints + render the archived view. Backend contract documented in OUTPUT.
- **Bulk archive endpoint** (operator selects N conversations, archives all) — convenience UX; defer until operators ask.

## Tests

6 new tests in `wtyj/tests/social/test_249_server_side_archive.py` (NEW file).

Expected after-test count: **1070 passing / 0 failures** (1064 baseline post-Brief-248 verified by `python3 -m pytest wtyj/tests/ -q` at start of this brief + 6 new = 1070). Note: MEMORY.md says 1015 — that's stale (post-Brief-237 baseline); current baseline is 1064 after Briefs 238-248 shipped 49 net new tests.

## Success Condition

After this brief lands:
1. `POST /dashboard/api/messages/conversations/{conv_id}/archive` accepts both `email::...` and bare-phone formats; returns 200 with `{ok, conversationId, channel, archived: true}`.
2. `POST /dashboard/api/messages/conversations/{conv_id}/unarchive` mirrors the archive endpoint with `archived: false`.
3. `GET /dashboard/api/messages/conversations` excludes archived conversations (both email + WhatsApp).
4. `GET /dashboard/api/messages/conversations/archived` returns ONLY archived conversations (both channels merged).
5. `GET /dashboard/api/escalations?status=resolved` returns only resolved escalation rows.
6. Brief 237's WhatsApp-side bulk archive sweep now actually hides the rows from the active list (was silently broken pre-Brief-249).
7. Existing endpoints behavior preserved: email DELETE (`api.py:1360`), bulk archive-now (`api.py:922`), block/unblock (`api.py:2194,2207`) all unchanged.
8. 1070 tests passing.

## Frontend contract for SR

**Endpoints (no breaking changes; all additive):**
- `POST /dashboard/api/messages/conversations/{conv_id:path}/archive` — body empty; auth required.
- `POST /dashboard/api/messages/conversations/{conv_id:path}/unarchive` — same.
- `GET /dashboard/api/messages/conversations/archived` — same shape as the existing `/messages/conversations` endpoint; entries have `status="archived"`.
- `GET /dashboard/api/escalations?status=resolved` (also `?status=sent`, `?status=pending`, `?status=all`) — extends the existing endpoint; backward compatible (no status param = all).

**Cross-device consistency:** archive state is now persisted in:
- Email: `email_thread_state.json` per-thread `flags.deleted` (existing field; same semantic Brief 237 uses).
- WhatsApp: `conversation_status.deleted` column (existing column; same semantic Brief 237 uses).

The frontend's React app should:
1. Replace its `localStorage` archive state with calls to the new endpoints.
2. Call `GET /messages/conversations` for the active inbox (excludes archived).
3. Call `GET /messages/conversations/archived` for the Archived view.
4. Call `POST .../{id}/archive` from the archive button; refresh the active list afterward.
5. Optionally call `POST .../{id}/unarchive` from the archived view's restore button.
6. Call `GET /escalations?status=resolved` for the Resolved/History view.

The naming of the underlying flag (`deleted` rather than `archived`) is invisible to the frontend — the API uses `archived` consistently in URLs and response bodies.

## Rollback

```
git revert <brief-249-commit-sha>
git push origin main
```

This removes the 3 new endpoints + the `?status=` filter on `/escalations` + the `wa_list_conversations` LEFT JOIN filter (so Brief 237's WhatsApp archives go back to being silently visible). Existing data is preserved — the `flags.deleted` and `conversation_status.deleted` values stay in storage; they just stop being read by the listing endpoint and stop being writable via the new endpoints. Frontend reverts to localStorage-only archive (the pre-Brief-249 broken state). CI re-deploys in ~90s.
