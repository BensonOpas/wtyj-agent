# BRIEF 227 — Decision-first escalation summary
**Status:** Draft | **Files:** `wtyj/shared/state_registry.py`, `wtyj/dashboard/api.py`, `wtyj/dashboard/escalation_summary.py` (new), `wtyj/tests/dashboard/test_227_escalation_summary.py` | **Depends on:** Brief 211 (`escalated`/`escalationResolved`/`escalationMode`/`aiMuted` on conversation detail), Brief 217 (alert dispatcher hook in `create_pending_notification`), Brief 222 (`recommendedOptions` + `extractedDetails` already wired through to the frontend mapper) | **Blocks:** SR's "decision-first escalation view" (frontend already renders the structured fields if backend supplies them — this brief makes the backend supply them)

## Context

SR's frontend `EscalationReasonPanel` (316 lines) and `EscalationReplyComposer` (482 lines) already parse and render structured escalation fields: `summary`, `reason`, `customerWants`, `operatorNeedsToDecide`, `recommendedOptions[]`, `extractedDetails.proposedTimes[]`. When the backend doesn't return these, the frontend falls back to a generic-text parser (`escalation-summary.ts`, 540 lines) that does its best to extract proposed times from the conversation. Result: operators see vague summaries like "Calvin is asking about schedule a meeting and suggested a time" when the customer actually proposed two specific slots.

SR's task (`727264bd9c61`):
> "When generating escalationSummary, the backend/AI must extract all proposed dates, times, slots, and options from the conversation, not only the first one. Reason box must be operator briefing — give the human the exact choice they need to make. Concrete options (Confirm Thursday at 09:00 / Confirm Thursday at 12:00 / Suggest another time / Switch to human takeover). One active unresolved escalation per conversation."

Backend today: `create_pending_notification` (state_registry.py:1285) inserts a row with `subject` + `body` (alert text), no structured summary. `get_all_escalations` (state_registry.py:1669) returns those columns + Brief 211/213 fields, no summary. `/messages/conversations/{phone}` (api.py:1108) exposes the Brief 211/213/222 fields but no summary block.

## Why This Approach

**Chosen:** add a single nullable JSON column `escalation_summary TEXT` to `pending_notifications`. Generate the summary once at escalation-create time via a dedicated `dashboard.escalation_summary.generate_summary` Claude call. Persist as JSON string. Read paths parse and surface. Dedup at write time: if an unresolved escalation already exists for this `customer_id`, UPDATE it in place instead of INSERTing a fresh row.

**Why one JSON column, not five separate columns.** The structured summary is one indivisible AI output — `recommendedOptions` and `extractedDetails.proposedTimes` only make sense alongside `reason`/`customerWants`/`operatorNeedsToDecide`. SQLite gets one column to update; the API layer JSON-decodes once. If a future requirement wants per-field indexing (e.g. "find escalations mentioning a specific time"), split then. YAGNI today.

**Why a separate module `dashboard/escalation_summary.py`.** State-registry stays Claude-agnostic (the Brief 217 pattern). The dashboard layer already imports `anthropic`. Module-private function with one entry point: `generate_summary(channel, customer_id, customer_name, mode, channels_history)`. Returns a dict matching SR's frontend contract — or `None` on any failure (network, parsing, empty response). Caller persists what it gets back.

**Why a NEW dispatcher hook, not extending Brief 217's `_alert_dispatcher`.**
Brief 217's dispatcher fires alert emails. This brief generates a summary. Two unrelated concerns; bundling them would mean alert delivery and summary generation share a try/except scope, so a Claude API hiccup could swallow an SMTP failure (or vice versa). State-registry already has a clean pattern: `set_alert_dispatcher` + `_alert_dispatcher` global. We mirror it as `set_summary_dispatcher` + `_summary_dispatcher`. `create_pending_notification` calls both in sequence, each independently best-effort.

**Why generate synchronously inside `create_pending_notification`.** Claude latency for this prompt is ~1-2 seconds. Escalations are rare events (humans, not bots). Adding 1-2 seconds to a path that already involves SMTP delivery is acceptable. An async background job would let the escalation list briefly show "summary pending" — extra UI state for marginal benefit.

