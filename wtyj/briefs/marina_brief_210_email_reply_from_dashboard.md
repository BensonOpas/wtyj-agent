# BRIEF 210 — Email reply-from-dashboard for hard escalations
**Status:** Draft | **Files:** `wtyj/dashboard/api.py`, `wtyj/shared/state_registry.py` | **Depends on:** Brief 206 (`[ESCALATE]` sentinel + `pending_notifications` row), Brief 209 (Marina sign-off live) | **Blocks:** SR being able to reply to email escalations from the dashboard

## Context

Live evidence: there is exactly one escalation row in `unboks/data/state_registry.db` — Calvin Adamus from GAIMIN, channel=`email`, customer_id=`calvin@gaimin.io`. SR's complaint "Escalations doesnt work !  check" + "add in reply in dashboard" are the same bug:

`wtyj/dashboard/api.py:1216` (existing `reply_to_escalation` endpoint):
```python
else:
    raise HTTPException(status_code=400, detail=f"Channel '{channel}' reply not supported from dashboard")
```

When SR opens the email escalation and tries to reply → 400. The endpoint only handles `channel == "whatsapp"`. The WhatsApp branch (lines 1177-1214) routes through `marina_agent.process_message()` in **relay mode** (`awaiting_relay` flag preserved) so Marina reformulates the operator's text before sending.

For email **hard** escalations (the `[ESCALATE]` sentinel pattern from Brief 206), there is no `awaiting_relay` flag — the conversation isn't in semi-escalation mode. The operator is just typing a direct reply. The cleanest UX matches a normal email reply: **operator's text is sent verbatim** (no LLM reformulation), appended to the email thread state, notification marked replied.

## Why this approach

- **Direct send for email, no Marina reformulation.** Hard escalations don't have a relay token; the operator is the one who *should* be authoring the reply (this is the "human takes over" moment). Reformulating their text through Claude is unwanted: adds latency, an extra API call (Rule 1: one Claude call per inbound — but this isn't an inbound, it's an outbound), and risks the LLM softening or contradicting what the operator wrote.
- **WhatsApp branch left untouched.** The existing relay-mode behavior is correct for WhatsApp semi escalations (the only kind that exists today on this endpoint). Hard-escalation WhatsApp replies would be a separate brief if needed; SR's complaint is email-specific.
- **Email thread state lives in `email_thread_state.json` (file, not SQLite).** Existing helper `state_registry._get_email_state_path()` resolves the container path. Existing reader `email_get_conversation()` parses it. Need a small writer for "append assistant message + save" — symmetric with `wa_store_message`.
- **Customer email = `pending_notifications.customer_id`.** Verified live: row id=1 has `customer_id='calvin@gaimin.io'`. No mapping needed.
- **No `In-Reply-To` / `References` header threading on the outbound.** The existing relay-send path at `email_poller.py:591-595` doesn't pass these either — keeping behavior consistent. Email clients fall back to subject-line threading. Adding RFC 5322 reply headers is a future polish if needed (would require persisting customer's Message-ID per inbound; the current state JSON doesn't store it).
- **Rejected:** routing operator text through `marina_agent.process_message()`. Adds 5-15s latency, costs a Claude call, may rewrite the operator's exact words. Operators want WYSIWYG.
- **Rejected:** building a new `POST /escalations/{id}/reply_email` endpoint. Same shape, same auth, same response contract — just extending the channel branches in the existing endpoint is cleaner.
- **Rejected:** finding the email thread by `customer_id == thread_key`. Thread keys look like `subj:calvin@gaimin.io:abc123` — need substring match on the email. A linear scan over threads dict is fine (typical dict has dozens of entries, not thousands).

## Instructions

### Step 1 — `wtyj/shared/state_registry.py`: add `email_append_assistant_message`

Insert after `email_get_conversation()` (around line 891). Reads the JSON, finds the matching thread by customer email substring, appends a `{"role": "marina", ...}` message, and writes back. Returns the thread_key on success or `None` if no thread matched (caller still sends the email; this is a logging-only side effect).

