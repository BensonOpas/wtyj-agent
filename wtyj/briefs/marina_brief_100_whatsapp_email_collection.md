# BRIEF 100 — WhatsApp Email Collection + Escalation Email Fix
**Status:** Draft | **Files:** `agents/marina/marina_agent.py`, `agents/social/social_agent.py`, `tests/social/test_100_email_collection.py` (NEW) | **Depends on:** Brief 091 (marina_agent current state), Brief 077 (social_agent escalation handler) | **Blocks:** None

## Context
Two related problems. (1) WhatsApp booking flow never collects the customer's email. The system stores the phone number as `customer_email` — a workaround that breaks when we need a real email (Stripe receipts, booking confirmations, cross-channel recognition). (2) WhatsApp full escalation tells the customer "you'll receive an email from our team" but we don't have their email to send to. Both problems are solved by collecting email during the WhatsApp flow.

## Why This Approach
Adding `email` to the extraction fields and asking for it during WhatsApp booking intake is the simplest fix. Marina already asks for name and phone — adding email is natural. For escalation, we check if email is already in fields (from a booking conversation). If not, Marina asks for it before completing the escalation. This avoids promising an email we can't send. The two-step escalation uses a flag (`awaiting_escalation_email`) — same pattern as `awaiting_booking_confirmation`. We don't change the email channel behavior at all — email customers already have an email address.

## Source Material

### New field: email
Added to the extraction list and JSON schema in marina_agent.py prompt. Only extracted when the customer provides it — never inferred.

### WhatsApp-specific booking prompt addition
```
WHATSAPP EMAIL:
When collecting booking details on WhatsApp, also ask for the customer's
email address. It's needed for the booking confirmation and payment receipt.
Ask naturally as part of the intake — e.g. "And your email for the confirmation?"
If they decline or don't provide one, proceed without it.
```

### Channel-aware escalation prompt
```
ESCALATION — WHATSAPP EMAIL RULE:
On WhatsApp, if the customer's email is NOT in the collected fields:
- Do NOT tell them they will receive an email
- Instead, ask for their email: "I'd like to pass this to our team so they
  can help. Could you share your email so they can reach out?"
- Set needs_escalation_email to true in flags
- Do NOT set requires_human yet — wait for the email first

If the customer's email IS already in fields:
- Proceed with normal escalation (set requires_human, give the standard reply)
```

### awaiting_escalation_email state
When `needs_escalation_email` is true in the Claude response:
1. social_agent.py stores the flag
2. Does NOT fire the escalation notification yet
3. Marina's reply asks for email
4. Next message: Claude extracts the email into fields
5. Python detects email is now present + `awaiting_escalation_email` flag
6. Fires the full escalation with the email included
7. Marina tells the customer "our team will reach out to you at {email}"

## Instructions

### Step 1 — Add email field to marina_agent.py prompt

**1a.** In the booking behaviour section (line 222), add `email` to the extraction list:
Change:
```
extract all fields you can find (experience,
date, guests, trip_key, departure_time, customer_name, phone, special_requests).
```
To:
```
extract all fields you can find (experience,
date, guests, trip_key, departure_time, customer_name, phone, email, special_requests).
```

**1b.** In the JSON schema fields section (after line 304 `phone: customer's phone number`), add:
```
    email: customer's email address — only if explicitly provided
```

**1c.** Add WhatsApp email instruction. In the WhatsApp writing style block (inside the `if channel == "whatsapp":` section), add after the existing RULES section (after line 150 "NEVER return an empty reply..."):
```python
            "\n"
            "EMAIL:\n"
            "- When collecting booking details, also ask for the customer's email\n"
            "- It's needed for the booking confirmation\n"
            "- Ask naturally: 'And your email for the confirmation?'\n"
            "- If they decline, proceed without it\n"
```

**1d.** Make the escalation behaviour channel-aware. Replace the current escalation reply instruction (lines 247-254):

