# BRIEF 201 — dm_agent em-dash strip + dashboard message field aliases

**Status:** Draft
**Files:** `wtyj/agents/social/dm_agent.py`, `wtyj/shared/state_registry.py`, `wtyj/dashboard/api.py`, `wtyj/tests/test_201_dm_agent_em_dash.py` (new), `wtyj/docs/project_open_work.md`
**Depends on:** Brief 200 (api.unboks.org cutover live)
**Blocks:** Nothing — both fixes are independent and targeted.

---

## Context

Two visible bugs in the post-Brief-200 cutover that need fixing in one tight brief:

### Bug F — dm_agent em-dashes despite brand_voice_rules

The `agent_persona.brand_voice_rules` in `clients/unboks/config/client.json` says *"Never use em-dashes or en-dashes"* — but Claude ignores this consistently. Every reply calvin-csa sent during testing on `+599 968 81585` contained at least one em-dash (`—`). Claude's prompt-following on punctuation rules is unreliable; deterministic post-processing is the correct mechanism.

Marina (the email + booking-flow agent at `wtyj/agents/marina/marina_agent.py`) handles a similar problem with a backend strip post-LLM-call. The dm_agent path (`wtyj/agents/social/dm_agent.py:118+`) — used by every `booking_flow:false` tenant including unboks — has no such strip. Replies go out raw.

### Bug — dashboard "can't open conversations"

After Brief 200's cutover (`api.unboks.org` live, dashboard.unboks.org now talking to our Python backend), the inbox correctly lists the 2 unboks conversations. But clicking into a conversation appears broken — the message bubbles are blank.

**Root cause** (verified by reading SR's frontend at `calvin835/unboks-dashboard-api/artifacts/unboks/src/pages/Inbox.tsx`):

```
Line 53:  const isAssistant = msg.role === "assistant";
Line 64:  {msg.content}                                ← reads `content`
Line 65:  {msg.timestamp && (                          ← reads `timestamp`
Line 432: messages.map((msg, i) => <MessageBubble key={msg.id ?? i} msg={msg} />)
                                                       ← reads `id`
```

The detail view (rendering individual messages) reads `msg.content`, `msg.timestamp`, and `msg.id`. Our backend's `get_conversation()` endpoint returns rows with `text`, `created_at`, and no `id` (the schema column exists in `whatsapp_threads.id` but isn't selected by `wa_get_full_history`):

```
wtyj/shared/state_registry.py:931-940
  wa_get_full_history()
    SELECT role, text, created_at FROM whatsapp_threads ...
    return [{"role": r[0], "text": r[1], "created_at": r[2]} for r in rows]
```

So when the React component renders, `msg.content` is `undefined` → empty bubble. From the user's perspective: the conversation "won't open" — actually it opens, just renders blank.

**Note on SR's frontend list view** — `safePreview()` in `artifacts/unboks/src/lib/conversation-mapper.ts:46+` is defensive: it tries `lastMessage`, `latestMessage`, `last_message`, `preview`, `snippet`, `body`, `text` in priority order. So our LIST endpoint's `last_message` field gets picked up correctly — that's why the inbox-list shows the 2 conversations. The detail view's `MessageBubble` component is NOT defensive (direct `msg.content` access) — that's why detail rendering breaks.

### Why these are bundled

Both are short, low-risk, and surfaced from the same testing session. Em-dash strip is ~2 lines; field aliases are ~5 lines. One brief, one deploy, both shipped.

### What's NOT in scope (captured for later)

- **JWT expiration handling** — During testing, the JWT minted on login expired between the smoke test (early in session) and a later detail-endpoint call, causing 401. The frontend doesn't refresh tokens or redirect-on-401. This is a separate frontend issue; capturing in `project_open_work.md` as a follow-up.
- **Other detail-view fields** — `detail.escalated`, `detail.escalationResolved`, `detail.escalationMode`, `detail.escalationSummary`. Frontend handles these gracefully via `!detail.escalated` short-circuit, so undefined is fine. Not blocking the bubble render.
- **Message preview camelCase aliases** for the LIST endpoint — frontend's `safePreview` tries snake_case `last_message` already, so no work needed. (Other camelCase aliases like `lastMessage` are checked first as fallback, but snake_case works.)
- **Marina-as-template anti-pattern** — Benson's call: Marina was fine-tuned for BlueMarlin specifically, not a clean template. We need actual reusable templates for agents going forward, not "copy from Marina." Captured as a follow-up note in `project_open_work.md`. Not actioned here.