```python
def email_append_assistant_message(customer_email: str, body: str) -> str | None:
    """Brief 210: append an operator-authored reply to the email thread state
    so it shows up in the dashboard conversation view. Mirrors what
    email_poller.py:596-601 does on the relay-receive path. Returns the
    matched thread_key, or None if no thread exists for this email yet
    (caller can still send the email; we just won't have a thread record)."""
    path = _get_email_state_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            state = json.load(f)
    except Exception:
        return None

    threads = state.get("threads", {})
    matched_key = None
    for thread_key in threads.keys():
        # thread_keys look like "subj:calvin@gaimin.io:..." — substring-match the email
        if customer_email and customer_email.lower() in thread_key.lower():
            matched_key = thread_key
            break

    if not matched_key:
        return None

    th = threads[matched_key]
    th.setdefault("messages", []).append({
        "role": "marina",
        "ts": datetime.now(timezone.utc).isoformat(),
        "body": body,
    })
    th["last_activity"] = datetime.now(timezone.utc).isoformat()
    state["threads"][matched_key] = th

    try:
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except OSError:
        return None

    return matched_key
```

(Imports `datetime` and `timezone` are already in `state_registry.py`. `json` and `os` too.)

### Step 2 — `wtyj/dashboard/api.py`: add email branch to `reply_to_escalation`

At line 1215-1216, replace the bare `else: raise HTTPException(...)` with an `elif channel == "email":` branch that calls `smtp_send` and the new helper. Final `else` keeps the 400 for any future unknown channel.

Imports needed at top of file (check first — add only if absent):
- `from agents.marina.email_adapter import smtp_send`

The replaced block:

```python
    elif channel == "email":
        if not customer_id or "@" not in customer_id:
            raise HTTPException(status_code=400, detail="Email escalation missing valid email address")

        operator_reply = req.answer.strip()
        # Use the escalation's subject as the reply subject; prepend "Re: " if missing.
        subject = esc.get("subject") or "Re: Unboks"
        if not subject.lower().startswith("re:"):
            subject = "Re: " + subject

        try:
            smtp_send(customer_id, subject, operator_reply)
        except Exception as exc:
            bm_logger.log("dashboard_email_reply_send_failed",
                          email=customer_id, escalation_id=escalation_id,
                          error=str(exc)[:200])
            raise HTTPException(status_code=500,
                detail=f"Failed to send email reply: {str(exc)[:120]}")

        thread_key = state_registry.email_append_assistant_message(customer_id, operator_reply)
        bm_logger.log("dashboard_email_reply_sent",
                      email=customer_id, escalation_id=escalation_id,
                      thread_key=thread_key or "(no thread match)")

        state_registry.update_notification_status(escalation_id, "replied")
        return {"ok": True, "reply": operator_reply, "channel": "email"}

    else:
        raise HTTPException(status_code=400, detail=f"Channel '{channel}' reply not supported from dashboard")
```

### Step 3 — Tests in `wtyj/tests/test_210_email_escalation_reply.py` (new file, 4 tests)