Change:
```
When the intent is complaint, refund request, or cancellation, set requires_human
to true. Your reply MUST:
- Acknowledge what the customer said warmly and with genuine empathy
- Tell them exactly: "I've passed this along to our customer care team.
  You can expect an email from info@bluefinncharters.com shortly —
  they'll take great care of you."
- Do NOT ask for booking details, reference numbers, dates, or
  any other information. The crew will handle that.
- Do NOT attempt to resolve the issue or make promises about outcomes.
- Sign off warmly.
```

To:
```
When the intent is complaint, refund request, or cancellation:

EMAIL CHANNEL: Set requires_human to true. Your reply MUST:
- Acknowledge what the customer said warmly and with genuine empathy
- Tell them the team will follow up via email
- Do NOT ask for booking details. The crew will handle that.
- Sign off warmly.

WHATSAPP CHANNEL: Check if an email address is in the collected fields.
- IF email IS in fields: set requires_human to true. Acknowledge warmly
  and tell them the team will reach out at their email.
- IF email is NOT in fields: do NOT set requires_human yet. Instead:
  - Acknowledge warmly
  - Ask for their email: "Could you share your email so our team can follow up?"
  - Set needs_escalation_email to true in flags
  - Do NOT promise an email will come — you don't have one yet

In both cases: do NOT ask for booking details, do NOT attempt to resolve.
```

**1e.** Add `needs_escalation_email` to the flags schema (line 315). Add after `needs_child_ages`:
```
, "needs_escalation_email": <true when a WhatsApp escalation needs the customer's email before proceeding — omit or false otherwise>
```

**1f.** Update marina_agent.py header to `# Last modified: Brief 100`.

### Step 2 — Handle email in social_agent.py

**2a.** In the escalation handler (around line 538), add a check before firing the full escalation. Replace:

```python
    # Step 7.6: Full escalation — requires_human, holding reply to customer
    if not _skip_booking and result.get("requires_human"):
```

With:

```python
    # Step 7.5: Awaiting escalation email — Claude asked for email, waiting for response
    if flags.get("awaiting_escalation_email") and fields.get("email"):
        # Email provided — now fire the escalation
        flags.pop("awaiting_escalation_email", None)
        flags.pop("needs_escalation_email", None)
        result["requires_human"] = True
        # Claude should have set requires_human now, but force it
        bm_logger.log("whatsapp_escalation_email_received", phone=phone,
                      email=fields.get("email", "")[:50])

    # Step 7.55: Needs escalation email — hold the escalation, ask for email
    if not _skip_booking and result.get("flags", {}).get("needs_escalation_email"):
        flags["awaiting_escalation_email"] = True
        reply_text = result["reply"]  # Claude's reply asking for email
        _skip_booking = True

    # Step 7.6: Full escalation — requires_human, holding reply to customer
    if not _skip_booking and result.get("requires_human"):
```

**2b.** In the escalation notification body (around line 579), add the customer's email if available:

Change:
```python
        _esc_body = (
            f"=== CUSTOMER ===\n"
            f"WhatsApp: {phone}\n"
            f"Name: {_cname}\n\n"
```

To:
```python
        _customer_email = fields.get("email", "")
        _esc_body = (
            f"=== CUSTOMER ===\n"
            f"WhatsApp: {phone}\n"
            f"Name: {_cname}\n"
            f"Email: {_customer_email or '(not provided)'}\n\n"
```

**2c.** In the booking storage calls, use the real email when available. Find both places where `customer_email=phone` is used and change to:
```python
customer_email=fields.get("email") or phone
```
There are two occurrences: in `create_soft_hold` (around line 452) and in `save_booking` (around line 689).

**2d.** Add `email` to `_PERSISTENT_FIELDS` (around line 31). Change:
```python
_PERSISTENT_FIELDS = {"customer_name", "phone"}
```
To:
```python
_PERSISTENT_FIELDS = {"customer_name", "phone", "email"}
```
This preserves the email across multi-trip resets and stale conversation resets.