---

## Why This Approach

**Em-dash strip — considered alternatives:**

1. **Strengthen the prompt.** Already tried — `brand_voice_rules` explicitly forbids em-dashes, Claude still emits them. Prompt reliability on this kind of micro-rule is bad. Rejected.
2. **Replace em-dash with `, ` (comma + space).** Slightly cleaner typography but adds spaces that the existing double-space normalizer then collapses awkwardly in some cases. More moving parts.
3. **Replace em-dash with just `,` (the chosen path).** Per Benson 2026-05-05: "just do `,` for now." Simplest, deterministic, low risk. If "word — word" becomes "word , word" with awkward space-comma-space, we iterate later. Em-dash only — no en-dash, no other punctuation.
4. **Do nothing in dm_agent — refactor Marina's strip into shared helper first.** Benson's call: Marina is BlueMarlin-specific, not a template. Don't generalize from her. Just copy the minimal pattern into dm_agent. Generalization is a separate later concern.

**Field aliases — considered alternatives:**

1. **Change SR's frontend to read `text`/`created_at`.** Possible but requires SR to push a frontend change, his territory. Slower iteration.
2. **Replace `text`→`content`, `created_at`→`timestamp` in our backend response (breaking change).** Would silently break any other client of our `/messages/conversations/{phone}` endpoint that reads the existing names. We don't know all consumers (control panel? legacy dashboard build?). Rejected.
3. **Add ALIASES — return both old and new field names.** Backward-compatible, additive only, safe to ship. Chosen.
4. **Build a response-transformer layer.** Cleaner long-term but premature for a 5-line fix. Rejected.

The aliases are added at the dashboard API layer (`wtyj/dashboard/api.py`), NOT in `state_registry.wa_get_full_history()` itself, with one exception: `id` requires changing the SQL `SELECT` clause, which IS a state_registry change. The alias mapping (text→content, created_at→timestamp) lives in the API endpoint to keep the data layer clean.

---

## Instructions

### Part 1 — Em-dash strip in dm_agent

**`wtyj/agents/social/dm_agent.py`** — at line 169 (existing post-process block), insert one line AFTER the `[BOOKING_REF]`/`[PAYMENT_LINK]` strip and BEFORE the markdown code-fence strip. The block currently looks like:

```python
        # Safety net: strip unreplaced booking placeholders
        reply = reply.replace("[BOOKING_REF]", "").replace("[PAYMENT_LINK]", "")
        # Strip markdown code fences if present
        reply = re.sub(r"^```(?:json)?\s*", "", reply)
```

Add a new line between them:

```python
        # Safety net: strip unreplaced booking placeholders
        reply = reply.replace("[BOOKING_REF]", "").replace("[PAYMENT_LINK]", "")
        # Brief 201: strip em-dashes (Claude ignores brand_voice_rules on this).
        # Em-dash only — en-dashes and hyphens left alone.
        reply = reply.replace("—", ",")
        # Strip markdown code fences if present
        reply = re.sub(r"^```(?:json)?\s*", "", reply)
```

That's the entire em-dash change. The existing double-space normalizer at line 174-175 (`while "  " in reply: reply = reply.replace("  ", " ")`) handles any cases where pre-existing whitespace around the em-dash leaves "  ," (double space + comma) — though `replace("—", ",")` only collapses the em-dash itself, not surrounding whitespace, so the input "word — word" produces "word , word" (single-space-comma-single-space). The double-space normalizer doesn't fix that, but it's readable. Per Benson's "just do `,` for now" — we're not optimizing typography; if it bothers, we iterate.

### Part 2 — Add `id` to wa_get_full_history return rows

**`wtyj/shared/state_registry.py`** — at `wa_get_full_history()` (line 931-940). The current implementation:

```python
def wa_get_full_history(phone: str, limit: int = 100) -> list:
    """Get full conversation history for a phone number (no 24h cutoff). Oldest first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, text, created_at FROM whatsapp_threads "
        "WHERE phone = ? ORDER BY created_at ASC LIMIT ?",
        (phone, limit)
    ).fetchall()
    conn.close()
    return [{"role": r[0], "text": r[1], "created_at": r[2]} for r in rows]
```

Change SELECT and dict mapping to include `id`:

```python
def wa_get_full_history(phone: str, limit: int = 100) -> list:
    """Get full conversation history for a phone number (no 24h cutoff). Oldest first.
    Brief 201: also returns row id (SQLite autoincrement) so frontends can use it
    as a stable React key."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, role, text, created_at FROM whatsapp_threads "
        "WHERE phone = ? ORDER BY created_at ASC LIMIT ?",
        (phone, limit)
    ).fetchall()
    conn.close()
    return [{"id": r[0], "role": r[1], "text": r[2], "created_at": r[3]} for r in rows]
