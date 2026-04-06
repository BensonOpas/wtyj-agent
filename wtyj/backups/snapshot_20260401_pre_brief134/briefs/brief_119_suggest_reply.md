# BRIEF 119 — Suggest Email Reply
**Status:** Draft | **Depends on:** Brief 118 (complete) | **Blocks:** —

**Backend files:**
- `bluemarlin/dashboard/api.py`

**Frontend files (~/Projects/wetakeyourjob-dashboard/):**
- `artifacts/dashboard/src/lib/api.ts`
- `artifacts/dashboard/src/hooks/use-bluemarlin.ts`
- `artifacts/dashboard/src/pages/Messages.tsx`

**Test file:**
- `bluemarlin/tests/social/test_119_suggest_reply.py`

## Context
SR built a "Suggest Reply" button in the email compose modal using a Replit-local Node.js server calling OpenAI. It 404s in production. We removed the broken button in Brief 118. Now we build the real backend endpoint using Claude and re-wire the frontend.

## Why This Approach
Backend endpoint takes `phone` (not the messages array) because the backend already has `wa_get_full_history()` and `wa_get_booking_state()`. This is simpler, more secure, and lets us inject full business context from client.json. We use a dedicated Claude call (not `process_message()`) because process_message has side effects (field mutations, booking logic). This endpoint is read-only.

## Source Material

### Backend — Add to `dashboard/api.py`

**Add imports at top of file (after line 9):**
```python
import json
import re
import anthropic
```

**Add model and endpoint at end of file (after line 946):**
```python

# ── Suggest Reply ────────────────────────────────────────────────────────────

class SuggestReplyRequest(BaseModel):
    phone: str

@router.post("/messages/suggest-reply", dependencies=[Depends(_check_auth)])
async def suggest_reply(req: SuggestReplyRequest):
    """Generate an AI-suggested email reply based on WhatsApp conversation."""
    if not req.phone:
        raise HTTPException(status_code=400, detail="Phone number required")

    messages = state_registry.wa_get_full_history(req.phone, limit=30)
    if not messages:
        raise HTTPException(status_code=404, detail="No conversation found")

    booking_state = state_registry.wa_get_booking_state(req.phone)
    business = config_loader.get_business()
    csk = config_loader.get_common_sense_knowledge()
    trips = config_loader.get_trips()
    signature = config_loader.get_agent_signature()

    # Format conversation
    thread_lines = []
    for msg in messages:
        label = "Customer" if msg["role"] == "user" else "Marina"
        thread_lines.append(f"{label}: {msg['text']}")
    thread_text = "\n\n".join(thread_lines)

    # Format booking context
    fields = booking_state.get("fields", {})
    completed = booking_state.get("completed_bookings", [])
    booking_parts = []
    if fields:
        booking_parts.append("Current booking fields: " + json.dumps(fields, default=str))
    if completed:
        booking_parts.append("Completed bookings: " + json.dumps(completed, default=str))
    booking_context = "\n".join(booking_parts)

    # Format trips
    trip_lines = []
    for key, data in trips.items():
        name = data.get("display_name", key)
        price = data.get("price_pp", "")
        trip_lines.append(f"- {name}: ${price}/person" if price else f"- {name}")

    agent_name = business.get("agent_name", "Marina")
    company_name = business.get("name", "BlueFinn Charters Curaçao")
    persona = csk.get("marina_persona", "")

    system_prompt = f"""You are {agent_name}, the booking agent for {company_name}.

PERSONA: {persona}

WRITING STYLE FOR EMAIL:
Write as a real member of the {company_name} team. Warm, practical, human.
Mirror the customer's tone. Use contractions. Plain language.
No em dashes, no forced enthusiasm, no "I'd be happy to" or "Great choice".
Emails are slightly longer and more structured than WhatsApp but still conversational.

AVAILABLE TRIPS:
{chr(10).join(trip_lines)}

AGENT SIGNATURE:
{signature}

Return a JSON object with exactly two keys:
- "subject": a short email subject line (no "Re:" prefix)
- "body": the full email body including signature at the end

Return ONLY the JSON object. No markdown fences, no extra text."""

    user_prompt = f"""WHATSAPP CONVERSATION:
{thread_text}

{booking_context}

Write an email reply from {agent_name} to this customer. Address open questions, confirm bookings, or provide next steps as appropriate."""

    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw.strip())
        result = json.loads(raw)
        return {
            "subject": result.get("subject", ""),
            "body": result.get("body", ""),
        }
    except json.JSONDecodeError:
        # If JSON parse fails, treat the whole response as the body
        return {
            "subject": f"{company_name} — Follow-up",
            "body": raw if raw else "Could not generate suggestion.",
        }
    except Exception as exc:
        bm_logger.log("suggest_reply_error", error=str(exc)[:200])
        raise HTTPException(status_code=500, detail="Failed to generate suggestion")
```

### Frontend — api.ts

**Add after the `getConversation` method (after the `// --- Escalations ---` comment):**
```typescript
suggestReply: async (phone: string): Promise<{ subject: string; body: string }> => {
  const res = await fetch(`${BASE_URL}/messages/suggest-reply`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify({ phone }),
  });
  return handleResponse(res);
},
```

### Frontend — use-bluemarlin.ts

**Add after `useConversation` hook:**
```typescript
export function useSuggestReply() {
  return useMutation({
    mutationFn: api.suggestReply,
    onError: (err: unknown) => toast.error(`Failed to suggest reply: ${getErrorMessage(err)}`),
  });
}
```

### Frontend — Messages.tsx

**Add `Wand2` to lucide-react import (line 11):**
Change: `Mail, X, Send,`
To: `Mail, X, Send, Wand2,`

