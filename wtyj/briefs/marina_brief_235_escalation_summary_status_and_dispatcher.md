# BRIEF 235 — Fix Brief 227 escalation summary in production
**Status:** Draft | **Files:** `wtyj/shared/state_registry.py`, `wtyj/dashboard/api.py`, `wtyj/agents/marina/email_poller.py`, `wtyj/shared/escalation_dispatcher.py` (new), `wtyj/tests/social/test_235_escalation_summary_fix.py` | **Depends on:** Brief 217 (alert dispatcher transitions `pending → sent`), Brief 227 (escalation summary generator + dispatcher pattern + dedup) | **Blocks:** unboks dashboard rendering real escalation summaries instead of the generic frontend fallback

## Context

Brief 227 shipped the decision-first escalation summary. SR reported the dashboard is showing the generic frontend-fallback text ("Agent needs help / Calvin sent a message your Agent is unsure how to answer / ...") instead of the structured AI-generated briefing the brief promised. Production diagnosis found two real bugs.

### Bug 1: status filter mismatch

`state_registry.get_active_escalation_summary_for(customer_id)` at `state_registry.py:1853-1875` filters with `WHERE status = 'pending'`. But pending_notifications rows transition `pending → sent` immediately when Brief 217's `_fire_escalation_alerts` dispatcher fires (right after the row insert in `create_pending_notification`). Then `replied` once an operator answers via `/escalations/{id}/reply` (Brief 210, line 1800) which calls `update_notification_status(escalation_id, "replied")`.

Production query confirms zero rows have `status='pending'` on unboks:
```
distinct statuses: [('sent',), ('replied',)]
```

Same wrong filter exists at `state_registry.py:1389` inside `create_pending_notification`'s dedup check — meaning Brief 227's "one active unresolved escalation per conversation" rule never fires either, allowing duplicate rows to accumulate.

### Bug 2: dispatcher not registered in email_poller process

Brief 227 registers `_summary_dispatcher` at `dashboard/api.py:1671` via `state_registry.set_summary_dispatcher(_generate_escalation_summary)`. This runs at module-load time. The `webhook_server` process imports `dashboard.api` at startup (it mounts the router) so the dispatcher is live there — WhatsApp/IG/FB inbound messages flowing through `_process_zernio_event` → `create_pending_notification` correctly fire the summary generator.

The `email_poller` is a separate supervisord-managed process. It imports `state_registry` directly but never imports `dashboard.api`, so `state_registry._summary_dispatcher` stays `None` in this process. When the email poller's `create_pending_notification` runs (e.g., from `dm_agent` escalation path on email-channel rows, or from email_poller's own escalation creation) the dispatcher is None and the conditional at `state_registry.py:1429` short-circuits — `escalation_summary` stays NULL.

Production confirmation:
- WhatsApp escalation rows 10, 11, 12, 13 (Charlotte, post-Brief-227, via webhook_server): `escalation_summary` populated.
- Email escalation rows 8, 9 (calvin@gaimin.io and calvinadamus@gmail.com, post-Brief-227, via email_poller): `escalation_summary IS NULL`.

### Bug 3 (out of scope): pre-Brief-227 rows have null summaries

Rows 1–7 predate Brief 227's deploy. They have null summaries because the column didn't exist yet (well, ALTER added it after the fact, so existing rows got NULL). These are old escalations and will resolve naturally as operators reply. Skip backfill.

## Why This Approach

**Chosen — bug 1:** change the status filter in BOTH locations (`state_registry.py:1389` dedup and `state_registry.py:1866` readback) from `status = 'pending'` to `status IN ('pending', 'sent')`. "Active unresolved" semantically means "the operator has not yet answered" — `pending` (transient pre-alert state) plus `sent` (alert dispatched, awaiting operator) both qualify. `replied` is the explicit operator-answered state and stays excluded.