```

This is additive — every existing caller that uses `role`, `text`, or `created_at` continues to work. The new `id` field is just available as an extra dict key.

**Caller verification (grep performed):** three callsites consume `wa_get_full_history()`:
1. `wtyj/dashboard/api.py:891` — `get_conversation()` endpoint, modified by Part 3 below.
2. `wtyj/dashboard/api.py:1016` — `suggest_reply()` endpoint. Reads via `m.get(...)` dict access only. Adding `id` does not break.
3. `wtyj/agents/social/social_agent.py:693` — escalation chat-log builder. Iterates with `_em['role']`, `_em.get('created_at', '')`, `_em.get('text', '')`. Dict-key access only, no positional/index access. Adding `id` does not break.

No callers consume the raw `cursor.fetchall()` rows by index — the function returns dicts, and no caller does `r[0]/r[1]/r[2]`-style access. Safe additive change.

### Part 3 — Add field aliases at dashboard API layer

**`wtyj/dashboard/api.py`** — `get_conversation()` at line 884-897. Current:

```python
@router.get("/messages/conversations/{phone:path}", dependencies=[Depends(_check_auth)])
async def get_conversation(phone: str):
    """Get full conversation thread + booking state. Brief 171: routes to the
    email helper when phone starts with 'email::'."""
    if phone.startswith("email::"):
        thread_key = phone[len("email::"):]
        return state_registry.email_get_conversation(thread_key)
    messages = state_registry.wa_get_full_history(phone, limit=200)
    booking_state = state_registry.wa_get_booking_state(phone)
    return {
        "phone": phone,
        "messages": messages,
        "booking_state": booking_state,
    }
```

Modify the WhatsApp branch to enrich each message with frontend-expected aliases:

```python
@router.get("/messages/conversations/{phone:path}", dependencies=[Depends(_check_auth)])
async def get_conversation(phone: str):
    """Get full conversation thread + booking state. Brief 171: routes to the
    email helper when phone starts with 'email::'. Brief 201: each message dict
    is enriched with `content` (alias of text) and `timestamp` (alias of
    created_at) so SR's dashboard frontend can read them directly. Original
    `text`/`created_at` keys preserved for backward compat."""
    if phone.startswith("email::"):
        thread_key = phone[len("email::"):]
        return state_registry.email_get_conversation(thread_key)
    messages = state_registry.wa_get_full_history(phone, limit=200)
    # Brief 201: add frontend-friendly field aliases without removing originals.
    for m in messages:
        m["content"] = m.get("text", "")
        m["timestamp"] = m.get("created_at", "")
    booking_state = state_registry.wa_get_booking_state(phone)
    return {
        "phone": phone,
        "messages": messages,
        "booking_state": booking_state,
    }
```

The for-loop mutates each dict in place. Since `wa_get_full_history` builds fresh dicts on every call (line 940), there's no shared-state risk.

### Part 4 — Update project_open_work.md

**`wtyj/docs/project_open_work.md`** — append two new short notes near the top (after the HIGH PRIORITY section but before "## The SOT spec"):

```markdown
## Marina is not a template (added 2026-05-05)

Marina (`wtyj/agents/marina/marina_agent.py`) was fine-tuned specifically for BlueMarlin Charters during Phase 1. She has BlueMarlin-specific prompt scaffolding, BlueMarlin-specific extraction fields, BlueMarlin-specific booking flow, and BlueMarlin-specific tone defaults. **Do NOT use Marina as the template for new agents.** When we surface a pattern that needs to be shared between agents (e.g., em-dash strip, brand-voice enforcement, escalation triggers), the right move is to extract it into a shared helper or modular agent base — NOT to "copy what Marina does."

