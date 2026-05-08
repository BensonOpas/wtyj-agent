# BRIEF 233 — Distinguish operator-typed email replies from Marina-generated ones
**Status:** Draft | **Files:** `wtyj/shared/state_registry.py`, `wtyj/dashboard/api.py`, `wtyj/tests/social/test_233_operator_role.py` | **Depends on:** Brief 210 (`/escalations/{id}/reply` email branch — operator verbatim send), Brief 214 (`/escalations/{id}/guidance` email path — Marina reformulation), Brief 225 (`/messages/conversations/{id}/email/reply` — operator verbatim send) | **Blocks:** SR's task `f61c511ffd3c` Q1 ("Client-facing display should not imply the Agent wrote a verbatim operator reply.")

## Context

SR's task `f61c511ffd3c` Q1 asked us to verify how operator-typed email replies render. Today's behavior:

- Operator types a reply via `EmailActionsModal` → `POST /messages/conversations/{id}/email/reply` (Brief 225) or `POST /escalations/{id}/reply` for hard escalations (Brief 210).
- Backend calls `state_registry.email_append_assistant_message(customer_email, body)` which writes a message with `role: "marina"` (state_registry.py:1199).
- `email_get_conversation` mapper at lines 1085-1089 maps `"marina" → "assistant"` for the dashboard.
- The dashboard's mapper at `lib/api.ts:466-475` normalizes `"assistant"` to the Marina/Agent avatar.
- Result: every operator-typed reply renders in the conversation view as if Marina wrote it.

For the `/escalations/{id}/guidance` email path (Brief 214), Marina genuinely DOES reformulate the operator's coaching into a customer-facing reply, so `role: "marina"` is correct there. Only the verbatim-send paths (Briefs 210 + 225) are mis-attributed.

## Why This Approach

