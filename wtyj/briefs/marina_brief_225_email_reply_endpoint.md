# BRIEF 225 — Email reply endpoint for non-escalated threads
**Status:** Draft | **Files:** `wtyj/dashboard/api.py`, `wtyj/tests/social/test_225_email_reply_endpoint.py` | **Depends on:** Brief 210 (`/escalations/{id}/reply` email branch), Brief 218 (`/email/forward` + `/email/delete` mounted on `/messages/conversations/{id}/`) | **Blocks:** SR's EmailActionsModal reply path on any email thread (escalated or not)

## Context

SR's frontend `EmailActionsModal` calls `POST /messages/conversations/{id}/email/reply` (with a `/reply` fallback) for ANY email row, including threads that never escalated. Backend currently has:

- `POST /messages/conversations/{id}/email/forward` (Brief 218, line 1148) ✓
- `POST /messages/conversations/{id}/email/delete` (Brief 218, line 1217) ✓
- `POST /messages/conversations/{id}/email/reply` ✗ **missing**
- `POST /escalations/{id}/reply` (Brief 210, line 1706) — requires an existing escalation row, can't be used for "operator wants to reply to a non-escalated email."

Operators who want to reply to a regular email thread from the dashboard hit a 404. The frontend's fallback to `/reply` on the same conversation path also 404s. The reply modal looks broken even though forward + delete next to it work.

## Why This Approach

**Chosen:** add `POST /messages/conversations/{conversation_id:path}/email/reply` mirroring the `forward` + `delete` pattern. Same `conversation_id` path-resolver logic, same Pydantic request body shape as the frontend's `EmailReplyPayload`, same return shape `{ok: true}` matching the frontend's TypeScript contract.

**thread_key format is fixed.** `email_adapter.resolve_thread_key` (line 210-213) produces `"subj:<from_email>:<normalized_subject>"`, so `parts = thread_key.split(":", 2)` gives `parts[0] == "subj"` (literal), `parts[1] == customer_email`, `parts[2] == normalized_subject` (lowercased, "re:" prefixes stripped). The existing `forward_email` handler at api.py:1169 uses `parts[1]` for the customer email, same as we will. We use `parts[2]` for the original subject.

**Reuses existing state-registry helpers verbatim:**
- `_find_email_thread_key_for(customer_email)` — when `conversation_id` is just an email address (not a full `email::<thread_key>`)
- `email_append_assistant_message(customer_email, body)` — append the operator reply to thread state so the dashboard conversation view shows it (mirrors the existing escalation-reply path at line 1794)

**No Marina reformulation.** The existing escalation-reply email branch at `dashboard/api.py:1772-1813` sends the operator's text **verbatim** (no Marina call). For non-escalated email replies the same rule applies — operator IS the author, no agent in the loop. Cheaper, more honest, no Rule 1 violation (zero new Claude calls per inbound message).

**No `awaiting_relay` flag toggling.** That's a soft-escalation Marina-mode mechanic (Brief 159). For a non-escalated email, the operator just typed a message; there is no Marina to "release" via flag flip. The endpoint stays simple: send + persist + return ok.

**Rejected:** route this through `/escalations/{id}/reply` by auto-creating an escalation row first. Would create phantom escalations every time an operator wants to send a quick "thanks, I'll get back to you" email. Wrong abstraction.