Action: when we need our second-or-later cross-agent shared behavior, design a real reusable template at `wtyj/agents/_shared/` or similar. Marina becomes a thin tenant-specialized layer over the base, not the canonical reference. Out of scope for any single brief; flagging as the principle going forward.

## Frontend-side follow-ups from Brief 200 cutover (added 2026-05-05)

After the api.unboks.org cutover, two frontend-handling issues emerged. Both are SR's territory (frontend repo `calvin835/unboks-dashboard-api/artifacts/unboks/`); flagging here so the next session knows:

- **JWT expiration handling.** Our `_check_auth` dependency rejects expired tokens with 401. Frontend doesn't refresh tokens or redirect-on-401, so users see broken UI after idle. Fix on frontend: detect 401 in axios/fetch interceptor, clear stored token, redirect to login.
- **Detail view defensiveness.** `Inbox.tsx` line 64 reads `msg.content` directly with no fallback to `msg.text`. Brief 201 worked around by adding aliases backend-side. Frontend should mirror the `safePreview` defensive-read pattern in `MessageBubble` to handle backend shape variation gracefully going forward.
```

---

## Tests

New file: `wtyj/tests/test_201_dm_agent_em_dash.py` — 4 tests covering both parts.

```python
"""Brief 201: em-dash strip in dm_agent + dashboard message field aliases."""

import os

# Match established test pattern (see test_125, test_173, test_186, etc.) —
# DASHBOARD_PASSWORD must be set BEFORE importing the dashboard module so the
# auth handler reads our test password rather than a missing env var.
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from unittest.mock import MagicMock, patch

import pytest


# ── Part 1: em-dash strip ────────────────────────────────────────────────────
# Module path is `agents.social.dm_agent` (NOT `wtyj.agents.social.dm_agent`)
# because conftest.py adds `wtyj/` to sys.path — see existing tests like
# test_068_pipeline.py:144 which uses `agents.social.social_agent.marina_agent`.

@patch("agents.social.dm_agent.state_registry")
@patch("agents.social.dm_agent.config_loader")
@patch("agents.social.dm_agent.anthropic.Anthropic")
@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
def test_em_dash_replaced_with_comma(mock_anthropic, mock_config, mock_state):
    """An em-dash in Claude's reply is replaced with a comma."""
    from agents.social import dm_agent

    # Stub config_loader so _build_dm_system_prompt doesn't blow up
    mock_config.get_business.return_value = {"agent_name": "Calvin", "name": "Unboks", "whatsapp": "", "languages": ["English"]}
    mock_config.get_common_sense_knowledge.return_value = {}
    mock_config.get_services.return_value = {}
    mock_config.get_faq.return_value = {}
    mock_config.get_raw.return_value = {"terminology": {}}
    mock_state.dm_get_history.return_value = []

    # Stub Claude response with em-dash in reply
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="Hello — how can I help?")]
    mock_msg.usage = None
    mock_anthropic.return_value.messages.create.return_value = mock_msg

    reply = dm_agent.handle_incoming_dm({
        "conversation_id": "test-conv",
        "platform": "whatsapp",
        "channel": "whatsapp",
        "sender_name": "TestUser",
        "text": "hi",
        "account_id": "acct-1",
    })

    assert "—" not in reply
    assert "," in reply
    # The space normalizer collapses double spaces but leaves single-space-comma-single-space.
    # We verify the em-dash is gone and a comma is present — not the exact whitespace.


@patch("agents.social.dm_agent.state_registry")
@patch("agents.social.dm_agent.config_loader")
@patch("agents.social.dm_agent.anthropic.Anthropic")
@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
def test_no_em_dash_passes_through_unchanged(mock_anthropic, mock_config, mock_state):
    """A reply with no em-dash is returned unchanged (no false replacements)."""
    from agents.social import dm_agent

    mock_config.get_business.return_value = {"agent_name": "Calvin", "name": "Unboks", "whatsapp": "", "languages": ["English"]}
    mock_config.get_common_sense_knowledge.return_value = {}
    mock_config.get_services.return_value = {}
    mock_config.get_faq.return_value = {}
    mock_config.get_raw.return_value = {"terminology": {}}
    mock_state.dm_get_history.return_value = []

    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="Hello, how can I help?")]
    mock_msg.usage = None
    mock_anthropic.return_value.messages.create.return_value = mock_msg

    reply = dm_agent.handle_incoming_dm({
        "conversation_id": "test-conv-2",
        "platform": "whatsapp",
        "channel": "whatsapp",
        "sender_name": "TestUser",
        "text": "hi",
        "account_id": "acct-1",
    })

    assert reply == "Hello, how can I help?"