**Chosen:** add an optional `role` parameter to `email_append_assistant_message` (default `"marina"` — backward compat for Marina's own writes). Update the two verbatim-send call sites in `dashboard/api.py` to pass `role="operator"`. Extend the role-mapping in `email_get_conversation` and `email_list_conversations` to pass `"operator"` through to the API response unchanged. SR's frontend mapper currently lumps anything-not-"user" into `"assistant"` — so the new `"operator"` value gracefully defaults to the existing Marina avatar for operators who haven't updated yet, but exposes the distinction so SR can wire a different render path when ready.

**Why a 3-value role enum, not a separate field.** The existing role field already discriminates on author. Adding `"operator"` as a third value keeps the contract single-axis. A parallel `senderType` field would force SR's frontend to reconcile two fields (role and senderType) for every message render. One field, three values is the simpler shape.

**Why the operator-side guidance path stays `role: "marina"`.** Brief 214's `/escalations/{id}/guidance` flow has Marina REFORMULATE the operator's coaching into a customer-facing reply. The customer received a Marina-written message. The dashboard correctly shows it as Marina. The comment at api.py:2277-2278 documents this explicitly. This brief leaves that path untouched.

**Why backward compat matters here.** Existing `email_thread_state.json` files have years of historical messages with `role: "marina"` — many of which were operator-typed before this fix. The mapper preserves the existing behavior for legacy data: anything stored as `"marina"` continues to map to `"assistant"`, anything stored as `"operator"` (new writes only, post-deploy) maps to `"operator"`. No data migration needed.

**Rejected:** centralize the role mapping in a single helper function used by both `email_get_conversation` and `email_list_conversations`. Tempting but adds a new module-level helper for a 3-line case. Inline duplication is honest about the cost and the call sites are short.

**Rejected:** force the new value through `email_append_assistant_message`'s body content (e.g., prepend "[OPERATOR]" to the body). Visual hack, not a contract. Would also leak into the customer-visible email since smtp_send already happened upstream.

**Tradeoff:** SR's frontend won't render operator messages distinctly until he ships a frontend change. Until then the visible behavior is identical to today (operator-typed renders as Agent), but the data model now distinguishes — so SR can ship the frontend update independently. The fix is genuinely two-sided; this brief ships the backend half.

## Instructions

### 1. `state_registry.email_append_assistant_message` — add `role` param

Current signature (line 1179):
```python
def email_append_assistant_message(customer_email: str, body: str):
```

Change to:
```python
def email_append_assistant_message(customer_email: str, body: str,
                                    role: str = "marina"):
    """Brief 210: append an outbound reply to the email thread state.
    Brief 233: `role` distinguishes Marina-generated replies (`"marina"`,
    the default) from verbatim operator replies (`"operator"`). The
    /escalations/{id}/guidance path keeps the default because Marina
    reformulates the operator's coaching there. /escalations/{id}/reply
    (hard escalation) and /messages/conversations/{id}/email/reply pass
    `role="operator"` because the operator's text is sent verbatim."""
```

Inside the function (line 1199), replace:
```python
    th.setdefault("messages", []).append({
        "role": "marina",
        "ts": datetime.now(timezone.utc).isoformat(),
        "body": body,
    })
```

with:
```python
    th.setdefault("messages", []).append({
        "role": role,
        "ts": datetime.now(timezone.utc).isoformat(),
        "body": body,
    })
```

### 2. `state_registry.email_get_conversation` — pass operator role through

In the message-mapping loop at lines 1084-1092, replace:

```python
    for m in raw_messages:
        role = m.get("role", "")
        if role == "customer":
            role = "user"
        elif role == "marina":
            role = "assistant"
        text = m.get("body") or m.get("text") or ""
        ts = m.get("ts") or m.get("timestamp") or ""
        out_messages.append({"role": role, "text": text, "created_at": ts})
```

with:

```python
    for m in raw_messages:
        role = m.get("role", "")
        if role == "customer":
            role = "user"
        elif role == "marina":
            role = "assistant"
        # Brief 233: 'operator' passes through unchanged so the frontend
        # can render verbatim operator replies distinctly from Marina-
        # generated ones. SR's existing mapper falls back to "assistant"
        # for unknown values, so this is a graceful no-op until the
        # frontend opts into the new value.
        text = m.get("body") or m.get("text") or ""
        ts = m.get("ts") or m.get("timestamp") or ""
        out_messages.append({"role": role, "text": text, "created_at": ts})
```

### 3. `state_registry.email_list_conversations` — pass operator role through in last_message_role

In the per-thread loop at lines 1035-1041, replace:

```python
        last_role = last.get("role", "")
        last_body = (last.get("body") or last.get("text") or "")[:200]
        # Normalize role: customer -> user, marina -> assistant (matches WhatsApp shape)
        if last_role == "customer":
            last_role = "user"
        elif last_role == "marina":
            last_role = "assistant"
```

with:

```python
        last_role = last.get("role", "")
        last_body = (last.get("body") or last.get("text") or "")[:200]
        # Normalize role: customer -> user, marina -> assistant.
        # Brief 233: 'operator' passes through unchanged so the inbox
        # list can show a distinct indicator for operator-typed replies.
        if last_role == "customer":
            last_role = "user"
        elif last_role == "marina":
            last_role = "assistant"
```

(No code change needed in step 3 — the existing branch leaves unknown roles untouched. The comment captures intent. If you want to be defensive and match the explicit "passes through" claim with a no-op branch, that's optional.)

### 4. `dashboard/api.py` — verbatim-send call sites pass `role="operator"`

**Site A: `/messages/conversations/{id}/email/reply` (Brief 225, line 1358)**

Replace:
```python
    matched = state_registry.email_append_assistant_message(customer_email, body)
```

with:
```python
    matched = state_registry.email_append_assistant_message(
        customer_email, body, role="operator")
```

**Site B: `/escalations/{id}/reply` email branch (Brief 210, line 2120)**

Replace:
```python
        thread_key = state_registry.email_append_assistant_message(
            customer_id, operator_reply)
```

with:
```python
        thread_key = state_registry.email_append_assistant_message(
            customer_id, operator_reply, role="operator")
```

**Site C: `/escalations/{id}/guidance` email branch (Brief 214, line 2279)**

LEAVE UNCHANGED. The comment at line 2277-2278 documents that Marina's reformulation is what's appended, not the operator's coaching. Default `role="marina"` is correct.

## Tests

Place at `wtyj/tests/social/test_233_operator_role.py`. Drive the real `email_append_assistant_message` and the real `email_get_conversation` / `email_list_conversations` so the test fails if either side regresses.

```python
"""Tests for Brief 233 — distinguish operator-typed email replies from
Marina-generated ones via a `role="operator"` value on the persisted
message."""
import json

from shared import state_registry


def _seed_thread(tmp_path, monkeypatch, customer_email, with_customer=True):
    """Write a fake email_thread_state.json with one customer message
    and monkeypatch the path resolver. Returns the thread_key."""
    thread_key = f"subj:{customer_email}:test233"
    messages = []
    if with_customer:
        messages.append({
            "role": "customer",
            "ts": "2026-05-08T10:00:00+00:00",
            "body": "Hi, can you help?",
        })
    state = {
        "threads": {
            thread_key: {
                "messages": messages,
                "fields": {},
                "flags": {},
            }
        }
    }
    fake_path = tmp_path / "email_thread_state.json"
    fake_path.write_text(json.dumps(state))
    monkeypatch.setattr(state_registry, "_get_email_state_path",
                        lambda: str(fake_path))
    return thread_key, fake_path


def test_default_role_is_marina(tmp_path, monkeypatch):
    """Brief 233: backward compat — calls without an explicit role
    persist as `marina` so legacy callers (Brief 214 guidance path) keep
    working."""
    customer = "test233-alice@example.com"
    thread_key, fake_path = _seed_thread(tmp_path, monkeypatch, customer)
    state_registry.email_append_assistant_message(
        customer, "Marina's reformulated reply")
    state = json.loads(fake_path.read_text())
    last = state["threads"][thread_key]["messages"][-1]
    assert last["role"] == "marina"


def test_operator_role_persisted_when_specified(tmp_path, monkeypatch):
    """Brief 233: passing role='operator' stores the new value verbatim."""
    customer = "test233-bob@example.com"
    thread_key, fake_path = _seed_thread(tmp_path, monkeypatch, customer)
    state_registry.email_append_assistant_message(
        customer, "Operator's verbatim reply", role="operator")
    state = json.loads(fake_path.read_text())
    last = state["threads"][thread_key]["messages"][-1]
    assert last["role"] == "operator"
    assert last["body"] == "Operator's verbatim reply"


def test_get_conversation_passes_operator_role_through(tmp_path, monkeypatch):
    """Brief 233: the email_get_conversation mapper passes 'operator'
    through unchanged. Customer still maps to 'user', marina still maps
    to 'assistant', operator stays as 'operator' so the frontend can
    distinguish."""
    customer = "test233-carol@example.com"
    thread_key, _ = _seed_thread(tmp_path, monkeypatch, customer)
    state_registry.email_append_assistant_message(
        customer, "Marina-generated", role="marina")
    state_registry.email_append_assistant_message(
        customer, "Operator-typed", role="operator")
    detail = state_registry.email_get_conversation(thread_key)
    msgs = detail["messages"]
    # 3 messages: customer, marina, operator (in that order).
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"
    assert msgs[2]["role"] == "operator"
    assert msgs[2]["text"] == "Operator-typed"


def test_list_conversations_surfaces_operator_role(tmp_path, monkeypatch):
    """Brief 233: when the most recent message in a thread is from an
    operator, email_list_conversations returns last_message_role
    ='operator' (not 'assistant')."""
    customer = "test233-dan@example.com"
    thread_key, _ = _seed_thread(tmp_path, monkeypatch, customer)
    state_registry.email_append_assistant_message(
        customer, "Operator's reply", role="operator")
    rows = state_registry.email_list_conversations()
    matches = [r for r in rows if r["phone"] == f"email::{thread_key}"]
    assert len(matches) == 1
    assert matches[0]["last_message_role"] == "operator"


def test_marina_role_still_maps_to_assistant_for_legacy(tmp_path, monkeypatch):
    """Brief 233: legacy threads with role='marina' continue to map to
    'assistant' so existing data renders unchanged."""
    customer = "test233-eve@example.com"
    thread_key, _ = _seed_thread(tmp_path, monkeypatch, customer)
    state_registry.email_append_assistant_message(
        customer, "legacy marina write")  # default role
    detail = state_registry.email_get_conversation(thread_key)
    assert detail["messages"][-1]["role"] == "assistant"
```

## Success Condition

After deploy, an operator who replies via the dashboard's `/email/reply` (Brief 225) or hard-escalation `/escalations/{id}/reply` email branch (Brief 210) sees their message persisted with `role: "operator"`, surfaced through both `email_get_conversation` and `email_list_conversations` as `"operator"`, ready for SR's frontend to render distinctly. Marina's auto-replies and Brief 214's guidance reformulation continue to persist as `"marina"`. New regression tests cover backward-compat default, operator-explicit persist, conversation-detail mapper, list mapper, and legacy-marina mapping. Full suite stays at 1083 + 5 new = 1088 passing / 0 failures.

## Rollback

`git revert <commit>`. Operator-typed replies revert to `role: "marina"`; the dashboard renders them as Marina/Agent again (back to today's behavior). No data migration risk — the new `"operator"` value lives only in messages added after this deploy, and the mapper continues to handle them as "assistant" once SR's frontend changes are also reverted (or if the value is read by a frontend that doesn't recognize it).
