# BRIEF 125 — Dashboard Escalation Replies (Semi + Full)
**Status:** Draft | **Depends on:** Brief 124 (complete) | **Blocks:** —

**Backend files:**
- `bluemarlin/dashboard/api.py`

**Frontend files:**
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Escalations.tsx`
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/lib/api.ts`
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/hooks/use-bluemarlin.ts`

**Test file:**
- `bluemarlin/tests/social/test_125_escalation_reply.py`

## Context
Escalations page needs two reply flows:
- Full: operator types reply, optionally clicks Rewrite to polish, opens in Gmail
- Semi (relay): operator types answer, optionally clicks Rewrite, clicks Send Reply → backend reformulates via Marina → sends to customer via WhatsApp

Currently: compose modal has "Suggest Reply" (generates from scratch) + "Open in Gmail". Pre-fills subject/body with boilerplate. Both need to change.

## Why This Approach
Reuse the existing suggest-reply endpoint with a `draft_text` parameter for rewrite mode. New endpoint `POST /escalations/{id}/reply` for semi relay — reuses the exact relay logic from email_poller.py (Marina reformulates, sends via WhatsApp).

## Source Material

### Backend — Modify suggest-reply endpoint

**Add `draft_text` to request model (line 954-955):**
```python
class SuggestReplyRequest(BaseModel):
    phone: str
    draft_text: str = ""
```

**Add rewrite branch to user_prompt (line 1023-1028).** Replace:
```python
    user_prompt = f"""WHATSAPP CONVERSATION:
{thread_text}

{booking_context}

Write an email reply from {agent_name} to this customer. Address open questions, confirm bookings, or provide next steps as appropriate."""
```
With:
```python
    if req.draft_text:
        user_prompt = f"""WHATSAPP CONVERSATION:
{thread_text}

{booking_context}

The operator wrote this draft reply:
---
{req.draft_text}
---

Rewrite this draft as a polished, professional email from {agent_name}. Keep the operator's intent and key points. Improve tone, clarity, and structure. Include the agent signature."""
    else:
        user_prompt = f"""WHATSAPP CONVERSATION:
{thread_text}

{booking_context}

Write an email reply from {agent_name} to this customer. Address open questions, confirm bookings, or provide next steps as appropriate."""
```

### Backend — New endpoint `POST /escalations/{id}/reply`

**Add after the suggest-reply endpoint (after line 1055):**
**Also add module-level imports at the top of api.py (after the existing agent imports, line 17-18):**
```python
from agents.marina import marina_agent
from agents.social.whatsapp_client import send_text_message as wa_send_text_message
```

**Add the endpoint:**
```python

# ── Escalation Reply ─────────────────────────────────────────────────────────

class EscalationReplyRequest(BaseModel):
    answer: str

@router.post("/escalations/{escalation_id}/reply", dependencies=[Depends(_check_auth)])
async def reply_to_escalation(escalation_id: int, req: EscalationReplyRequest):
    """Reply to a semi escalation. Marina reformulates and sends to customer."""
    if not req.answer.strip():
        raise HTTPException(status_code=400, detail="Answer text required")

    # Look up escalation (wa_send_text_message and marina_agent imported at module level)
    all_esc = state_registry.get_all_escalations()
    esc = next((e for e in all_esc if e["id"] == escalation_id), None)
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation not found")

    channel = esc.get("channel", "whatsapp")
    customer_id = esc.get("customer_id", "")

    if channel == "whatsapp" and customer_id:
        # Get conversation context
        wa_state = state_registry.wa_get_booking_state(customer_id)
        wa_fields = wa_state.get("fields", {})
        wa_flags = wa_state.get("flags", {})
        wa_history = state_registry.wa_get_history(customer_id, limit=10)

        # Strip relay-specific flags before passing to Marina
        agent_flags = dict(wa_flags)
        for rk in ("relay_token", "reply_times", "awaiting_relay", "relay_question"):
            agent_flags.pop(rk, None)

        # Marina reformulates the operator's answer
        relay_result = marina_agent.process_message(
            customer_id, "", req.answer.strip(),
            wa_fields, agent_flags,
            channel="whatsapp", messages=wa_history,
        )
        relay_reply = relay_result.get("reply", "")

        if relay_reply:
            wa_send_text_message(to=customer_id, text=relay_reply)
            state_registry.wa_store_message(customer_id, "assistant", relay_reply)
            bm_logger.log("dashboard_relay_sent", phone=customer_id, escalation_id=escalation_id)
        else:
            raise HTTPException(status_code=500, detail="Marina returned empty reply")

        # Clear relay flags
        wa_flags.pop("awaiting_relay", None)
        wa_flags.pop("relay_token", None)
        wa_flags.pop("relay_question", None)
        state_registry.wa_save_booking_state(
            customer_id, wa_fields, wa_flags,
            wa_state.get("completed_bookings", []))

        # Mark notification as replied
        state_registry.update_notification_status(escalation_id, "replied")

        return {"ok": True, "reply": relay_reply}
    else:
        raise HTTPException(status_code=400, detail=f"Channel '{channel}' reply not supported from dashboard")