**Dedup approach: update-in-place at write time.**
Per SR's spec: "update the existing unresolved escalation". When `create_pending_notification` is called with `notification_type == "escalation"` and a row already exists for the same `customer_id` with `status == "pending"`, we UPDATE that row's `subject`/`body`/`mode`/`escalation_summary`/`created_at` instead of inserting a new one. The row keeps its `id`, so any outstanding alert thread stays attached. Returns the existing row's `id`.

**Rejected: read-time dedup in `get_all_escalations`.** Easier to write but leaves accumulated noise in the DB and complicates audit-log queries. SR's spec says "update", so we update.

**Rejected: dedup by `(customer_id, channel)` instead of just `customer_id`.** A WhatsApp conversation and an email conversation are distinct flows even when they share the same human. `customer_id` for whatsapp is a phone number; for email it's an address; for DMs it's a Zernio hex. The `customer_id` value alone is already unique to the conversation, so adding `channel` to the dedup key is redundant.

**Rejected: separate `escalation_summaries` table joined on `pending_notifications.id`.** Cleaner schema but doubles the read path (one extra query per `get_all_escalations` call) for no benefit. The summary is 1:1 with the escalation row and never independently queried.

**Tradeoff:** if Claude returns malformed JSON or an empty response, the row's `escalation_summary` stays null and the frontend uses its existing generic-text fallback parser. We log the failure in `bm_logger` so we can monitor rate, but never raise — escalation row creation MUST never fail because of a summary-generation hiccup.

## Instructions

### 1. Schema migration

In `wtyj/shared/state_registry.py`, the `pending_notifications` `CREATE TABLE` block (around line 238) is followed by Brief 213's idempotent ALTER for the `mode` column (line 261). Add a parallel ALTER block for the new column **right after the Brief 213 ALTER block**:

```python
    # Brief 227: structured escalation summary as JSON. Generated by Claude
    # at escalation-create time (best-effort — null if generation fails).
    try:
        conn.execute(
            "ALTER TABLE pending_notifications "
            "ADD COLUMN escalation_summary TEXT"
        )
    except sqlite3.OperationalError:
        pass  # column already exists
```

### 2. Generator module — `wtyj/dashboard/escalation_summary.py`

NEW FILE. Pure Claude call, no DB access, no state-registry import. Returns a dict matching SR's frontend contract or None.

