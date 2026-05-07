# BRIEF 218 — Email forward + delete actions
**Status:** Draft | **Files:** `wtyj/dashboard/api.py`, `wtyj/shared/state_registry.py`, `wtyj/tests/social/test_218_email_actions.py` | **Depends on:** Brief 210 (smtp_send + email_append_assistant_message), Brief 211 (`_find_email_thread_key_for`) | **Blocks:** SR's email-conversation Reply/Forward/Delete row buttons (Forward + Delete are the missing two)

## Context

In SR's frontend Inbox view, every email-channel row shows three action buttons: Reply, Forward, Delete. Reply works (Brief 210). Forward and Delete are dead today — the backend doesn't have those endpoints. The frontend's lib at `unboks-org/.../lib/api.ts:296+` already calls `POST /messages/conversations/:id/email/forward` and `POST /messages/conversations/:id/email/delete`; both 404 today and the frontend's NOT_CONNECTED fallback shows a calm "will be connected" notice instead of either action firing.

SR's product contract Section 7 describes the v1 contract:

```
POST /messages/conversations/{conversation_id}/email/forward
Body: { to: [str], cc?: [str], bcc?: [str], note?: str, includeAttachments?: bool }
Behavior: re-send original email to recipients (with optional note prepended)

POST /messages/conversations/{conversation_id}/email/delete
Body: { deleteMode: "archive" | "trash" | "permanent" }
v1 recommendation: "trash" only.
Behavior: move email to trash/archive in provider if supported.
         Mark local conversation deleted/archived.
         Do not show in normal inbox after success.
```

Today the email thread state (`/app/config/email_thread_state.json`) does NOT store attachments — `extract_text` at `wtyj/agents/marina/email_adapter.py:165-181` parses the message into plain text and discards attachments. So `includeAttachments=true` from the frontend cannot be honored without a much bigger ingestion change. v1 ignores it with a clear response note.

## Why This Approach

- **Forward = re-send the latest customer message.** SR's frontend posts only `{to, cc, bcc, note, includeAttachments}` — no message_id, no body — so the backend has to infer what to forward from conversation context. The pragmatic choice: forward the most recent customer-role message in the thread. Operators are usually forwarding the most recent inbound to a colleague; if they want to forward an older message, the dashboard UI can be extended later to send `{messageId}` explicitly. Frontend can also accept `note` as a prefix the operator types in the forward dialog.
- **Forward subject = "Fwd: " + original subject** (built from the thread's first message's subject if available; falls back to `business.support_email` placeholder). Email-client-friendly convention; threading still works in the recipient's inbox.
- **Delete v1 is local-only.** Mark the thread `flags.deleted = True` in `email_thread_state.json`. Filter deleted threads from `email_list_conversations()` so they disappear from the dashboard. Provider-side IMAP MOVE to trash is **deferred** — explained below.
- **Provider-side trash deferred.** The IMAP MOVE to `[Gmail]/Trash` (Gmail) or `Deleted Items` (Outlook) requires (a) tracking the original IMAP UID per email message — currently the thread state stores only `Message-ID` in `mid_index`, not the UID, (b) opening an IMAP connection at delete-time and `UID SEARCH HEADER Message-ID` to resolve, (c) provider-folder mapping. ~30 min of work and risks blocking the delete flow if IMAP is slow/unavailable. v1 hides the conversation in the dashboard (which is the operator-facing UX), with a `# TODO: provider-side IMAP MOVE` comment + brief follow-up note. Operator can manually clean up `hello@unboks.org` Gmail later if they want.
- **`includeAttachments` ignored in v1, response acknowledges it.** Forward response includes `"attachments_included": False` so the frontend can show a small "(attachments not forwarded)" caveat. Real attachment handling needs storage of attachments at ingestion time — separate brief.
- **Rejected: bundle "archive" mode in v1.** SR's spec lists three modes (archive/trash/permanent). v1 ships "trash" only — accepts only that value, returns 400 for the others with a clear message ("v1 supports trash only"). Archive could mean "remove from inbox but keep in archive folder" but the dashboard UX reduces to the same thing for the operator (conversation gone from active list); simpler to expose one flavor.
- **Rejected: actually IMAP-MOVE on the provider during delete.** As above — deferred. The brief notes the provider mapping (Gmail vs Outlook) so when the first Outlook tenant is deployed and asks for it, we have the design ready.
- **Outlook tenant note.** When BlueMarlin/Adamus/Consulta need email delete, the folder name changes from `[Gmail]/Trash` to `Deleted Items`. Detection: `EMAIL_PASSWORD` env var presence (Brief 204 — set means Gmail app password mode, absent means Microsoft OAuth/Outlook). Codepath is single line behind a folder-name lookup; no refactor required.

## Instructions

### Step 1 — `email_mark_deleted` helper in `wtyj/shared/state_registry.py`

Insert near `email_append_assistant_message` (around line 949+):