**Chosen — bug 2:** extract `_generate_escalation_summary` and the `state_registry.set_summary_dispatcher(...)` registration call from `dashboard/api.py` into a new `wtyj/shared/escalation_dispatcher.py`. Module-load side effect: importing `shared.escalation_dispatcher` calls `state_registry.set_summary_dispatcher(_generate_escalation_summary)`, registering the dispatcher in whatever process imports it. Both `dashboard/api.py` (via `from shared import escalation_dispatcher  # noqa: F401`) and `email_poller.py` import it at module load. Each process registers independently.

**Why a new shared module, not "import dashboard.api from email_poller".** `dashboard/api.py` is heavy — pulls in FastAPI, Pydantic, all 70+ endpoint handlers, photo libs, etc. Importing it from the email_poller process would balloon startup time and mix dashboard-only deps into the poller. The dispatcher wrapper is ~60 lines; extracting it into a tiny shared module is a clean fix. `dashboard/api.py` also imports the new module to register its own dispatcher — same registration code, same behavior, no duplication.

**Why "side-effect import" is acceptable here.** Side-effect imports are usually a smell (testability, subtle ordering bugs). For dispatcher registration in a single-purpose module that exists ONLY to register the dispatcher, the side effect IS the purpose. The module body is two function definitions and one `set_summary_dispatcher(...)` call — nothing else. Equivalent to Brief 217's `set_alert_dispatcher` registration which is also a side effect at `dashboard/api.py:1598` and works the same way.

**Tradeoff: in tests where state_registry is imported but neither dashboard.api nor shared.escalation_dispatcher is imported, the dispatcher stays None.** That matches the pre-fix behavior — tests that don't load dashboard never had a dispatcher. New regression tests for Brief 235 explicitly import `shared.escalation_dispatcher` to validate the registration side effect.

**Rejected — bug 1:** matching by `conversation_status.status` instead of pending_notifications.status. Cleaner semantically (the "is escalation unresolved" question lives in conversation_status), but adds a JOIN to a hot path query. The two-value enum match (`pending`, `sent`) is the simplest correct filter.

**Rejected — bug 2:** moving registration to `state_registry.py` itself with a default dispatcher. Couples state_registry to dashboard.escalation_summary which depends on Anthropic. State registry should stay Claude-agnostic (the Brief 217/227 design). The shared dispatcher module is the right layering — state_registry exposes the registration setter, shared/escalation_dispatcher.py is the registrant.

**Rejected — bug 3 backfill:** writing a one-shot script to walk pre-Brief-227 rows and regenerate summaries. Real cost is the Claude API calls for old conversations whose context is now stale. Not worth it; old escalations will resolve.

## Instructions

### 1. Create `wtyj/shared/escalation_dispatcher.py`

NEW FILE. Move the `_generate_escalation_summary` wrapper + the `set_summary_dispatcher` call out of `dashboard/api.py:1609-1671` into this module. Adjust import path for `escalation_summary` since it lives in `dashboard/`.