```python
"""Brief 227: generate the structured 'decision-first' escalation summary
that SR's EscalationReasonPanel renders. One Claude call, one return —
no retries, no fallbacks. Caller persists whatever we hand back (or null
on failure).

Frontend contract (from EscalationReasonPanel + escalation-summary.ts):
{
    "reason": str,                  # one-paragraph operator briefing
    "customerWants": str,           # what the customer is asking for
    "operatorNeedsToDecide": str,   # the choice the operator faces
    "recommendedOptions": [str],    # 3-5 concrete actionable chips
    "extractedDetails": {
        "intent": str,              # "scheduling" | "complaint" | ...
        "proposedTimes": [str],     # every time slot the customer mentioned
        "topic": str,               # short topic label
    }
}
"""
import json
import os
from typing import Optional

import anthropic
from shared import bm_logger


SUMMARY_TOOL = {
    "name": "escalation_summary",
    "description": (
        "Emit a structured operator briefing for this escalation. The "
        "operator will read this BEFORE the conversation trail, so it must "
        "tell them WHY they're being pulled in, WHAT the customer wants, "
        "and WHICH choice they need to make. Extract every proposed time/"
        "slot/option from the customer's messages — do not summarize "
        "vaguely as 'suggested a time' when exact times exist."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": (
                    "One-paragraph operator briefing. Names the customer, "
                    "states the topic, and ends with what the operator needs "
                    "to do. Example: 'Calvin wants to schedule an activation "
                    "call. He suggested Thursday at 09:00 or 12:00. Marina "
                    "needs a human to choose one of the proposed slots or "
                    "suggest another time.'"
                ),
            },
            "customerWants": {
                "type": "string",
                "description": "One sentence: what the customer is asking for.",
            },
            "operatorNeedsToDecide": {
                "type": "string",
                "description": (
                    "One sentence: the choice the operator must make. List the "
                    "concrete options inline. Example: 'Choose Thursday at "
                    "09:00, choose Thursday at 12:00, suggest another time, "
                    "or ask for more availability.'"
                ),
            },
            "recommendedOptions": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "3-5 concrete actionable options. Each option must be a "
                    "specific action, not a category. EVERY proposed time "
                    "from the customer becomes its own 'Confirm <time>' "
                    "option. Always include 'Suggest another time' and "
                    "'Switch to human takeover' as fallback options when "
                    "the intent is scheduling. For non-scheduling intents, "
                    "tailor accordingly."
                ),
            },
            "extractedDetails": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": (
                            "Short label: scheduling | complaint | refund | "
                            "pricing | activation | technical | other"
                        ),
                    },
                    "proposedTimes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "EVERY time slot the customer mentioned, in "
                            "their original wording. Example: ['Thursday at "
                            "09:00', 'Thursday at 12:00']. Empty list if "
                            "no times mentioned."
                        ),
                    },
                    "topic": {
                        "type": "string",
                        "description": "2-5 word topic label.",
                    },
                },
                "required": ["intent", "proposedTimes", "topic"],
            },
        },
        "required": [
            "reason", "customerWants", "operatorNeedsToDecide",
            "recommendedOptions", "extractedDetails",
        ],
    },
}


def _format_history(messages: list) -> str:
    """Render the conversation as plain text for the Claude prompt."""
    lines = []
    for m in messages or []:
        role = m.get("role", "")
        if role in ("user", "customer", "incoming"):
            speaker = "CUSTOMER"
        else:
            speaker = "AGENT"
        text = m.get("text") or m.get("content") or m.get("body") or ""
        if not text:
            continue
        lines.append(f"{speaker}: {text.strip()}")
    return "\n".join(lines) if lines else "(no message history available)"


def generate_summary(channel: str, customer_id: str, customer_name: str,
                     mode: Optional[str], history: list) -> Optional[dict]:
    """Brief 227: build the structured escalation briefing. Returns the
    dict on success, None on any failure (caller persists null and the
    frontend falls back to its generic-text parser)."""
    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return None
        client = anthropic.Anthropic(api_key=api_key)

        history_text = _format_history(history)
        mode_text = mode if mode in ("soft", "hard") else "(unset)"

        system_prompt = (
            "You are an operator-facing assistant. Your job is to read a "
            "conversation between a CUSTOMER and an AI AGENT, then summarize "
            "the situation for a human operator who has to step in. The "
            "operator will read your summary BEFORE reading the conversation, "
            "so it must give them everything they need to make a decision in "
            "one glance.\n\n"
            "Hard rules:\n"
            "- Extract EVERY proposed time/slot/option from the customer's "
            "messages. Never summarize 'suggested a time' if exact times "
            "exist.\n"
            "- Use the customer's exact wording for times when possible.\n"
            "- Recommended options must be CONCRETE actions, not categories. "
            "'Confirm Thursday at 09:00' yes; 'Pick a time' no.\n"
            "- For scheduling escalations, always include "
            "'Suggest another time' and 'Switch to human takeover' as "
            "fallbacks.\n"
            "- Never invent customer wording or times that aren't in the "
            "transcript."
        )

        user_prompt = (
            f"CHANNEL: {channel}\n"
            f"CUSTOMER ID: {customer_id}\n"
            f"CUSTOMER NAME: {customer_name or '(unknown)'}\n"
            f"ESCALATION MODE: {mode_text}\n\n"
            f"CONVERSATION:\n{history_text}\n\n"
            "Emit your structured operator briefing now."
        )

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            tools=[SUMMARY_TOOL],
            tool_choice={"type": "tool", "name": "escalation_summary"},
            messages=[{"role": "user", "content": user_prompt}],
        )

        # Token usage logging (mirrors marina_agent.process_message).
        _usage = getattr(response, "usage", None)
        if _usage:
            bm_logger.log("escalation_summary_usage",
                          input_tokens=_usage.input_tokens,
                          output_tokens=_usage.output_tokens,
                          channel=channel,
                          customer_id=customer_id[:50])

        block = next(
            (b for b in response.content if b.type == "tool_use"),
            None,
        )
        if block is None:
            bm_logger.log("escalation_summary_no_tool_use",
                          channel=channel, customer_id=customer_id[:50])
            return None
        return dict(block.input)
    except Exception as exc:
        bm_logger.log("escalation_summary_failed",
                      error=str(exc)[:200],
                      channel=channel,
                      customer_id=customer_id[:50])
        return None
```