```

### Frontend — api.ts

**Update `suggestReply` (line 532):**
```typescript
suggestReply: async (data: { phone: string; draft_text?: string }): Promise<{ subject: string; body: string }> => {
  const res = await fetch(`${BASE_URL}/messages/suggest-reply`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify(data),
  });
  return handleResponse(res);
},
```

**Add `replyToEscalation` after `resolveEscalation` (after line 556):**
```typescript
replyToEscalation: async (id: number, answer: string): Promise<{ ok: boolean; reply: string }> => {
  const res = await fetch(`${BASE_URL}/escalations/${id}/reply`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ answer }),
  });
  return handleResponse(res);
},
```

### Frontend — use-bluemarlin.ts

**Update `useSuggestReply` mutation (find the existing one, update mutationFn type):**
```typescript
export function useSuggestReply() {
  return useMutation({
    mutationFn: (data: { phone: string; draft_text?: string }) => api.suggestReply(data),
    onError: (err: unknown) => toast.error(`Failed: ${getErrorMessage(err)}`),
  });
}
```

**Add `useEscalationReply` after `useEscalationMutations`:**
```typescript
export function useEscalationReply() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, answer }: { id: number; answer: string }) => api.replyToEscalation(id, answer),
    onSuccess: () => {
      toast.success("Reply sent to customer");
      queryClient.invalidateQueries({ queryKey: ["escalations"] });
    },
    onError: (err: unknown) => toast.error(`Reply failed: ${getErrorMessage(err)}`),
  });
}
```

### Frontend — Escalations.tsx

**Edit 1 — Add imports (line 3):**
Change: `import { useEscalations, useEscalationMutations, useSuggestReply } from "@/hooks/use-bluemarlin";`
To: `import { useEscalations, useEscalationMutations, useSuggestReply, useEscalationReply } from "@/hooks/use-bluemarlin";`

**Edit 2 — Add hook (after line 62):**
After `const suggestReply = useSuggestReply();` add:
```tsx
const escalationReply = useEscalationReply();
```

**Edit 3 — Clear pre-filled compose (lines 95-98).** Replace:
```tsx
        setCompose({
          to: "",
          subject: `Blue Marlin Tours — Re: ${esc.subject}`,
          body: `Hi ${esc.customer_name},\n\nThank you for reaching out. We're looking into your request regarding "${esc.subject}" and will get back to you shortly.\n\nBest regards,\nBlue Marlin Tours Curaçao\n`,
        });
```
With:
```tsx
        setCompose({
          to: "",
          subject: "",
          body: "",
        });
