# BRIEF 206 — Real escalation handler for dm_agent + concrete escalation script + tenant contact_methods + suppress booking-redirect for booking_flow:false

**Status:** Draft
**Files:** `wtyj/agents/social/dm_agent.py`, `clients/unboks/config/client.json`, `wtyj/tests/test_206_dm_escalation.py` (new)
**Depends on:** Brief 203 (master prompt + freeform_notes injection live), Brief 188 (conversation_status + create_pending_notification helpers)
**Blocks:** Frontend display of unboks escalations (SR's territory; backend will populate the rows, frontend already renders Marina escalations from the same table).

---

## Context

SR asked "escalation logic, do we have it? what is it? doesn't work now." Live conversation history confirms three concrete problems on the unboks tenant (`booking_flow: false` → `dm_agent` path):

1. **Calvin-csa lies about flagging.** Sample replies pulled from `whatsapp_threads`:
   - *"I've flagged this conversation for a human to pick up. Someone will follow up with you here shortly."*
   - *"Of course. I'll flag this conversation for a human to follow up with you."*
   - *"Let me flag this conversation so a human can follow up with you directly here."*

   `dm_agent.py:handle_incoming_dm` has zero escalation code. No `pending_notifications` row, no `fully_escalated` flag, no operator alert. The dashboard Escalations tab shows nothing for unboks. Every "I've flagged" reply is a lie.

2. **Recursive WhatsApp redirect.** Calvin-csa keeps sending: *"Reach out directly on WhatsApp at wa.me/59996881585"* — to customers who are actively texting that exact number. Source: hardcoded `BOOKING REDIRECT` block in `_build_dm_system_prompt` (line ~76 area in current dm_agent.py post-Brief-203) that injects `wa.me/{wa_link}` regardless of booking flow. Block name says "BOOKING REDIRECT" but injects for non-booking tenants too because the conditional was never added.

3. **Forbidden phrasing leaks through SR's master prompt.** Live samples include *"Of course"* (avoid-list), *"I apologize for the confusion"* (filler), *"Since this involves a paid order"* — that last one is explicitly forbidden by SR's master prompt: *"Do not say 'paid booking' unless the user has bookings and payments."* Master prompt covers tone and broad principles but has NO concrete script for the moment-of-escalation. Claude improvises and the improvisation drifts.

### Root cause analysis

Three intertwined gaps:
- **Backend has no dm_agent escalation handler.** Marina's path uses `state_registry.create_pending_notification` to create rows that surface in the dashboard's Escalations tab. Dm_agent path doesn't. Need to add it.
- **Master prompt's "Escalations:" section is product-explanation, not behavior-script.** It describes what to TELL A PROSPECT WHO ASKS about escalations, not what to ACTUALLY SAY when a customer triggers escalation in real time. Claude has no script to anchor on, so it invents.
- **dm_agent's hardcoded BOOKING REDIRECT block** is the only "redirect to a human" template Claude has structurally. Concrete instructions beat abstract voice rules. Claude follows the block even in non-booking contexts.

### Out of scope

- Backfilling the existing "I've flagged" replies (~5 historical lies in unboks DB). Roll forward only; the lies are stuck.
- Frontend rendering of unboks escalations in the Escalations tab (SR's territory; the backend will populate rows in the same table Marina escalations use, so existing renderer should pick them up).
- Migrating dm_agent's prompt output from plain text to structured JSON (bigger refactor; the sentinel-based escalation signal we use here is the simpler path for now).
- Backfill / migration of historical conversations to set `escalated: true` on past escalation moments.

---

## Why This Approach

**Considered alternatives for the escalation-detection signal:**

1. **Keyword match on Claude's reply** ("human", "team", "follow up directly"). Fragile — Claude might say "human" in non-escalation contexts. Rejected.
2. **Migrate dm_agent to structured JSON output** with `requires_human: true` field (Marina's pattern). Cleaner long-term but ~50-line refactor of the prompt + post-process. Rejected for first iteration.
3. **Sentinel in plain text reply.** Add `[ESCALATE]` line to Claude's master prompt: "If you decide to escalate this, end your reply with [ESCALATE] on its own line. It will be stripped before sending." Post-process detects sentinel, strips it, creates `pending_notifications`. Single Claude call (Rule 1 preserved), reliable signal, no JSON refactor. **Chosen.**
4. **Detect escalation by inbound message intent** (refund, complaint keywords). Doesn't cover cases where Claude decides to escalate based on context. Rejected.

**Considered alternatives for fixing the BOOKING REDIRECT recursion:**

1. **Suppress the entire block when `booking_flow: false`.** Simplest. The block is bookings-specific by name and content. Non-booking tenants don't need it. **Chosen.**
2. **Make the redirect target configurable via client.json.** Bigger; ties into contact_methods anyway. We add contact_methods separately and the master prompt references it. The booking redirect block specifically can just be dropped for non-booking tenants. Rejected for this brief.
3. **Detect "user is on the same channel as the redirect" and suppress dynamically.** Cute but over-engineered. Rejected.

**Tradeoff:** the sentinel approach trusts Claude to emit `[ESCALATE]` reliably at appropriate moments. Master prompt's Escalation Script section will give it concrete trigger criteria. False positives possible but bounded — operator can dismiss in the dashboard.

**Tradeoff:** sentinel-based escalation matches on a specific token; Claude could miss it (no escalation when one was needed) or over-emit it (escalation when not needed). For first-stage demo with low volume, either failure mode is recoverable. Brief includes a rate-limit note to prevent escalation flooding from a stuck conversation.

---

## Instructions

### Part 1 — Suppress BOOKING REDIRECT for `booking_flow: false`

In `wtyj/agents/social/dm_agent.py:_build_dm_system_prompt()`, the master-prompt branch (post-Brief-203) currently always includes `booking_redirect_block`. Wrap inclusion in a feature check.

Add a config read after the existing `business`/`csk`/`trips`/`faq`/`persona` reads:
```python
booking_flow = config_loader.get_raw().get("features", {}).get("booking_flow", True)
```

Then in BOTH branches (master prompt + fallback), conditionally include `booking_redirect_block`:

**Master prompt branch:**
```python
if master_prompt:
    parts = [intro, qa_role_short, master_prompt, services_block, faq_block]
    if booking_flow:
        parts.append(booking_redirect_block)
    parts.extend([language_block, emoji_block, output_rule])
    return "\n\n".join(parts)
```

**Fallback branch (BlueMarlin path even though it doesn't use dm_agent today):**
Same conditional pattern — only append `booking_redirect_block` and the booking-related WRITING STYLE bullets if `booking_flow` is true. Conservatively keep ALL hardcoded blocks for the fallback path since BlueMarlin/Adamus are `booking_flow: true` regardless.

Only the master-prompt branch adds the conditional skip. Fallback branch stays byte-equivalent to current behavior — defensible because no current tenant exercises the fallback's `booking_flow: false` combination (Marina path handles booking-true tenants; dm_agent fallback is unused in production today).

### Part 2 — Add `contact_methods` block to `clients/unboks/config/client.json`

Add at the top level of `client.json` (sibling to `business`, `agent_persona`, `features`):
```json
"contact_methods": {
  "primary_email": "hello@unboks.org",
  "calendly_url": null,
  "public_form_url": null
}
```

The master prompt (Part 3) references `hello@unboks.org` directly. The other two slots are placeholders SR can fill in later — the prompt only mentions them if they're set.

### Part 3 — Replace `agent_persona.freeform_notes`'s "Escalations:" section in unboks's `client.json`

Find the `"Escalations:"` section in the existing freeform_notes (installed by Brief 203). Replace with two sub-sections: (a) the existing product-explanation guidance for "what to tell a prospect who asks about escalations" — keep mostly intact since it's product info; (b) a new ESCALATION SCRIPT section with concrete moment-of-escalation phrasing.

The replacement text (paste into `freeform_notes` in place of the existing "Escalations:" block):

```
Escalations (when explaining the product to a prospect):
If asked what happens when something needs a human, explain simply.
The dashboard should show:
- the conversation
- the customer's latest message
- the channel it came from
- why Unboks flagged it
- who should handle it, if configured
Escalation examples:
- unclear question
- complaint
- refund request
- urgent issue
- sensitive topic
- request for a human
- order or service issue
- anything needing a decision
Avoid technical terms like "hard escalation" unless the user already understands it.
Use "sent to a human," "flagged in your dashboard," or "sent to the right person."

ESCALATION SCRIPT (when YOU need to actually hand a real conversation to a human, in this conversation, right now):
Trigger this when the customer:
- expresses a complaint, frustration, or anger
- asks for a refund, cancellation, or any payment-related action
- explicitly asks to speak with a person, "real human," "someone who can help," etc.
- raises a legal, regulatory, medical, financial, or sensitive matter
- describes an urgent issue you cannot answer safely from your knowledge base
- repeats a question after you've answered it (signal that the AI answer was wrong or insufficient)

When you trigger an escalation:
1. Acknowledge briefly. One sentence. No "I apologize for the confusion." No "Of course." No filler.
2. Be honest about the handoff: tell them you're getting it to the team. Do NOT say "I've flagged" or "this is flagged" as a past-tense lie. Use present/future tense.
3. Give them the concrete next step: email hello@unboks.org. Tell them they can also stay in this thread and someone from Unboks will reply here when they pick it up.
4. End the escalation message with the literal token [ESCALATE] on its own line. The token will be stripped before sending; the system uses it to flag the conversation in the operator dashboard. NEVER send [ESCALATE] without also handing off honestly in the visible message.

Example escalation reply (good):
"Got it, this needs a person. The fastest way is to email hello@unboks.org so the team can pick it up directly, or you can stay here and someone from Unboks will reply when they're back online.
[ESCALATE]"

Example escalation reply (bad — DO NOT DO):
- "I've flagged this conversation for a human to pick up."  (lying about a past-tense action)
- "Reach out directly on WhatsApp at wa.me/..."  (recursive — the customer is already on WhatsApp talking to that number)
- "Of course. Let me flag this conversation..."  (forbidden filler + lie)
- "Since this involves a paid order..."  (forbidden — Unboks does not have paid orders for this tenant)

If you do NOT need to escalate, do NOT include [ESCALATE]. The token must only appear at the moment of an actual handoff.

CRITICAL: NEVER write the literal token [ESCALATE] when explaining the system to a prospect. If a customer asks "how do escalations work" or "what does Unboks do when a complaint comes in," describe escalations in plain words ("flagged in the dashboard," "sent to the right person") — but DO NOT type the bracket-token. The bracket-token is a system signal, not a product term. Writing it during a product explanation will create a false escalation in the operator dashboard.

Recursive-redirect rule:
You are running on Calvin's WhatsApp number. NEVER tell a customer to "contact Unboks on WhatsApp" — they're already on WhatsApp. The valid public contact channels are:
- email: hello@unboks.org
- (other channels will be configured later)
Use email as the primary handoff target, not WhatsApp.
```

The ESCALATION SCRIPT section gives Claude:
- Concrete trigger criteria (replaces vague "if escalation is needed" guidance)
- Honest handoff phrasing (replaces lying "I've flagged")
- Concrete next step (`hello@unboks.org`, replaces recursive wa.me link)
- Literal sentinel `[ESCALATE]` (the technical signal for backend handler)
- Bad-examples list (anchors against the specific phrases SR caught in production)

### Part 4 — Backend escalation handler in `dm_agent.py:handle_incoming_dm`

After the existing post-process steps (em-dash strip, code-fence strip, double-space normalization) but BEFORE the empty-reply check, detect the `[ESCALATE]` sentinel:

```python
# Brief 206: detect escalation sentinel from master prompt's ESCALATION SCRIPT.
# If present, strip it from the visible reply AND create a pending_notifications
# row so the escalation appears in the operator dashboard. The customer-facing
# reply text is unchanged (sans the sentinel line).
escalate_requested = "[ESCALATE]" in reply
if escalate_requested:
    # Strip sentinel + any trailing whitespace it left behind. Use rsplit to
    # remove the sentinel line cleanly even if it's the last/only line.
    reply = reply.replace("[ESCALATE]", "").rstrip()
    try:
        # Conversation_id is the customer-facing identifier (Zernio hex for
        # WhatsApp/IG/FB DM). channel comes from the inbound message dict.
        # Subject is a short tag; body is the customer's most recent message
        # plus the AI's reply for operator context.
        _company = config_loader.get_business().get("name", "the business")
        _agent = config_loader.get_business().get("agent_name", "AI agent")
        state_registry.create_pending_notification(
            notification_type="escalation",
            channel=channel,
            customer_id=conversation_id,
            customer_name=sender_name or "Unknown contact",
            subject=f"{_agent} escalated a {channel} conversation",
            body=(
                f"Customer message:\n{text}\n\n"
                f"{_agent}'s reply:\n{reply}\n\n"
                f"({_company} — auto-escalated by {_agent} based on conversation context.)"
            ),
        )
        bm_logger.log("dm_escalation_created",
                       conversation_id=conversation_id[:20],
                       channel=channel)
    except Exception as e:
        # Never let an escalation-DB failure break the customer reply.
        bm_logger.log("dm_escalation_create_failed",
                       conversation_id=conversation_id[:20],
                       channel=channel,
                       error=str(e)[:200])
```

The handler:
- Strips the sentinel before the reply ships to the customer
- Creates a `pending_notifications` row using the existing helper (auto-sets `conversation_status` to `"open"` per Brief 188)
- Logs success/failure separately so we can monitor escalation rate
- Wraps in try/except so a DB error never blocks the customer reply

**Ordering matters:** the sentinel detection happens AFTER em-dash strip + code-fence strip + double-space normalization but BEFORE the empty-reply check. If Claude emits ONLY `[ESCALATE]` with no visible message body (which violates the script's instruction), the post-process produces an empty string, the empty-reply check returns "" (no message sent), and the escalation row IS still created. Operator sees the escalation in the dashboard with no AI text — acceptable outcome (signals "Claude wanted to escalate but didn't write anything to the customer," operator picks it up cleanly).

**Rate-limit interaction:** the existing per-conversation rate limit at `_is_rate_limited` (30 replies / hour) still applies. If a stuck conversation generates 30 escalations in an hour, the AI stops replying entirely and additional escalation rows stop being created. Acceptable for now.

---

## Tests

New file: `wtyj/tests/test_206_dm_escalation.py` — 5 tests.

```python
"""Brief 206: dm_agent escalation handler + booking_redirect suppression."""

import os

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from unittest.mock import MagicMock, patch


# ── Part 1: BOOKING REDIRECT block conditional ─────────────────────────────

@patch("agents.social.dm_agent.config_loader")
def test_booking_redirect_omitted_when_booking_flow_false(mock_config):
    """When tenant has booking_flow:false, the BOOKING REDIRECT block is NOT
    included in the rendered system prompt — non-booking tenants don't need
    a recursive 'message us at wa.me/' redirect."""
    from agents.social.dm_agent import _build_dm_system_prompt

    mock_config.get_business.return_value = {
        "agent_name": "Calvin", "name": "Unboks", "whatsapp": "+59912345",
        "languages": ["English"]
    }
    mock_config.get_common_sense_knowledge.return_value = {}
    mock_config.get_services.return_value = {}
    mock_config.get_faq.return_value = {}
    mock_config.get_raw.return_value = {
        "terminology": {},
        "agent_persona": {"freeform_notes": "Master prompt for unboks."},
        "features": {"booking_flow": False},
    }

    prompt = _build_dm_system_prompt("whatsapp")

    # Master prompt content present
    assert "Master prompt for unboks." in prompt
    # Booking redirect block ABSENT
    assert "BOOKING REDIRECT" not in prompt
    assert "wa.me/59912345" not in prompt


@patch("agents.social.dm_agent.config_loader")
def test_booking_redirect_present_when_booking_flow_true(mock_config):
    """When tenant has booking_flow:true (BlueMarlin path), the BOOKING
    REDIRECT block IS included — regression for tenants that need it."""
    from agents.social.dm_agent import _build_dm_system_prompt

    mock_config.get_business.return_value = {
        "agent_name": "Marina", "name": "BlueMarlin", "whatsapp": "+59999999",
        "languages": ["English"], "booking_email": "hello@bluemarlin.com",
    }
    mock_config.get_common_sense_knowledge.return_value = {}
    mock_config.get_services.return_value = {}
    mock_config.get_faq.return_value = {}
    mock_config.get_raw.return_value = {
        "terminology": {"service_label": "trip"},
        "features": {"booking_flow": True},
    }

    prompt = _build_dm_system_prompt("whatsapp")

    # Booking redirect block PRESENT
    assert "BOOKING REDIRECT" in prompt
    assert "wa.me/59999999" in prompt


# ── Part 4: escalation sentinel detection + pending_notification creation ──

@patch("agents.social.dm_agent.state_registry")
@patch("agents.social.dm_agent.config_loader")
@patch("agents.social.dm_agent.anthropic.Anthropic")
def test_escalate_sentinel_creates_pending_notification(
    mock_anthropic, mock_config, mock_state
):
    """When Claude's reply contains [ESCALATE], the sentinel is stripped from
    the visible reply AND a pending_notifications row is created via
    state_registry.create_pending_notification."""
    from agents.social import dm_agent

    mock_config.get_business.return_value = {
        "agent_name": "Calvin", "name": "Unboks", "whatsapp": "",
        "languages": ["English"]
    }
    mock_config.get_common_sense_knowledge.return_value = {}
    mock_config.get_services.return_value = {}
    mock_config.get_faq.return_value = {}
    mock_config.get_raw.return_value = {
        "terminology": {},
        "agent_persona": {"freeform_notes": "Master prompt"},
        "features": {"booking_flow": False},
    }
    mock_state.dm_get_history.return_value = []

    # Claude responds with an escalation reply
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(
        text="Got it, this needs a person. Email hello@unboks.org.\n[ESCALATE]"
    )]
    mock_msg.usage = None
    mock_anthropic.return_value.messages.create.return_value = mock_msg

    reply = dm_agent.handle_incoming_dm({
        "conversation_id": "test-206-conv-id",
        "platform": "whatsapp",
        "channel": "whatsapp",
        "sender_name": "AngryCustomer",
        "text": "I want a refund right now",
        "account_id": "acct-1",
    })

    # Sentinel stripped from visible reply
    assert "[ESCALATE]" not in reply
    # Visible message preserved
    assert "Email hello@unboks.org" in reply
    # Escalation row created with the right payload
    mock_state.create_pending_notification.assert_called_once()
    call = mock_state.create_pending_notification.call_args
    assert call.kwargs["notification_type"] == "escalation"
    assert call.kwargs["channel"] == "whatsapp"
    assert call.kwargs["customer_id"] == "test-206-conv-id"
    assert call.kwargs["customer_name"] == "AngryCustomer"
    # Body should contain the customer's message + Calvin's reply for operator context
    assert "I want a refund right now" in call.kwargs["body"]


@patch("agents.social.dm_agent.state_registry")
@patch("agents.social.dm_agent.config_loader")
@patch("agents.social.dm_agent.anthropic.Anthropic")
def test_no_sentinel_no_escalation_created(
    mock_anthropic, mock_config, mock_state
):
    """Regression: when Claude's reply does NOT contain [ESCALATE], no
    pending_notifications row is created. False-positive guard."""
    from agents.social import dm_agent

    mock_config.get_business.return_value = {
        "agent_name": "Calvin", "name": "Unboks", "whatsapp": "",
        "languages": ["English"]
    }
    mock_config.get_common_sense_knowledge.return_value = {}
    mock_config.get_services.return_value = {}
    mock_config.get_faq.return_value = {}
    mock_config.get_raw.return_value = {
        "terminology": {},
        "agent_persona": {"freeform_notes": "Master prompt"},
        "features": {"booking_flow": False},
    }
    mock_state.dm_get_history.return_value = []

    # Claude responds with a normal Q&A reply, no sentinel
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(
        text="Unboks puts all your messages in one inbox."
    )]
    mock_msg.usage = None
    mock_anthropic.return_value.messages.create.return_value = mock_msg

    reply = dm_agent.handle_incoming_dm({
        "conversation_id": "test-206-noesc",
        "platform": "whatsapp",
        "channel": "whatsapp",
        "sender_name": "Prospect",
        "text": "What does Unboks do?",
        "account_id": "acct-1",
    })

    # Reply unchanged
    assert "Unboks puts all your messages" in reply
    # No escalation created
    mock_state.create_pending_notification.assert_not_called()


@patch("agents.social.dm_agent.state_registry")
@patch("agents.social.dm_agent.config_loader")
@patch("agents.social.dm_agent.anthropic.Anthropic")
def test_escalation_db_failure_does_not_break_reply(
    mock_anthropic, mock_config, mock_state
):
    """If create_pending_notification raises (e.g., DB transient), the
    customer-facing reply still ships (with sentinel stripped). Escalation
    failures are logged but never blocking."""
    from agents.social import dm_agent

    mock_config.get_business.return_value = {
        "agent_name": "Calvin", "name": "Unboks", "whatsapp": "",
        "languages": ["English"]
    }
    mock_config.get_common_sense_knowledge.return_value = {}
    mock_config.get_services.return_value = {}
    mock_config.get_faq.return_value = {}
    mock_config.get_raw.return_value = {
        "terminology": {},
        "agent_persona": {"freeform_notes": "Master prompt"},
        "features": {"booking_flow": False},
    }
    mock_state.dm_get_history.return_value = []
    # DB blows up
    mock_state.create_pending_notification.side_effect = RuntimeError("db down")

    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(
        text="Got it, getting to the team.\n[ESCALATE]"
    )]
    mock_msg.usage = None
    mock_anthropic.return_value.messages.create.return_value = mock_msg

    reply = dm_agent.handle_incoming_dm({
        "conversation_id": "test-206-dbfail",
        "platform": "whatsapp",
        "channel": "whatsapp",
        "sender_name": "Customer",
        "text": "complaint",
        "account_id": "acct-1",
    })

    # Reply still shipped (with sentinel stripped)
    assert "[ESCALATE]" not in reply
    assert "Got it, getting to the team" in reply
    # Escalation attempt was made (even though it failed)
    mock_state.create_pending_notification.assert_called_once()
```

**Why these 5 tests:**

1. **Booking redirect omitted when `booking_flow:false`** — direct verification of Part 1 for the unboks/dm_agent path.
2. **Booking redirect present when `booking_flow:true`** — regression guard for BlueMarlin/Adamus.
3. **Escalation sentinel creates pending_notification** — exercises the full escalation path. Asserts both stripping behavior and DB write parameters.
4. **No sentinel → no escalation** — false-positive guard. Routine Q&A replies don't accidentally escalate.
5. **DB failure doesn't break reply** — error-handling regression. Ensures the try/except actually swallows DB exceptions instead of letting them propagate.

5 tests, within the 3-5 target range. No source-level string guards; no tautological assertions.

---

## Success Condition

After this brief deploys:

1. Pytest goes from 920 → 925 passing (5 new), 0 failures.
2. unboks's rendered system prompt (verified via `docker exec wtyj-unboks python3 -c '...'`):
   - Contains "ESCALATION SCRIPT" section
   - Does NOT contain "BOOKING REDIRECT" block
   - Contains the email `hello@unboks.org`
   - Does NOT contain "wa.me/59996881585" or "wa.me/" recursive redirect to the same number
3. Manual end-to-end: send calvin-csa a complaint-style message ("I want a refund"). Verify:
   - Reply doesn't contain `[ESCALATE]` (stripped)
   - Reply mentions `hello@unboks.org` as the contact path (not wa.me/)
   - Reply doesn't say "I've flagged" or "Of course" or "paid order"
   - The dashboard's Escalations tab shows a new row for the conversation
   - Log entry `dm_escalation_created` appears in `docker logs wtyj-unboks`

---

## Rollback

`git revert <commit>` and redeploy. Each part reverts cleanly:

- Part 1 (booking_redirect conditional) reverts to always-include — recursive WhatsApp redirect returns for unboks. Acceptable transient state during rollback window.
- Part 2 (`contact_methods` block in client.json) reverts to removed — master prompt's references to `hello@unboks.org` from the freeform_notes content stay (they're just text, no technical break).
- Part 3 (master prompt updates) reverts to the older "Escalations:" product-explanation only — Claude goes back to improvising at escalation moments. Same state as before this brief.
- Part 4 (escalation handler in dm_agent) reverts to no detection — `[ESCALATE]` sentinel emitted by Claude (if any) flows through to the customer as visible text, but no DB row is created. One-day inconvenience until rollback completes.

No DB schema change, no irreversible ops. The `pending_notifications` rows created during the live window remain in the DB after rollback (operator can dismiss them via the dashboard normally).