### 3. State-registry changes

Add the `_summary_dispatcher` global + setter alongside the Brief 217 pattern (around line 21):

```python
# Brief 227: dashboard.api registers a summary generator here. Mirrors the
# Brief 217 alert-dispatcher pattern — one global, set once at module-load,
# called best-effort with try/except gating so a Claude failure never blocks
# escalation row creation.
_summary_dispatcher = None


def set_summary_dispatcher(fn):
    """Brief 227: register the summary generator (typically dashboard.api's
    _generate_escalation_summary)."""
    global _summary_dispatcher
    _summary_dispatcher = fn
```

Update `create_pending_notification` (around line 1285) to: (a) dedup unresolved escalations by UPDATE, (b) call the summary dispatcher and persist its result, (c) keep the alert dispatcher firing as today.

```python
def create_pending_notification(notification_type: str, channel: str,
                                 customer_id: str, customer_name: str,
                                 subject: str, body: str,
                                 relay_token: str = None) -> int:
    """Insert (or, for an unresolved escalation, UPDATE) a pending
    notification. Brief 227: structured escalation summary generated
    via _summary_dispatcher and persisted on the same row."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()

    row_id = None
    summary_dict = None

    # Brief 227: dedup unresolved escalations. If a 'pending' row already
    # exists for this customer_id (escalation only), UPDATE it instead of
    # inserting a new one. Keeps the row id stable so any outstanding
    # alert thread / learning entry stays attached.
    if notification_type == "escalation":
        existing = conn.execute(
            "SELECT id FROM pending_notifications "
            "WHERE customer_id = ? AND notification_type = 'escalation' "
            "AND status = 'pending' "
            "ORDER BY created_at DESC LIMIT 1",
            (customer_id,)).fetchone()
        if existing:
            row_id = existing[0]

    if row_id is None:
        cur = conn.execute(
            "INSERT INTO pending_notifications "
            "(notification_type, relay_token, channel, customer_id, customer_name, "
            "subject, body, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (notification_type, relay_token, channel, customer_id, customer_name,
             subject, body, now)
        )
        row_id = cur.lastrowid
    else:
        conn.execute(
            "UPDATE pending_notifications "
            "SET subject = ?, body = ?, customer_name = ?, created_at = ? "
            "WHERE id = ?",
            (subject, body, customer_name, now, row_id))
    conn.commit()
    conn.close()

    set_conversation_status(customer_id, "open", channel)

    # Brief 217: best-effort alert dispatch.
    if notification_type == "escalation" and _alert_dispatcher is not None:
        try:
            _alert_dispatcher(row_id, customer_name, channel, subject)
        except Exception:
            pass

    # Brief 227: best-effort structured summary generation. Persisted on
    # the same row whether the row was newly inserted or updated.
    if notification_type == "escalation" and _summary_dispatcher is not None:
        try:
            summary_dict = _summary_dispatcher(
                row_id, channel, customer_id, customer_name)
            if summary_dict:
                conn = _get_conn()
                conn.execute(
                    "UPDATE pending_notifications SET escalation_summary = ? "
                    "WHERE id = ?",
                    (json.dumps(summary_dict), row_id))
                conn.commit()
                conn.close()
        except Exception:
            pass

    return row_id
```