```

**Edit 4 — Clear detail view button compose too (lines 399-410).** Replace the `setCompose({...})` block:
```tsx
              {emailSettings.enabled && selected && (
                <button
                  onClick={() => setCompose({
                    to: "",
                    subject: `Blue Marlin Tours — Re: ${selected.subject}`,
                    body: `Hi ${selected.customer_name},\n\nThank you for reaching out. We're looking into your request regarding "${selected.subject}" and will get back to you shortly.\n\nBest regards,\nBlue Marlin Tours Curaçao\n`,
                  })}
```
With:
```tsx
              {emailSettings.enabled && selected && (
                <button
                  onClick={() => setCompose({
                    to: "",
                    subject: "",
                    body: "",
                  })}
```

**Edit 5 — Replace compose modal actions (lines 234-253).** Replace the entire `<div className="flex justify-between items-center pt-1">` block with:
```tsx
              <div className="flex justify-between items-center pt-1 gap-2">
                <button
                  onClick={async () => {
                    if (!selected?.customer_id || !compose?.body.trim()) return;
                    try {
                      const result = await suggestReply.mutateAsync({ phone: selected.customer_id, draft_text: compose.body });
                      setCompose(prev => prev ? { ...prev, subject: result.subject, body: result.body } : prev);
                    } catch {}
                  }}
                  disabled={suggestReply.isPending || !compose?.body.trim()}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold border border-dashed border-primary/40 text-primary hover:bg-primary/10 hover:border-primary/60 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <Wand2 className="w-3.5 h-3.5" />
                  {suggestReply.isPending ? "Rewriting…" : "Rewrite"}
                </button>
                {selected && isSemi(selected.notification_type) ? (
                  <button
                    onClick={async () => {
                      if (!selected || !compose?.body.trim()) return;
                      try {
                        await escalationReply.mutateAsync({ id: selected.id, answer: compose.body });
                        setCompose(null);
                        backToList();
                      } catch {}
                    }}
                    disabled={escalationReply.isPending || !compose?.body.trim()}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-semibold transition-colors"
                  >
                    <Send className="w-3.5 h-3.5" />
                    {escalationReply.isPending ? "Sending…" : "Send Reply"}
                  </button>
                ) : (
                  <button onClick={sendCompose} disabled={!compose?.to} className="flex items-center gap-2 px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-semibold transition-colors">
                    <Send className="w-3.5 h-3.5" />
                    Open in {emailSettings.client === "gmail" ? "Gmail" : "Mail App"}
                  </button>
                )}
              </div>
```

## Tests

**File:** `bluemarlin/tests/social/test_125_escalation_reply.py`

```python
# test_125_escalation_reply.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from agents.social.webhook_server import app

client = TestClient(app)

def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]

def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# --- Test 1: Suggest reply with draft_text rewrites ---
@patch("dashboard.api.anthropic")
def test_rewrite_mode(mock_anthropic_module):
    from shared import state_registry
    phone = "125_rewrite_phone"
    state_registry.wa_store_message(phone, "user", "Can I bring my dog?")

    mock_client = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"subject": "Pet Policy", "body": "Hi there, unfortunately pets are not allowed on our boats for safety reasons. We hope you understand!\\n\\nMarina\\nBlueFinn Charters"}')]
    mock_client.messages.create.return_value = mock_response

    token = _login()
    r = client.post("/dashboard/api/messages/suggest-reply",
                     json={"phone": phone, "draft_text": "no dogs allowed sorry"},
                     headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert data["subject"] == "Pet Policy"
    assert "pets" in data["body"].lower() or "dog" in data["body"].lower()

    # Verify the prompt included draft_text
    call_args = mock_client.messages.create.call_args
    user_msg = call_args.kwargs["messages"][0]["content"]
    assert "no dogs allowed sorry" in user_msg
    assert "Rewrite this draft" in user_msg

    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


# --- Test 2: Suggest reply without draft_text generates from scratch ---
@patch("dashboard.api.anthropic")
def test_generate_mode(mock_anthropic_module):
    from shared import state_registry
    phone = "125_generate_phone"
    state_registry.wa_store_message(phone, "user", "Hello")

    mock_client = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"subject": "Welcome", "body": "Hi!"}')]
    mock_client.messages.create.return_value = mock_response

    token = _login()
    r = client.post("/dashboard/api/messages/suggest-reply",
                     json={"phone": phone},
                     headers=_auth(token))
    assert r.status_code == 200

    call_args = mock_client.messages.create.call_args
    user_msg = call_args.kwargs["messages"][0]["content"]
    assert "Write an email reply" in user_msg
    assert "Rewrite this draft" not in user_msg

    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


# --- Test 3: Escalation reply sends WhatsApp message ---
@patch("dashboard.api.wa_send_text_message")
@patch("dashboard.api.marina_agent")
def test_escalation_reply_sends_whatsapp(mock_marina, mock_wa_send):
    from shared import state_registry
    phone = "125_relay_phone"

    # Create a semi escalation
    state_registry.wa_store_message(phone, "user", "What is the weight limit?")
    state_registry.wa_save_booking_state(phone, {"customer_name": "Test"}, {"awaiting_relay": True, "relay_token": "abc123"})
    esc_id = state_registry.create_pending_notification(
        notification_type="relay", channel="whatsapp",
        customer_id=phone, customer_name="Test",
        subject="[RELAY-abc123] test", body="Question: weight limit",
        relay_token="abc123"
    )

    mock_marina.process_message.return_value = {
        "reply": "Great question! The weight limit is 150kg per person.",
        "intents": ["inquiry"], "fields": {}, "flags": {},
        "confidence": "high", "requires_human": False,
        "clarifications_needed": [], "internal_note": ""
    }

    token = _login()
    r = client.post(f"/dashboard/api/escalations/{esc_id}/reply",
                     json={"answer": "weight limit is 150kg"},
                     headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "150kg" in data["reply"]

    # Verify WhatsApp message was sent
    mock_wa_send.assert_called_once()
    call_args = mock_wa_send.call_args
    assert call_args.kwargs["to"] == phone

    # Verify escalation marked as replied
    escs = state_registry.get_all_escalations()
    esc = next((e for e in escs if e["id"] == esc_id), None)
    assert esc["status"] == "replied"

    # Verify relay flags cleared
    wa_state = state_registry.wa_get_booking_state(phone)
    assert wa_state["flags"].get("awaiting_relay") is None

    # Cleanup
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM pending_notifications WHERE id = ?", (esc_id,))
    conn.commit()
    conn.close()


# --- Test 4: Empty answer returns 400 ---
def test_empty_answer():
    token = _login()
    r = client.post("/dashboard/api/escalations/999/reply",
                     json={"answer": "   "},
                     headers=_auth(token))
    assert r.status_code == 400


# --- Test 5: Non-existent escalation returns 404 ---
def test_escalation_not_found():
    token = _login()
    r = client.post("/dashboard/api/escalations/99999/reply",
                     json={"answer": "test"},
                     headers=_auth(token))
    assert r.status_code == 404
```

## Success Condition
Full escalation: compose modal opens empty, Rewrite polishes text (disabled when empty), Open in Gmail sends.
Semi escalation: compose modal opens empty, Rewrite polishes, Send Reply sends via WhatsApp through Marina, escalation marked replied.
5 backend tests pass.

## Rollback
Revert api.py, Escalations.tsx, api.ts, use-bluemarlin.ts. Delete test file.