**Rejected:** thin wrapper over `email_poller.smtp_send` only (no thread-state append). The dashboard conversation detail reads from `email_thread_state.json` — without the append, the operator's reply doesn't appear in the message trail until the next poll cycle (and may never appear if it doesn't bounce back via IMAP).

**Tradeoff on subject:** the normalized subject in `parts[2]` is lowercased (e.g. `"hi can you help"`). The reply will go out as `"Re: hi can you help"`. Customer mail clients thread on `Message-ID` / `In-Reply-To` headers, not on subject case, so threading works. The cosmetic awkwardness is acceptable for v1; if operators complain, a future brief can store the original-cased subject on the thread state at first ingest.

**Tradeoff on payload:** v1 ignores `mode` and `attachments` from the frontend payload. The frontend defaults to `mode: "direct"` and `attachments: []`, so neither carries semantics today. The Pydantic schema accepts both so a future feature can branch on mode without a contract change.

## Instructions

Open `wtyj/dashboard/api.py`. Find the existing `EmailForwardRequest` Pydantic model (around line 1140) and the `forward_email` handler (line 1148). The new endpoint will land **immediately before** them (above `# ── Email Forward + Delete (Brief 218) ──`) so the section reads in operator-action order: reply → forward → delete.

1. **Add the request model + handler** above the `# ── Email Forward + Delete (Brief 218) ──` section header, around line 1138:

```python
# ── Email Reply (Brief 225) ─────────────────────────────────────────────────
# Operator-authored reply to any email conversation, escalated or not. Mirrors
# the verbatim-send pattern of the existing /escalations/{id}/reply email
# branch (api.py:1772-1813) — operator's text goes to smtp_send unchanged,
# then is appended to the local email_thread_state.json so the dashboard
# conversation view reflects it immediately.

class EmailReplyRequest(BaseModel):
    body: str
    mode: str = "direct"           # v1 ignores; reserved for future relay/draft modes
    attachments: list = []         # v1 ignores (forward also defers attachments)


@router.post("/messages/conversations/{conversation_id:path}/email/reply",
             dependencies=[Depends(_check_auth)])
async def reply_to_email_conversation(conversation_id: str, req: EmailReplyRequest):
    """Brief 225: send an operator-authored email reply to a thread that may
    not be tied to an escalation. Operator's text is sent verbatim — no
    Marina reformulation (matches the /escalations/{id}/reply email branch)."""
    body = (req.body or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="`body` is required")

    thread_key = conversation_id
    if thread_key.startswith("email::"):
        thread_key = thread_key[len("email::"):]
    if "@" in thread_key and ":" not in thread_key:
        thread_key = state_registry._find_email_thread_key_for(thread_key) or ""

    if not thread_key:
        raise HTTPException(status_code=404,
            detail="Email conversation not found")

    # thread_key format from email_adapter.resolve_thread_key:
    #   "subj:<from_email>:<normalized_subject>"
    # parts[0] == literal "subj", parts[1] == customer email, parts[2] == subject.
    parts = thread_key.split(":", 2)
    customer_email = parts[1] if len(parts) >= 2 else ""
    raw_subject = parts[2] if len(parts) >= 3 else ""

    if not customer_email or "@" not in customer_email:
        raise HTTPException(status_code=404,
            detail="Email conversation has no resolvable customer address")

    subject = raw_subject or "Unboks"
    if not subject.lower().startswith("re:"):
        subject = "Re: " + subject

    try:
        smtp_send(customer_email, subject, body)
    except Exception as exc:
        bm_logger.log("dashboard_email_reply_send_failed",
                      thread_key=thread_key[:60],
                      email=customer_email[:60],
                      error=str(exc)[:200])
        raise HTTPException(status_code=500,
            detail=f"Failed to send email reply: {str(exc)[:120]}")

    matched = state_registry.email_append_assistant_message(customer_email, body)
    bm_logger.log("dashboard_email_reply_sent",
                  thread_key=thread_key[:60],
                  email=customer_email[:60],
                  matched=matched or "(no thread match)")

    return {"ok": True, "channel": "email"}
```

2. **No state_registry changes.** All helpers used (`_find_email_thread_key_for`, `email_append_assistant_message`) already exist.

## Tests

Mirror the proven Brief 218 fixture pattern: monkeypatch `state_registry._get_email_state_path` to a tmp file, use the real `webhook_server.app` via TestClient, login to get the auth token. Use the actual production thread_key shape `"subj:<email>:<subject>"`.

Place at `wtyj/tests/social/test_225_email_reply_endpoint.py`:

```python
"""Tests for Brief 225 — POST /messages/conversations/{id}/email/reply."""
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

client = TestClient(app)


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_email_thread(tmp_path, monkeypatch, customer_email, subject="test225 reply"):
    """Write a fake email_thread_state.json with one customer message and
    monkeypatch the state-registry path resolver. Returns the thread_key."""
    from shared import state_registry
    thread_key = f"subj:{customer_email}:{subject}"
    state = {
        "threads": {
            thread_key: {
                "messages": [{
                    "role": "customer",
                    "ts": "2026-05-08T10:00:00+00:00",
                    "body": "Hi, can you help?",
                }],
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


@patch("dashboard.api.smtp_send")
def test_reply_sends_smtp_and_appends_thread(mock_smtp, tmp_path, monkeypatch):
    """Brief 225: smtp_send fires with the right address + subject; thread state
    gains an operator-role message with the operator's body."""
    customer_email = "test225-alice@example.com"
    thread_key, fake_path = _seed_email_thread(tmp_path, monkeypatch,
                                               customer_email)

    token = _login()
    r = client.post(
        f"/dashboard/api/messages/conversations/email::{thread_key}/email/reply",
        json={"body": "Thanks for reaching out — looking into it."},
        headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "channel": "email"}

    mock_smtp.assert_called_once()
    to_addr, subj, sent_body = mock_smtp.call_args.args[0:3]
    assert to_addr == customer_email
    assert subj.lower().startswith("re:")
    assert "test225 reply" in subj.lower()
    assert sent_body == "Thanks for reaching out — looking into it."

    state = json.loads(fake_path.read_text())
    msgs = state["threads"][thread_key]["messages"]
    assert msgs[-1]["role"] == "marina"
    assert msgs[-1]["body"] == "Thanks for reaching out — looking into it."


@patch("dashboard.api.smtp_send")
def test_reply_resolves_email_only_conversation_id(mock_smtp, tmp_path, monkeypatch):
    """When the frontend passes just the customer email (not the full
    `email::<thread_key>`), the resolver finds the matching thread."""
    customer_email = "test225-bob@example.com"
    _seed_email_thread(tmp_path, monkeypatch, customer_email,
                       subject="brief 225 inquiry")
    token = _login()
    r = client.post(
        f"/dashboard/api/messages/conversations/{customer_email}/email/reply",
        json={"body": "Will follow up shortly."},
        headers=_auth(token))
    assert r.status_code == 200, r.text
    mock_smtp.assert_called_once()
    assert mock_smtp.call_args.args[0] == customer_email


@patch("dashboard.api.smtp_send")
def test_reply_strips_email_prefix(mock_smtp, tmp_path, monkeypatch):
    customer_email = "test225-carol@example.com"
    thread_key, _ = _seed_email_thread(tmp_path, monkeypatch, customer_email,
                                       subject="menu request")
    token = _login()
    r = client.post(
        f"/dashboard/api/messages/conversations/email::{thread_key}/email/reply",
        json={"body": "Here's our menu."},
        headers=_auth(token))
    assert r.status_code == 200, r.text
    mock_smtp.assert_called_once()


def test_reply_400_on_empty_body(tmp_path, monkeypatch):
    customer_email = "test225-dan@example.com"
    thread_key, _ = _seed_email_thread(tmp_path, monkeypatch, customer_email)
    token = _login()
    r = client.post(
        f"/dashboard/api/messages/conversations/email::{thread_key}/email/reply",
        json={"body": "   "},
        headers=_auth(token))
    assert r.status_code == 400
    assert "body" in r.json()["detail"].lower()


def test_reply_404_when_thread_missing(tmp_path, monkeypatch):
    """An email-only conversation_id with no matching thread → 404."""
    from shared import state_registry
    fake_path = tmp_path / "email_thread_state.json"
    fake_path.write_text(json.dumps({"threads": {}}))
    monkeypatch.setattr(state_registry, "_get_email_state_path",
                        lambda: str(fake_path))
    token = _login()
    r = client.post(
        "/dashboard/api/messages/conversations/test225-nobody@example.com/email/reply",
        json={"body": "hello"},
        headers=_auth(token))
    assert r.status_code == 404


def test_reply_500_on_smtp_failure(tmp_path, monkeypatch):
    customer_email = "test225-eve@example.com"
    thread_key, _ = _seed_email_thread(tmp_path, monkeypatch, customer_email)
    token = _login()
    with patch("dashboard.api.smtp_send",
               side_effect=Exception("Connection refused")):
        r = client.post(
            f"/dashboard/api/messages/conversations/email::{thread_key}/email/reply",
            json={"body": "hello"},
            headers=_auth(token))
    assert r.status_code == 500
    assert "Failed to send email reply" in r.json()["detail"]
```

## Success Condition

After deploy, hitting `POST /messages/conversations/{id}/email/reply` with `{"body": "..."}` returns `{ok: true, channel: "email"}`, sends an SMTP email to the customer at `parts[1]` with subject `"Re: <parts[2]>"`, and appends the reply (role `"marina"`) to `email_thread_state.json`. SR's `EmailActionsModal` reply button stops 404ing on non-escalated email rows. New regression tests in `test_225_email_reply_endpoint.py` cover smtp send + thread append, prefix stripping, email-only id resolution, empty-body 400, missing-thread 404, smtp failure 500. Full suite stays at 1033 + 6 new = 1039 passing / 0 failures.

## Rollback

`git revert <commit>`. Removes the new endpoint + tests; the broken state pre-Brief 225 returns (frontend falls back to `/reply` then surfaces "Email reply endpoint method mismatch"). No data migration risk — endpoint is purely additive.