# ── Part 2: dashboard detail-endpoint field aliases ───────────────────────

def test_wa_get_full_history_includes_id():
    """state_registry.wa_get_full_history returns dicts that include the row id."""
    from shared import state_registry

    # Use a unique phone to isolate from other tests
    phone = "test-201-phone-aliases"
    state_registry.wa_store_message(phone, "user", "first message")
    state_registry.wa_store_message(phone, "assistant", "second message")

    history = state_registry.wa_get_full_history(phone, limit=10)
    assert len(history) == 2
    assert "id" in history[0]
    assert "id" in history[1]
    assert isinstance(history[0]["id"], int)
    # IDs are strictly increasing (insertion order matches created_at order)
    assert history[1]["id"] > history[0]["id"]


def test_get_conversation_endpoint_adds_content_and_timestamp_aliases():
    """The dashboard get_conversation endpoint enriches messages with `content`
    and `timestamp` aliases (matching SR's frontend's expected shape)."""
    from fastapi.testclient import TestClient
    from agents.social.webhook_server import app
    from shared import state_registry

    # Seed the DB with two messages on a unique phone
    phone = "test-201-aliases-phone"
    state_registry.wa_store_message(phone, "user", "incoming text")
    state_registry.wa_store_message(phone, "assistant", "outgoing text")

    client = TestClient(app)

    # Login first to get auth token. Password matches the module-level
    # os.environ.setdefault("DASHBOARD_PASSWORD", "testpass") at the top.
    login = client.post("/dashboard/api/login", json={"password": "testpass"})
    assert login.status_code == 200
    token = login.json()["token"]

    # Hit the detail endpoint
    resp = client.get(
        f"/dashboard/api/messages/conversations/{phone}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "messages" in body
    assert len(body["messages"]) == 2

    for m in body["messages"]:
        # Originals preserved (backward-compat)
        assert "text" in m
        assert "created_at" in m
        # New aliases present
        assert "content" in m
        assert "timestamp" in m
        # Aliases match originals
        assert m["content"] == m["text"]
        assert m["timestamp"] == m["created_at"]
        # id passes through from state_registry
        assert "id" in m
```

**Why these 4 tests:**

1. **em-dash replaced with comma** — verifies the substitution actually happens after the LLM call.
2. **no em-dash → no change** — guards against future regression where the strip accidentally mutates non-em-dash content.
3. **wa_get_full_history includes id** — verifies the state_registry change. Tests the data layer separately from the API layer.
4. **dashboard endpoint adds aliases** — verifies the integration: real DB write → real API call → response includes aliases. Exercises the actual code path SR's frontend hits.

No source-level string guards. No mocks where real behavior is testable. The em-dash tests mock only the Anthropic SDK (since we don't want a real API call); the alias tests use the real DB + real router.

---

## Success Condition

After this brief:

1. Sending a WhatsApp/IG/FB DM to calvin-csa produces a reply with NO em-dashes (the LLM may still generate them, but the post-process strips before send).
2. Opening any conversation in `https://dashboard.unboks.org` shows the full message history correctly rendered — bubbles populated with text and timestamps, not blank.
3. The legacy `api.wetakeyourjob.com/unboks/dashboard/api/messages/conversations/{phone}` endpoint continues to return the original `text`/`created_at` field shape (backward compat preserved).
4. Pytest goes from 907 → 911 passing (4 new), 0 failures.

---

## Rollback

`git revert <commit>` and redeploy. Each change is additive:

- Removing the em-dash strip line restores the previous (em-dash-emitting) behavior. Customers see em-dashes again. No data corruption.
- Removing `id` from `wa_get_full_history`'s SELECT/return restores the previous 3-field row shape. No callers downstream require `id` (we just added it; nothing else reads it yet).
- Removing the alias enrichment in `get_conversation()` restores the previous 3-field message shape. Frontend goes back to rendering blank message bubbles — same state as before this brief.

No DB schema migration, no data writes, no irreversible ops.