```python
"""Brief 235: shared registrant for the Brief 227 escalation summary
dispatcher. Importing this module triggers
`state_registry.set_summary_dispatcher(...)` as a load-time side effect,
so any process that imports it gets the dispatcher live.

The dashboard webhook process imports it via `dashboard/api.py`. The
email poller process imports it directly at the top of
`agents/marina/email_poller.py`. Each process gets its own registration
(globals are per-process; the side effect runs per import in each).
"""
from shared import state_registry
from dashboard import escalation_summary as _esc_summary


def _generate_escalation_summary(escalation_id: int, channel: str,
                                  customer_id: str, customer_name: str) -> dict:
    """Brief 227: dispatcher wrapper. Loads the relevant conversation history
    for this channel, calls the Claude generator, returns the dict (or None).
    Brief 235: extracted from dashboard/api.py to be importable from
    email_poller without pulling in FastAPI."""
    try:
        mode = state_registry.get_active_escalation_mode(customer_id)
    except Exception:
        mode = None

    history = []
    try:
        if channel == "email":
            thread_key = state_registry._find_email_thread_key_for(customer_id)
            if thread_key:
                detail = state_registry.email_get_conversation(thread_key)
                history = detail.get("messages", []) or []
        elif channel in ("instagram", "facebook", "messenger"):
            history = state_registry.dm_get_history(customer_id, channel,
                                                     limit=20)
        else:  # whatsapp + anything else
            history = state_registry.wa_get_full_history(customer_id, limit=20)
    except Exception:
        history = []

    summary_dict = _esc_summary.generate_summary(
        channel=channel,
        customer_id=customer_id,
        customer_name=customer_name,
        mode=mode,
        history=history,
    )

    # Brief 228: best-effort appointment row write. Only fires when the
    # summary indicates scheduling intent. Failure here never blocks
    # summary persistence.
    if summary_dict:
        try:
            details = (summary_dict.get("extractedDetails") or {})
            if details.get("intent") == "scheduling":
                proposed = details.get("proposedTimes") or []
                topic = details.get("topic") or "Meeting"
                if channel == "email":
                    thread_key = state_registry._find_email_thread_key_for(customer_id)
                    conv_id = f"email::{thread_key}" if thread_key else customer_id
                else:
                    conv_id = customer_id
                status = ("pending_team_confirmation"
                          if proposed else "detected")
                state_registry.appointment_upsert(
                    conversation_id=conv_id,
                    channel=channel,
                    customer_name=customer_name or "",
                    title=topic,
                    proposed_times=proposed,
                    status=status,
                )
        except Exception:
            pass

    return summary_dict


# Side-effect registration: importing this module installs the dispatcher
# in this process's state_registry global. Brief 235.
state_registry.set_summary_dispatcher(_generate_escalation_summary)
```

### 2. `wtyj/dashboard/api.py` — replace inline dispatcher with import

Find the block at lines 1600-1671 (the `# ── Brief 227: Escalation summary generator ──` comment through `state_registry.set_summary_dispatcher(_generate_escalation_summary)`). Replace the entire block with:

```python
# ── Brief 227 + 235: Escalation summary generator ───────────────────────────
# Wrapper + dispatcher registration moved to shared/escalation_dispatcher.py
# in Brief 235 so the email_poller process can also register the dispatcher
# without pulling in dashboard.api's FastAPI dependency tree.
from shared import escalation_dispatcher  # noqa: F401  (side-effect import)
```

This drops ~70 lines from dashboard/api.py and replaces them with one import. The `noqa: F401` suppresses the unused-import lint warning since the import IS the purpose.

### 3. `wtyj/agents/marina/email_poller.py` — register the dispatcher

At the top of the file, after the existing `from shared import state_registry` (around line 13-15), add:

```python
# Brief 235: register the Brief 227 escalation summary dispatcher in this
# process. The side-effect import installs _generate_escalation_summary
# as state_registry._summary_dispatcher so escalations created by the
# email poller get summaries generated (matches the webhook_server
# process which registers the same dispatcher via dashboard.api).
from shared import escalation_dispatcher  # noqa: F401
```

(Verify the actual import block by reading lines 12-20 of email_poller.py first; place the new import alongside the other shared imports.)

### 4. `wtyj/shared/state_registry.py` — fix the two status filters

**Site A:** `state_registry.py:1389` inside `create_pending_notification`'s dedup check. Change:

```python
        existing = conn.execute(
            "SELECT id FROM pending_notifications "
            "WHERE customer_id = ? AND notification_type = 'escalation' "
            "AND status = 'pending' "
            "ORDER BY created_at DESC LIMIT 1",
            (customer_id,)).fetchone()
```

to:

```python
        existing = conn.execute(
            "SELECT id FROM pending_notifications "
            "WHERE customer_id = ? AND notification_type = 'escalation' "
            "AND status IN ('pending', 'sent') "
            "ORDER BY created_at DESC LIMIT 1",
            (customer_id,)).fetchone()
```