```python
def email_mark_deleted(thread_key: str) -> bool:
    """Brief 218: mark an email thread as deleted in our local state.
    The thread will be filtered out of email_list_conversations and
    email_get_conversation will return a tombstone shape. Provider-side
    IMAP MOVE to trash is deferred — this is local-state only for v1.
    Returns True on success, False if no such thread."""
    path = _get_email_state_path()
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r") as f:
            state = json.load(f)
    except Exception:
        return False
    threads = state.get("threads", {})
    if thread_key not in threads:
        return False
    th = threads[thread_key]
    th.setdefault("flags", {})["deleted"] = True
    th["last_activity"] = datetime.now(timezone.utc).isoformat()
    state["threads"][thread_key] = th
    try:
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except OSError:
        return False
    return True
```

### Step 2 — Filter deleted threads in `email_list_conversations`

In the existing `email_list_conversations()` (line ~837), add a skip just after `flags = th.get("flags", {}) or {}`:

```python
# Brief 218: skip threads marked deleted (the dashboard hides them
# from the active inbox; provider-side cleanup is a follow-up).
if flags.get("deleted"):
    continue
```

### Step 3 — Latest customer message helper

Add a helper in state_registry near `email_append_assistant_message`:

```python
def email_get_latest_customer_message(thread_key: str) -> dict:
    """Brief 218: return the most recent customer-role message in this
    email thread, or empty dict if none. Used by /forward to pick what
    to forward when the frontend doesn't specify a message id."""
    if not thread_key:
        return {}
    path = _get_email_state_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            state = json.load(f)
    except Exception:
        return {}
    th = state.get("threads", {}).get(thread_key, {}) or {}
    for m in reversed(th.get("messages", []) or []):
        if m.get("role") == "customer":
            return m
    return {}
```

### Step 4 — POST `/messages/conversations/:id/email/forward` in `wtyj/dashboard/api.py`

Insert after the existing `delete_conversation` handler (around `:935`). Reuse the `state_registry._find_email_thread_key_for` helper from Brief 211 to resolve the thread.

```python
class EmailForwardRequest(BaseModel):
    to: list[str]
    cc: list[str] = []
    bcc: list[str] = []
    note: str = ""
    includeAttachments: bool = False  # ignored in v1


@router.post("/messages/conversations/{conversation_id:path}/email/forward",
             dependencies=[Depends(_check_auth)])
async def forward_email(conversation_id: str, req: EmailForwardRequest):
    """Brief 218: forward the most recent customer message in this email
    thread to a new recipient list, with an optional operator note
    prepended. Attachments are NOT forwarded in v1 (response includes
    `attachments_included: false` so the frontend can display a caveat)."""
    if not req.to:
        raise HTTPException(status_code=400, detail="`to` recipient list is required")

    # Resolve the email thread. Frontend may send the conversation_id with
    # or without the `email::` prefix from the inbox listing.
    thread_key = conversation_id
    if thread_key.startswith("email::"):
        thread_key = thread_key[len("email::"):]
    # If it looks like an email address (no thread_key shape), look up the
    # most recent thread for that address.
    if "@" in thread_key and ":" not in thread_key:
        thread_key = state_registry._find_email_thread_key_for(thread_key) or ""

    latest_msg = state_registry.email_get_latest_customer_message(thread_key)
    if not latest_msg:
        raise HTTPException(status_code=404,
            detail="No customer message found to forward in this conversation")

    # Build forward subject: "Fwd: " + original subject from thread_key shape.
    parts = thread_key.split(":", 2) if thread_key else []
    original_email = parts[1] if len(parts) >= 2 else ""
    fwd_subject = "Fwd: from " + (original_email or "customer")

    # Build forward body: optional note, then a delimiter, then the
    # original message body.
    original_body = latest_msg.get("body") or latest_msg.get("text") or ""
    forward_body_parts = []
    if req.note.strip():
        forward_body_parts.append(req.note.strip())
        forward_body_parts.append("")  # blank line
    forward_body_parts.append("---------- Forwarded message ----------")
    if original_email:
        forward_body_parts.append(f"From: {original_email}")
    forward_body_parts.append("")
    forward_body_parts.append(original_body)
    forward_body = "\n".join(forward_body_parts)

    # Send to each recipient. Combine to + cc + bcc into the SMTP envelope;
    # smtp_send takes a single to_addr, so loop. Cap to 20 recipients
    # to prevent accidental spam.
    all_recipients = list(req.to) + list(req.cc) + list(req.bcc)
    if len(all_recipients) > 20:
        raise HTTPException(status_code=400,
            detail="Too many recipients (max 20)")

    sent_to = []
    for rcpt in all_recipients:
        try:
            smtp_send(rcpt, fwd_subject, forward_body)
            sent_to.append(rcpt)
        except Exception as exc:
            bm_logger.log("email_forward_send_failed",
                          rcpt=rcpt[:60], error=str(exc)[:200])
            # Continue to next recipient — partial success is reported below

    bm_logger.log("email_forwarded",
                  thread_key=thread_key[:60],
                  recipient_count=len(sent_to))

    return {
        "ok": True,
        "forwarded_to": sent_to,
        "failed": [r for r in all_recipients if r not in sent_to],
        "attachments_included": False,  # v1: never
    }
```