**Add `useSuggestReply` to imports (line 4):**
Change: `import { useConversations, useConversation } from "@/hooks/use-bluemarlin";`
To: `import { useConversations, useConversation, useSuggestReply } from "@/hooks/use-bluemarlin";`

**Add hook call inside the component (after the existing `useConversation` call, around line 154):**
```tsx
const suggestReply = useSuggestReply();
```

**Replace the compose modal actions row (line 238):**
Current:
```tsx
<div className="flex justify-end pt-1">
  <button onClick={sendCompose} disabled={!compose.to} className="flex items-center gap-2 px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-semibold transition-colors">
    <Send className="w-3.5 h-3.5" />
    Open in {emailSettings.client === "gmail" ? "Gmail" : "Mail App"}
  </button>
</div>
```

Replace with:
```tsx
<div className="flex justify-between items-center pt-1">
  <button
    onClick={async () => {
      try {
        const result = await suggestReply.mutateAsync(selectedPhone);
        setCompose(prev => prev ? { ...prev, subject: result.subject, body: result.body } : prev);
      } catch {}
    }}
    disabled={suggestReply.isPending || !selectedPhone}
    className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold border border-dashed border-primary/40 text-primary hover:bg-primary/10 hover:border-primary/60 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
  >
    <Wand2 className="w-3.5 h-3.5" />
    {suggestReply.isPending ? "Thinking…" : "Suggest Reply"}
  </button>
  <button onClick={sendCompose} disabled={!compose.to} className="flex items-center gap-2 px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-semibold transition-colors">
    <Send className="w-3.5 h-3.5" />
    Open in {emailSettings.client === "gmail" ? "Gmail" : "Mail App"}
  </button>
</div>
```

## Tests

**File:** `bluemarlin/tests/social/test_119_suggest_reply.py`

```python
# test_119_suggest_reply.py
# Tests for Brief 119 — Suggest email reply endpoint

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "test_pw_119")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from agents.social.webhook_server import app

client = TestClient(app)

def _login():
    r = client.post("/dashboard/api/login", json={"password": "test_pw_119"})
    return r.json()["token"]

def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# --- Test 1: Missing phone returns 400 ---
def test_missing_phone():
    token = _login()
    r = client.post("/dashboard/api/messages/suggest-reply",
                     json={"phone": ""},
                     headers=_auth(token))
    assert r.status_code == 400


# --- Test 2: Unknown phone returns 404 ---
def test_unknown_phone():
    token = _login()
    r = client.post("/dashboard/api/messages/suggest-reply",
                     json={"phone": "0000000000"},
                     headers=_auth(token))
    assert r.status_code == 404


# --- Test 3: No auth returns 401 ---
def test_no_auth():
    r = client.post("/dashboard/api/messages/suggest-reply",
                     json={"phone": "1234567890"})
    assert r.status_code == 401


# --- Test 4: Successful suggestion with mocked Claude ---
@patch("dashboard.api.anthropic")
def test_suggest_reply_success(mock_anthropic_module):
    from shared import state_registry
    phone = "119_test_phone"

    # Seed conversation
    state_registry.wa_store_message(phone, "user", "Hi, I want to book the sunset cruise for 2 people")
    state_registry.wa_store_message(phone, "assistant", "The Sunset Cruise runs daily at 17:30. Price is $65/person. Which date works?")
    state_registry.wa_store_message(phone, "user", "This Friday please")

    # Mock Claude response
    mock_client = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"subject": "Sunset Cruise — Friday Booking", "body": "Hi there,\\n\\nGreat choice! I\\'ve got you down for the Sunset Cruise this Friday at 17:30 for 2 guests.\\n\\nMarina\\nBlueFinn Charters Curaçao"}')]
    mock_client.messages.create.return_value = mock_response

    token = _login()
    r = client.post("/dashboard/api/messages/suggest-reply",
                     json={"phone": phone},
                     headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert "subject" in data
    assert "body" in data
    assert len(data["subject"]) > 0
    assert len(data["body"]) > 0
    assert data["subject"] == "Sunset Cruise — Friday Booking"
    assert "Marina" in data["body"]
    assert "BlueFinn" in data["body"]

    # Verify Claude was called with conversation context
    call_args = mock_client.messages.create.call_args
    assert call_args is not None
    user_msg = call_args.kwargs.get("messages", [{}])[0].get("content", "")
    assert "sunset cruise" in user_msg.lower()
    assert "Friday" in user_msg

    # Cleanup
    state_registry._get_conn().execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    state_registry._get_conn().commit()


# --- Test 5: JSON parse failure falls back gracefully ---
@patch("dashboard.api.anthropic")
def test_suggest_reply_json_fallback(mock_anthropic_module):
    from shared import state_registry
    phone = "119_fallback_phone"

    state_registry.wa_store_message(phone, "user", "Hello")

    # Mock Claude returning non-JSON
    mock_client = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Hi there, thanks for reaching out! Let me help you.")]
    mock_client.messages.create.return_value = mock_response

    token = _login()
    r = client.post("/dashboard/api/messages/suggest-reply",
                     json={"phone": phone},
                     headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert "subject" in data
    assert "body" in data
    # Fallback: body should contain the raw text
    assert "thanks for reaching out" in data["body"].lower()

    # Cleanup
    state_registry._get_conn().execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    state_registry._get_conn().commit()
```

## Success Condition
Dashboard → Messages → open conversation → email icon → "Suggest Reply" button works, fills subject + body with contextual email.

## Rollback
Backend: remove the endpoint + imports from api.py, then `systemctl restart bluemarlin-social` on VPS. Frontend: revert 3 files in dashboard repo.