**Site B:** `state_registry.py:1866` inside `get_active_escalation_summary_for`. Change:

```python
    row = conn.execute(
        "SELECT escalation_summary FROM pending_notifications "
        "WHERE customer_id = ? AND notification_type = 'escalation' "
        "AND status = 'pending' "
        "ORDER BY created_at DESC LIMIT 1",
        (customer_id,)).fetchone()
```

to:

```python
    row = conn.execute(
        "SELECT escalation_summary FROM pending_notifications "
        "WHERE customer_id = ? AND notification_type = 'escalation' "
        "AND status IN ('pending', 'sent') "
        "ORDER BY created_at DESC LIMIT 1",
        (customer_id,)).fetchone()
```

Both filters now treat any non-`replied` notification as "active unresolved." `replied` is the explicit "operator answered" state — it stays excluded.

## Tests

Place at `wtyj/tests/social/test_235_escalation_summary_fix.py`:

```python
"""Tests for Brief 235 — escalation summary readback works on production
data shape (status='sent') and dispatcher registers in the email_poller
process via the shared module side-effect import."""
import json
from unittest.mock import patch

from shared import state_registry


def _reset(prefix: str = "test235"):
    conn = state_registry._get_conn()
    conn.execute(
        "DELETE FROM pending_notifications WHERE customer_id LIKE ?",
        (f"{prefix}%",))
    conn.execute(
        "DELETE FROM conversation_status WHERE conversation_id LIKE ?",
        (f"{prefix}%",))
    conn.commit()
    conn.close()


def _insert_escalation(customer_id: str, status: str, summary_dict=None):
    """Insert directly to bypass the dispatcher — we want to test the
    READBACK on a row whose status reflects production reality."""
    from datetime import datetime, timezone
    conn = state_registry._get_conn()
    conn.execute(
        "INSERT INTO pending_notifications "
        "(notification_type, channel, customer_id, customer_name, "
        "subject, body, status, created_at, escalation_summary) "
        "VALUES ('escalation', 'whatsapp', ?, 'Test', 'subj', 'body', ?, ?, ?)",
        (customer_id, status,
         datetime.now(timezone.utc).isoformat(),
         json.dumps(summary_dict) if summary_dict else None))
    conn.commit()
    conn.close()


def test_readback_finds_sent_row_with_summary():
    """Brief 235: get_active_escalation_summary_for must return the
    summary for a row with status='sent' (the actual production state
    after Brief 217's alert dispatcher transitions pending → sent)."""
    _reset()
    customer_id = "test235-alice@example.com"
    summary = {
        "reason": "Alice wants to schedule a call",
        "customerWants": "Activation meeting",
        "operatorNeedsToDecide": "Confirm time",
        "recommendedOptions": ["Confirm Thursday 09:00"],
        "extractedDetails": {"intent": "scheduling",
                             "proposedTimes": ["Thursday 09:00"],
                             "topic": "activation call"},
    }
    _insert_escalation(customer_id, status="sent", summary_dict=summary)
    result = state_registry.get_active_escalation_summary_for(customer_id)
    assert result is not None
    assert result["customerWants"] == "Activation meeting"
    assert result["recommendedOptions"] == ["Confirm Thursday 09:00"]


def test_readback_still_finds_pending_row():
    """Brief 235: backward compat — 'pending' rows (rare race window
    between insert and dispatcher) still match the new IN filter."""
    _reset()
    customer_id = "test235-bob@example.com"
    summary = {"reason": "Bob's escalation", "customerWants": "x",
               "operatorNeedsToDecide": "y", "recommendedOptions": [],
               "extractedDetails": {"intent": "other",
                                    "proposedTimes": [], "topic": "z"}}
    _insert_escalation(customer_id, status="pending", summary_dict=summary)
    result = state_registry.get_active_escalation_summary_for(customer_id)
    assert result is not None
    assert result["reason"] == "Bob's escalation"


def test_readback_skips_replied_row():
    """Brief 235: 'replied' rows are explicit operator-answered state
    and must NOT show up as active escalations. Tests the EXCLUSION
    side of the new IN filter."""
    _reset()
    customer_id = "test235-carol@example.com"
    summary = {"reason": "old", "customerWants": "x",
               "operatorNeedsToDecide": "y", "recommendedOptions": [],
               "extractedDetails": {"intent": "other",
                                    "proposedTimes": [], "topic": "z"}}
    _insert_escalation(customer_id, status="replied", summary_dict=summary)
    result = state_registry.get_active_escalation_summary_for(customer_id)
    assert result is None


def test_dedup_updates_existing_sent_row():
    """Brief 235: when a customer triggers a second escalation while one
    is still 'sent' (alert fired but operator hasn't replied), dedup
    must UPDATE the existing row instead of inserting a new one."""
    _reset()
    customer_id = "test235-dan@example.com"
    _insert_escalation(customer_id, status="sent")
    # Capture the count before the second escalation.
    conn = state_registry._get_conn()
    before = conn.execute(
        "SELECT COUNT(*) FROM pending_notifications WHERE customer_id = ?",
        (customer_id,)).fetchone()[0]
    conn.close()
    assert before == 1

    # Patch the dispatchers to no-ops so we test only the dedup branch.
    with patch.object(state_registry, "_alert_dispatcher", None), \
         patch.object(state_registry, "_summary_dispatcher", None):
        new_id = state_registry.create_pending_notification(
            notification_type="escalation",
            channel="whatsapp",
            customer_id=customer_id,
            customer_name="Dan",
            subject="second escalation",
            body="another alert body")

    conn = state_registry._get_conn()
    after = conn.execute(
        "SELECT COUNT(*), MAX(subject) FROM pending_notifications "
        "WHERE customer_id = ?", (customer_id,)).fetchone()
    conn.close()
    # Row count unchanged — dedup did UPDATE not INSERT.
    assert after[0] == 1
    assert after[1] == "second escalation"


def test_shared_dispatcher_module_registers_on_import():
    """Brief 235: importing shared.escalation_dispatcher installs the
    summary generator in this process. Validates the side-effect import
    pattern that fixes the email_poller process."""
    # Force a clean None state, then import the shared module fresh.
    state_registry._summary_dispatcher = None
    assert state_registry._summary_dispatcher is None

    # Reload to trigger the side effect.
    import importlib
    from shared import escalation_dispatcher
    importlib.reload(escalation_dispatcher)

    assert state_registry._summary_dispatcher is not None
    # Smoke-check it's the wrapper, not some test detritus.
    assert state_registry._summary_dispatcher.__name__ == "_generate_escalation_summary"
```

## Success Condition

After deploy:
- `get_active_escalation_summary_for(customer_id)` returns the parsed summary for any escalation in `pending` OR `sent` state (not just `pending`).
- `create_pending_notification`'s dedup updates the existing row when a customer triggers a second escalation while the first is still `sent`.
- `email_poller`'s process has `state_registry._summary_dispatcher` set (verified via `docker exec wtyj-unboks python3 -c "import sys; sys.path.insert(0,'/app'); from shared import state_registry; from shared import escalation_dispatcher; print(state_registry._summary_dispatcher)"`).
- New email-channel escalations created on unboks ship with `escalation_summary` populated (verifiable on next inbound email after deploy).
- The dashboard renders the structured AI briefing (reason / customerWants / recommendedOptions / proposedTimes) for any conversation with an active escalation, not the generic frontend fallback.

Full suite stays at 1095 + 5 new = 1100 passing / 0 failures.

## Rollback

`git revert <commit>`. Restores the wrong status filter (escalations stay invisible to the readback) and the inline dispatcher in dashboard/api.py (email_poller process loses the dispatcher again). The new file `wtyj/shared/escalation_dispatcher.py` gets deleted by the revert. No data migration risk; the column itself is unchanged.