**2e.** Add `awaiting_escalation_email` and `needs_escalation_email` to `_BOOKING_FLAGS_TO_RESET` (around line 22-29). Add both to the set so they get cleared on booking reset and stale conversation reset.

**2f.** Update social_agent.py header to `# Last modified: Brief 100`.

### Step 3 — Create test file

Create `tests/social/test_100_email_collection.py`:

**Setup:** sys.path, env vars.

**Imports:**
```python
from agents.social.social_agent import handle_incoming_whatsapp_message
from agents.marina.marina_agent import _build_system_prompt, _build_prompt
from shared import state_registry
```

**Helpers:**
- `_cleanup_phone(phone)` — same as test_077 pattern
- `_base_result(**overrides)` — same as test_077 pattern

**Tests (8 total):**

1. **`test_whatsapp_prompt_includes_email_field`** — Call `_build_system_prompt({}, channel="whatsapp")`. Assert contains `"email"` in the fields section. Assert contains `"EMAIL:"` in the writing style section.

2. **`test_email_prompt_no_email_section`** — Call `_build_system_prompt({}, channel="email")`. Assert does NOT contain `"EMAIL:\n"` (the WhatsApp-specific email collection instruction).

3. **`test_whatsapp_escalation_prompt_channel_aware`** — Call `_build_system_prompt({}, channel="whatsapp")`. Assert contains `"needs_escalation_email"`. Assert contains `"WHATSAPP CHANNEL"`.

4. **`test_escalation_with_email_fires_normally`** — Mock marina_agent to return `requires_human=True` with `fields={"email": "john@test.com"}`. Call `handle_incoming_whatsapp_message(msg)`. Assert `flags["fully_escalated"]` is True. Assert a pending_notification was created. Cleanup.

5. **`test_escalation_without_email_asks_for_it`** — Mock marina_agent to return `needs_escalation_email=True` in flags, `requires_human=False`, with a reply asking for email. Call `handle_incoming_whatsapp_message(msg)`. Assert `flags["awaiting_escalation_email"]` is True. Assert NO pending_notification was created (escalation not fired yet). Cleanup.

6. **`test_escalation_email_provided_fires_escalation`** — Set up state: `awaiting_escalation_email=True` in flags, save via `wa_save_booking_state`. Mock marina_agent to return `intents=["complaint"]`, `fields={"email": "john@test.com"}`, `requires_human=False` (Step 7.5 will force it to True), `reply="Our team will reach out to you."`. Call `handle_incoming_whatsapp_message(msg)`. Fetch state back. Assert `flags["fully_escalated"]` is True. Assert `awaiting_escalation_email` is NOT in flags. Assert a pending_notification was created for this phone. Cleanup.

7. **`test_booking_stores_real_email`** — Mock marina_agent to return booking fields including `email: "jane@test.com"`, `booking_confirmed=True`. Mock calendar/payment. Call `handle_incoming_whatsapp_message(msg)`. Check `state_registry.get_booking(ref)`. Assert `customer_email == "jane@test.com"` (not the phone number). Cleanup.

8. **`test_booking_stores_phone_when_no_email`** — Same as test 7 but without email in fields. Assert `customer_email` is the phone number (fallback behavior preserved). Cleanup.

## Tests
Run: `cd bluemarlin && python3 -m pytest tests/social/test_100_email_collection.py -v`

All 8 tests must pass.

## Success Condition
WhatsApp booking flow asks for email as part of intake. Escalation on WhatsApp asks for email before promising one. The real email is stored in bookings instead of the phone number. Escalation notifications include the customer's email when available.

## Rollback
1. Revert `agents/marina/marina_agent.py` to Brief 091 version
2. Revert `agents/social/social_agent.py` to Brief 091 version
3. Delete `tests/social/test_100_email_collection.py`