(Add `import json` at the top of `state_registry.py` if it isn't already imported — verify before adding.)

Update `get_all_escalations` (line 1669) to surface the summary on each row:

```python
def get_all_escalations() -> list:
    """Brief 181: contact_type. Brief 183: customer_contact. Brief 188:
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
    result = []
    for r in rows:
        ct = _infer_contact_type(r[4] or "")
        contact = _lookup_customer_contact(r[4] or "", ct)
        customer_contact = contact["email"] or contact["phone"] or r[4] or ""
        if r[3] == "email":
            _email_thread_key = _find_email_thread_key_for(r[4])
            _phone_routing_key = f"email::{_email_thread_key}" if _email_thread_key else (r[4] or "")
        else:
            _phone_routing_key = r[4] or ""

        # Brief 227: parse the JSON summary blob into structured fields.
        summary_obj = None
        if r[11]:
            try:
                summary_obj = json.loads(r[11])
            except (json.JSONDecodeError, TypeError):
                summary_obj = None

        result.append({
            "id": r[0], "notification_type": r[1], "relay_token": r[2],
            "channel": r[3], "customer_id": r[4], "customer_name": r[5],
            "subject": r[6], "body": r[7], "status": r[8], "created_at": r[9],
            "mode": r[10],
            "contact_type": ct,
            "customer_contact": customer_contact,
            "customer_email": contact["email"],
            "customer_phone": contact["phone"],
            "conversation_status": get_conversation_status(r[4]),
            "phone": _phone_routing_key,
            # Brief 227: structured summary surfaces as both a nested object
            # AND lifted top-level recommendedOptions/extractedDetails for
            # the frontend's existing readers.
            "escalationSummary": summary_obj,
            "recommendedOptions": (
                (summary_obj or {}).get("recommendedOptions") or []),
            "extractedDetails": (
                (summary_obj or {}).get("extractedDetails") or None),
        })
    return result
```

Add a new helper for the conversation-detail path:

```python
def get_active_escalation_summary_for(customer_id: str) -> Optional[dict]:
    """Brief 227: return the parsed escalation_summary dict for the most
    recent unresolved escalation on this conversation, or None.

    Used by GET /messages/conversations/:phone to enrich the response
    with escalationSummary so the frontend's EscalationReasonPanel can
    render without a second fetch."""
    if not customer_id:
        return None
    conn = _get_conn()
    row = conn.execute(
        "SELECT escalation_summary FROM pending_notifications "
        "WHERE customer_id = ? AND notification_type = 'escalation' "
        "AND status = 'pending' "
        "ORDER BY created_at DESC LIMIT 1",
        (customer_id,)).fetchone()
    conn.close()
    if not row or not row[0]:
        return None
    try:
        return json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return None
```

Place this helper next to `get_active_escalation_mode` (which is in the same conceptual area — around line 1440).

Add `from typing import Optional` to the state_registry imports if not already present.

### 4. Dashboard wiring

In `wtyj/dashboard/api.py`, near the Brief 217 alert dispatcher block (around line 1336), add the summary generator wrapper:

```python
# ── Brief 227: Escalation summary generator ─────────────────────────────────
# Hooked into state_registry.create_pending_notification via
# state_registry.set_summary_dispatcher. Best-effort: failure persists
# null, frontend falls back to its generic-text parser.

from dashboard import escalation_summary as _esc_summary


def _generate_escalation_summary(escalation_id: int, channel: str,
                                  customer_id: str, customer_name: str) -> dict:
    """Brief 227: dispatcher wrapper. Loads the relevant conversation history
    for this channel, calls the Claude generator, returns the dict (or None)."""
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

    return _esc_summary.generate_summary(
        channel=channel,
        customer_id=customer_id,
        customer_name=customer_name,
        mode=mode,
        history=history,
    )


state_registry.set_summary_dispatcher(_generate_escalation_summary)
```

Update `_conversation_status_fields` (api.py:1083) to add the summary block:

```python
def _conversation_status_fields(customer_id: str) -> dict:
    """Brief 211/213/222 + Brief 227 (escalationSummary, recommendedOptions,
    extractedDetails for the most recent unresolved escalation)."""
    cid = customer_id or ""
    status = state_registry.get_conversation_status(cid)
    summary = state_registry.get_active_escalation_summary_for(cid)
    return {
        "escalated": status == "open",
        "escalationResolved": status == "resolved",
        "escalationMode": state_registry.get_active_escalation_mode(cid),
        "aiMuted": state_registry.get_ai_muted(cid),
        "humanTakeoverAt": state_registry.get_human_takeover_at(cid),
        "learningStatus": state_registry.get_learning_status_for_conversation(cid),
        "humanGuidance": None,
        "humanResponder": None,
        "humanRespondedAt": None,
        # Brief 227: structured summary block — null if not yet generated
        # or generation failed. Frontend falls back to its generic parser.
        "escalationSummary": summary,
        "recommendedOptions": (summary or {}).get("recommendedOptions") or [],
        "extractedDetails": (summary or {}).get("extractedDetails") or None,
    }
```

## Tests

Place at `wtyj/tests/dashboard/test_227_escalation_summary.py`. Mock the Claude call to return a deterministic dict so we test wiring + persistence + dedup, not Claude itself.

```python
"""Tests for Brief 227 — decision-first escalation summary."""
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

# Importing webhook_server triggers dashboard.api import, which runs
# state_registry.set_summary_dispatcher(_generate_escalation_summary).
from agents.social.webhook_server import app
from shared import state_registry

client = TestClient(app)

SAMPLE_SUMMARY = {
    "reason": ("Calvin wants to schedule an activation call. He suggested "
               "Thursday at 09:00 or Thursday at 12:00. Marina needs a "
               "human to choose one of the proposed slots."),
    "customerWants": "An activation call this week.",
    "operatorNeedsToDecide": ("Choose Thursday at 09:00, choose Thursday at "
                              "12:00, suggest another time, or ask for more "
                              "availability."),
    "recommendedOptions": [
        "Confirm Thursday at 09:00",
        "Confirm Thursday at 12:00",
        "Suggest another time",
        "Ask Marina to collect more availability",
        "Switch to human takeover",
    ],
    "extractedDetails": {
        "intent": "scheduling",
        "proposedTimes": ["Thursday at 09:00", "Thursday at 12:00"],
        "topic": "activation call",
    },
}


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _reset_escalations(prefix: str = "test227"):
    """Wipe escalation rows for our test customer_ids so each test starts
    clean. We don't truncate the whole table — other tests share it."""
    conn = state_registry._get_conn()
    conn.execute(
        "DELETE FROM pending_notifications WHERE customer_id LIKE ?",
        (f"{prefix}%",))
    conn.execute(
        "DELETE FROM conversation_status WHERE conversation_id LIKE ?",
        (f"{prefix}%",))
    conn.commit()
    conn.close()


def test_summary_persisted_on_escalation_create():
    """Brief 227: when the summary dispatcher returns a dict,
    create_pending_notification persists it on the same row as JSON."""
    _reset_escalations()
    customer_id = "test227-alice@example.com"
    with patch("dashboard.escalation_summary.generate_summary",
               return_value=SAMPLE_SUMMARY):
        row_id = state_registry.create_pending_notification(
            notification_type="escalation",
            channel="email",
            customer_id=customer_id,
            customer_name="Alice",
            subject="Re: scheduling",
            body="alert text",
        )
    # Read raw column to confirm JSON was persisted.
    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT escalation_summary FROM pending_notifications WHERE id = ?",
        (row_id,)).fetchone()
    conn.close()
    assert row[0]
    parsed = json.loads(row[0])
    assert parsed["recommendedOptions"][0] == "Confirm Thursday at 09:00"
    assert parsed["extractedDetails"]["proposedTimes"] == [
        "Thursday at 09:00", "Thursday at 12:00"]


def test_summary_failure_does_not_block_escalation_create():
    """Brief 227: if the generator raises, the escalation row is still
    created with escalation_summary IS NULL."""
    _reset_escalations()
    customer_id = "test227-bob@example.com"
    with patch("dashboard.escalation_summary.generate_summary",
               side_effect=Exception("Claude exploded")):
        row_id = state_registry.create_pending_notification(
            notification_type="escalation",
            channel="email",
            customer_id=customer_id,
            customer_name="Bob",
            subject="Re: anything",
            body="alert text",
        )
    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT escalation_summary FROM pending_notifications WHERE id = ?",
        (row_id,)).fetchone()
    conn.close()
    assert row[0] is None


def test_dedup_unresolved_escalation_updates_in_place():
    """Brief 227: a second escalation on the same customer_id while one is
    still pending UPDATEs the existing row instead of inserting a new one."""
    _reset_escalations()
    customer_id = "test227-carol@example.com"
    with patch("dashboard.escalation_summary.generate_summary",
               return_value=SAMPLE_SUMMARY):
        first = state_registry.create_pending_notification(
            notification_type="escalation", channel="email",
            customer_id=customer_id, customer_name="Carol",
            subject="Re: first", body="first body")
        second = state_registry.create_pending_notification(
            notification_type="escalation", channel="email",
            customer_id=customer_id, customer_name="Carol",
            subject="Re: second update", body="second body")
    assert first == second
    # Only one row exists for this customer_id.
    conn = state_registry._get_conn()
    rows = conn.execute(
        "SELECT id, subject FROM pending_notifications "
        "WHERE customer_id = ? AND notification_type = 'escalation'",
        (customer_id,)).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][1] == "Re: second update"


def test_get_all_escalations_surfaces_summary_fields():
    """Brief 227: GET /escalations returns escalationSummary + lifted
    recommendedOptions + extractedDetails."""
    _reset_escalations()
    customer_id = "test227-dan@example.com"
    with patch("dashboard.escalation_summary.generate_summary",
               return_value=SAMPLE_SUMMARY):
        state_registry.create_pending_notification(
            notification_type="escalation", channel="email",
            customer_id=customer_id, customer_name="Dan",
            subject="Re: brief 227", body="alert")
    token = _login()
    r = client.get("/dashboard/api/escalations", headers=_auth(token))
    assert r.status_code == 200
    matches = [e for e in r.json() if e.get("customer_id") == customer_id]
    assert len(matches) == 1
    e = matches[0]
    assert e["escalationSummary"]["customerWants"] == "An activation call this week."
    assert e["recommendedOptions"][:2] == [
        "Confirm Thursday at 09:00", "Confirm Thursday at 12:00"]
    assert e["extractedDetails"]["proposedTimes"] == [
        "Thursday at 09:00", "Thursday at 12:00"]


def test_conversation_detail_includes_summary():
    """Brief 227: GET /messages/conversations/{phone} surfaces the summary
    block from the most recent unresolved escalation."""
    _reset_escalations()
    customer_id = "test227-eve@example.com"
    with patch("dashboard.escalation_summary.generate_summary",
               return_value=SAMPLE_SUMMARY):
        state_registry.create_pending_notification(
            notification_type="escalation", channel="whatsapp",
            customer_id=customer_id, customer_name="Eve",
            subject="WhatsApp escalation", body="alert")
    token = _login()
    r = client.get(f"/dashboard/api/messages/conversations/{customer_id}",
                   headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["escalationSummary"]["customerWants"] == "An activation call this week."
    assert body["recommendedOptions"][:2] == [
        "Confirm Thursday at 09:00", "Confirm Thursday at 12:00"]


def test_summary_generator_extracts_all_proposed_times():
    """Brief 227: the generator's tool schema demands `proposedTimes` be
    an array of every time mentioned. Smoke test that our schema is what
    the model gets."""
    from dashboard.escalation_summary import SUMMARY_TOOL
    schema = SUMMARY_TOOL["input_schema"]["properties"]
    assert "proposedTimes" in schema["extractedDetails"]["properties"]
    assert "recommendedOptions" in schema
    # Every required field is listed.
    required = set(SUMMARY_TOOL["input_schema"]["required"])
    assert {"reason", "customerWants", "operatorNeedsToDecide",
            "recommendedOptions", "extractedDetails"} <= required


def test_relay_notification_does_not_get_summary():
    """Brief 227: notification_type != 'escalation' must NOT trigger summary
    generation (relay rows are Marina asking the team — different flow)."""
    _reset_escalations()
    customer_id = "test227-frank@example.com"
    with patch("dashboard.escalation_summary.generate_summary") as mock_gen:
        state_registry.create_pending_notification(
            notification_type="relay", channel="whatsapp",
            customer_id=customer_id, customer_name="Frank",
            subject="ask the team", body="some question")
    mock_gen.assert_not_called()
```

## Success Condition

After deploy, an escalation triggered against a conversation containing two proposed times produces an `escalation_summary` JSON blob whose `recommendedOptions` list both confirmations plus the standard fallback options, and `extractedDetails.proposedTimes` contains both times in the customer's wording. `GET /escalations` rows include `escalationSummary` (object), `recommendedOptions` (top-level), and `extractedDetails` (top-level). `GET /messages/conversations/{phone}` includes the same three fields for the active unresolved escalation. A second escalation on the same conversation while the first is unresolved UPDATEs the existing row in place. New regression tests in `test_227_escalation_summary.py` cover persistence, failure-isolation, dedup, surface on both endpoints, schema completeness, and relay-not-summarized. Full suite stays at 1046 + 7 new = 1053 passing / 0 failures.

## Rollback

`git revert <commit>`. The `escalation_summary` column survives the revert (idempotent ALTER, no DROP). All existing rows have `NULL` for that column anyway, so reverted code paths simply ignore it. The dispatcher hook deregisters when the module is re-imported without the `set_summary_dispatcher` call. The frontend still works because its existing generic-text parser handles a missing `escalationSummary` field gracefully.