### Step 5 — POST `/messages/conversations/:id/email/delete` in `wtyj/dashboard/api.py`

Insert immediately after `forward_email`:

```python
class EmailDeleteRequest(BaseModel):
    deleteMode: str = "trash"  # v1 only accepts "trash"


@router.post("/messages/conversations/{conversation_id:path}/email/delete",
             dependencies=[Depends(_check_auth)])
async def delete_email_conversation(conversation_id: str, req: EmailDeleteRequest):
    """Brief 218: mark an email conversation deleted in local state so it
    disappears from the dashboard inbox. v1 = trash mode only.
    Provider-side IMAP MOVE to [Gmail]/Trash (or Outlook 'Deleted Items'
    when Outlook tenants come online) is deferred to a follow-up brief —
    this v1 hides the conversation from the dashboard, which is the
    operator-facing UX. The underlying email stays in the provider mailbox."""
    if req.deleteMode != "trash":
        raise HTTPException(status_code=400,
            detail=f"v1 supports deleteMode='trash' only (got {req.deleteMode!r}). "
                   f"'archive' and 'permanent' are deferred.")

    thread_key = conversation_id
    if thread_key.startswith("email::"):
        thread_key = thread_key[len("email::"):]
    if "@" in thread_key and ":" not in thread_key:
        thread_key = state_registry._find_email_thread_key_for(thread_key) or ""

    if not thread_key:
        raise HTTPException(status_code=404,
            detail="Email conversation not found")

    ok = state_registry.email_mark_deleted(thread_key)
    if not ok:
        raise HTTPException(status_code=404,
            detail="Email conversation not found")

    # TODO: provider-side IMAP MOVE to trash folder.
    # Gmail (unboks): folder = "[Gmail]/Trash", auth via EMAIL_PASSWORD app password.
    # Outlook (BlueMarlin/Adamus/Consulta): folder = "Deleted Items", Microsoft OAuth.
    # Detection: bool(os.environ.get("EMAIL_PASSWORD")) → Gmail; else Outlook.
    # Implementation: open IMAP, UID SEARCH HEADER Message-ID for each stored
    # message-id in the thread, MOVE the matched UIDs to the trash folder.

    bm_logger.log("email_conversation_deleted",
                  thread_key=thread_key[:60], mode="trash")
    return {"ok": True, "deleteMode": "trash", "thread_key": thread_key}
```

## Tests (6)

In `wtyj/tests/social/test_218_email_actions.py`. Mirror the pattern in test_210/214 (TestClient + tmp_path + monkeypatch on `_get_email_state_path`).

1. **`test_forward_calls_smtp_send_for_each_recipient`** — seed a fake email_thread_state.json with one customer message, mock `smtp_send`, POST `/forward` with `{to: ["a@x.com", "b@x.com"], note: "fyi"}`, assert smtp_send called twice (once per recipient), forward body contains the operator's note + the original body.
2. **`test_forward_400_on_empty_recipients`** — POST with `{to: []}`, assert 400 with detail mentioning "to" or "recipient".
3. **`test_forward_404_when_no_customer_message`** — seed thread with no customer messages, POST forward, assert 404.
4. **`test_forward_response_acknowledges_attachments_skipped`** — POST with `includeAttachments: true`, assert response has `attachments_included: false` (v1 always false).
5. **`test_delete_marks_thread_deleted_and_filters_from_list`** — seed thread, POST `/delete` with `{deleteMode: "trash"}`, then GET `/messages/conversations`, assert the deleted thread is NOT in the list.
6. **`test_delete_400_on_invalid_mode`** — POST with `{deleteMode: "permanent"}`, assert 400 with detail mentioning "trash only".

Baseline: 982 (Brief 215). Target: 988 passing / 0 failures.

## Success Condition

After deploy, in SR's frontend:
1. Open an email conversation in the inbox.
2. Click "Forward". Frontend dialog opens. Operator types a recipient (e.g., `colleague@example.com`) and an optional note. Click Send.
3. Backend `POST /forward` returns 200; the email arrives at the recipient inbox with subject "Fwd: from <customer email>" and a body containing the operator's note + the original message body.
4. Click "Delete" on a conversation. Confirmation dialog (frontend handles). On confirm, backend `POST /delete` returns 200, the conversation disappears from the inbox listing.
5. The underlying email is still in `hello@unboks.org` Gmail (provider-side cleanup is the deferred TODO). Operator can manually delete from Gmail if they want.

## Rollback

`git revert <commit>`, push, canary redeploys. The deletion flag added to thread state (`flags.deleted`) is harmless on revert — older code never checks for it, so deleted threads simply reappear in the inbox. No data loss; emails stay in `email_thread_state.json` regardless of the flag. Forward sends already happened on the SMTP side and can't be unsent — but that's true of any forward action.