```python
"""Brief 210: dashboard reply-to-escalation endpoint must handle email channel
in addition to the existing whatsapp branch."""
import os
import json
import pathlib
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from agents.social.webhook_server import app  # noqa: E402

client = TestClient(app)


def _login_token():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _seed_escalation(channel: str, customer_id: str) -> int:
    from shared import state_registry
    return state_registry.create_pending_notification(
        "escalation", channel, customer_id, "Test Customer",
        "[ESCALATION] test", "test body")


def test_email_reply_sends_via_smtp_and_marks_replied(tmp_path, monkeypatch):
    """Email reply path: smtp_send called with operator's text, status flips."""
    monkeypatch.setenv("STATE_REGISTRY_PATH", str(tmp_path / "state.db"))
    from shared import state_registry
    state_registry._connect.cache_clear() if hasattr(state_registry._connect, "cache_clear") else None

    esc_id = _seed_escalation("email", "test-customer@example.com")
    token = _login_token()

    with patch("dashboard.api.smtp_send") as mock_smtp, \
         patch("dashboard.api.state_registry.email_append_assistant_message",
               return_value="subj:test-customer@example.com:abc"):
        r = client.post(
            f"/dashboard/api/escalations/{esc_id}/reply",
            json={"answer": "Wednesday 4pm works. Calendar invite incoming."},
            headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200, r.text
    assert r.json()["channel"] == "email"
    mock_smtp.assert_called_once()
    args, _ = mock_smtp.call_args
    assert args[0] == "test-customer@example.com"
    assert args[2] == "Wednesday 4pm works. Calendar invite incoming."

    # Notification marked replied
    rows = state_registry.get_all_escalations()
    matched = next(e for e in rows if e["id"] == esc_id)
    assert matched["status"] == "replied"


def test_email_reply_rejects_invalid_address(tmp_path, monkeypatch):
    """Email branch must reject customer_id without an @."""
    monkeypatch.setenv("STATE_REGISTRY_PATH", str(tmp_path / "state.db"))
    esc_id = _seed_escalation("email", "not-an-email")
    token = _login_token()

    r = client.post(
        f"/dashboard/api/escalations/{esc_id}/reply",
        json={"answer": "test"},
        headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400
    assert "valid email" in r.json()["detail"].lower()


def test_email_reply_returns_500_on_smtp_failure(tmp_path, monkeypatch):
    """SMTP errors surface as 500, status NOT flipped to replied."""
    monkeypatch.setenv("STATE_REGISTRY_PATH", str(tmp_path / "state.db"))
    from shared import state_registry
    esc_id = _seed_escalation("email", "test-customer@example.com")
    token = _login_token()

    with patch("dashboard.api.smtp_send", side_effect=RuntimeError("smtp down")):
        r = client.post(
            f"/dashboard/api/escalations/{esc_id}/reply",
            json={"answer": "test"},
            headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 500
    assert "smtp down" in r.json()["detail"].lower()

    # Status still pending — failed sends must not flip the row
    rows = state_registry.get_all_escalations()
    matched = next(e for e in rows if e["id"] == esc_id)
    assert matched["status"] == "pending"


def test_unknown_channel_still_400(tmp_path, monkeypatch):
    """Channel not in {whatsapp, email} returns 400 (regression guard)."""
    monkeypatch.setenv("STATE_REGISTRY_PATH", str(tmp_path / "state.db"))
    esc_id = _seed_escalation("instagram", "fake-handle")
    token = _login_token()

    r = client.post(
        f"/dashboard/api/escalations/{esc_id}/reply",
        json={"answer": "test"},
        headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400
    assert "instagram" in r.json()["detail"].lower()
```

Test file path: `wtyj/tests/test_210_email_escalation_reply.py`. Mirrors the test file naming used elsewhere in the suite (`test_207_tasks_api.py`, `test_208_*`).

If the `STATE_REGISTRY_PATH` env-monkeypatching pattern doesn't isolate test state cleanly (other tests in the suite may share the same in-process DB connection cache), fall back to mocking `state_registry.create_pending_notification` and `state_registry.get_all_escalations` directly. Verify pattern in existing `wtyj/tests/test_dashboard_api.py` first if available — match whatever the suite already does.

## Tests (4)

Defined above. Summary:
1. **email_reply_sends_via_smtp_and_marks_replied** — happy path, mock `smtp_send` + `email_append_assistant_message`, verify call args + status flip
2. **email_reply_rejects_invalid_address** — customer_id without `@` returns 400
3. **email_reply_returns_500_on_smtp_failure** — SMTP exception → 500, status stays `pending`
4. **unknown_channel_still_400** — regression guard: `channel="instagram"` (or any non-whatsapp non-email) returns 400

WhatsApp branch is not re-tested — already covered by existing dashboard tests; this brief doesn't touch that code path.

## Success Condition

After deploy:
1. SR opens the Calvin Adamus escalation in `dashboard.unboks.org` Escalations panel.
2. SR types a reply (e.g., "Wednesday 4pm works for the activation call. I'll send a Google Meet invite shortly. Marina") and submits.
3. Within seconds: (a) calvin@gaimin.io receives the reply email from `Marina <hello@unboks.org>`, (b) the escalation row's status flips from `sent`/`pending` to `replied`, (c) the email thread in `dashboard.unboks.org` Messages panel shows the new outbound entry.
4. Live verification command:
   ```bash
   ssh root@108.61.192.52 'docker exec wtyj-unboks python3 -c "
   import sqlite3
   c = sqlite3.connect(\"/app/data/state_registry.db\").cursor()
   c.execute(\"SELECT id, status FROM pending_notifications ORDER BY id DESC LIMIT 3\")
   print(list(c))
   "'
   ```

## Rollback

`git revert <commit>` and trigger redeploy via the canary pipeline. State JSON appended messages stay in place (operator-authored content has standalone value); SMTP sends already happened on Anthropic's side and can't be unsent. The next deploy returns the endpoint to the pre-Brief-210 behavior (400 on email channel).

If the SMTP-send path itself is buggy in production but tests passed, frontend behavior degrades gracefully — operator sees a 500 with the SMTP error string and nothing has been irreversibly changed (notification status only flips after successful send).
