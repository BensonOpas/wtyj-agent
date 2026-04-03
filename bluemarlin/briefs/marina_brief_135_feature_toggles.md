# BRIEF 135 — Feature Toggles: Booking Flow + Terminology + Random Ref
**Status:** Draft | **Files:** `config/client.json`, `agents/social/social_agent.py`, `agents/marina/email_poller.py`, `agents/marina/marina_agent.py`, `agents/social/dm_agent.py` | **Depends on:** Brief 134 | **Blocks:** Tier 1 client onboarding

## Context

The system only works for charter companies. A restaurant (booking on, different words) or real estate agency (booking off, qualify and escalate) can't use it without code changes. Three things are needed to make it work for Tier 1 clients: a way to turn the booking flow off, a way to change what words the AI uses, and removing the charter-specific booking reference format.

## Why This Approach

Three focused changes. No new availability models (those come when Tier 2 clients need them). No generic booking summary (only needed when a non-charter has booking ON, which is Tier 2). Just the minimum to make a restaurant or real estate client work by changing config only.

## Source Material

### Booking flow entry point in social_agent.py (line 621):
```python
if not _skip_booking and any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
    if (fields.get("service_name") and fields.get("date")
            and fields.get("guests") and fields.get("service_key")
            and flags.get("booking_confirmed")
            and not flags.get("hold_created")):
```
This is the gate. If we add a config check before this, the entire booking state machine is skipped.

### Booking ref generation (social_agent.py line 631, email_poller.py line 1082):
```python
_ref_prefix = config_loader.get_booking_rules().get("booking_ref_prefix", "BM")
booking_ref = f"{_ref_prefix}-{time.strftime('%Y')}-{int(time.time()) % 100000:05d}"
```
Produces `BF-2026-12345`. Replace with random alphanumeric.

### Returning customer regex (social_agent.py line 287, email_poller.py line 299):
```python
_ref_match = re.search(rf'{re.escape(_ref_prefix)}-\d{{4}}-\d{{5}}', text)
```
Must be updated to match the new random format.

### Marina prompt field list (marina_agent.py line 228):
```
extract all fields you can find (experience, date, guests, service_key, slot_time, ...)
```
Uses hardcoded field names. Should read from terminology config.

### DM agent prompt (dm_agent.py):
Builds trip list with hardcoded labels. Should use terminology too.

### Current client.json has NO `features` or `terminology` section.

## Instructions

### Step 1: Add config sections to `config/client.json`

Add `features` section after `booking_rules`:
```json
"features": {
    "booking_flow": true
}
```

Add `terminology` section after `features`:
```json
"terminology": {
    "service_label": "trip",
    "party_size_label": "guests",
    "slot_label": "departure"
}
```

Only 3 keys for now — these are the ones used in the prompt. More can be added when needed (resource_label, location_label, confirmation_word) but unused keys are dead config.

Remove `booking_ref_prefix` from `booking_rules` (no longer needed — refs are random).

### Step 2: Booking flow toggle in `social_agent.py`

At line 621, wrap the booking confirmation block with a feature check:

```python
_booking_flow_on = config_loader.get_raw().get("features", {}).get("booking_flow", True)
```

Add this check BEFORE the existing `if not _skip_booking` line. When booking flow is OFF and the intent is booking:
- Do NOT enter the booking state machine
- Create an escalation with all collected fields as context
- Set `_skip_booking = True`
- Reply comes from Marina as-is (she already collected info via Claude)

Insert after the escalation handling (around line 530) and before the booking confirmation (line 620):

```python
# Step 7.8: Booking flow toggle — if OFF, escalate booking intents instead
if not _skip_booking and not _booking_flow_on:
    if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
        if fields.get("service_name") or fields.get("date") or fields.get("guests"):
            _cname = fields.get("customer_name", phone)
            _customer_email = fields.get("email", "")
            # Build chat log (same pattern as existing full escalation)
            _esc_msgs = state_registry.wa_get_full_history(phone, limit=20)
            _esc_chat_lines = []
            for _em in _esc_msgs:
                _esc_chat_lines.append(
                    f"[{_em['role'].upper()} | {_em.get('created_at', '')}]")
                _esc_chat_lines.append(_em.get("text", ""))
                _esc_chat_lines.append("---")
            _esc_chat_log = "\n".join(_esc_chat_lines) or "(no messages logged)"
            _esc_note = result.get("internal_note", "")
            _esc_subject = (
                f"[BOOKING REQUEST] {_cname} "
                f"(WhatsApp: {phone}) - {_esc_note or 'wants to book'}")
            _esc_body = (
                f"=== BOOKING REQUEST (booking_flow OFF) ===\n\n"
                f"=== CUSTOMER ===\n"
                f"WhatsApp: {phone}\n"
                f"Name: {_cname}\n"
                f"Email: {_customer_email or '(not provided)'}\n\n"
                f"=== COLLECTED FIELDS ===\n"
                f"{json.dumps(fields, indent=2, ensure_ascii=False)}\n\n"
                f"=== CHAT LOG ===\n{_esc_chat_log}\n\n"
                f"=== MARINA'S NOTE ===\n{_esc_note}"
            )
            state_registry.create_pending_notification(
                'escalation', 'whatsapp', phone, _cname,
                _esc_subject, _esc_body)
            bm_logger.log("booking_flow_off_escalated", phone=phone)
            _skip_booking = True
```

Note: this escalation is internal (sent to business owner, not customer). Uses the same chat log + structured body format as existing full escalations for consistency.

### Step 3: Booking flow toggle in `email_poller.py`

Same pattern. Find the booking confirmation entry point (around line 1061) and add the same feature check. When OFF, create an escalation email instead of entering the booking flow.

### Step 4: Random booking reference

Replace the ref generation in both files. Instead of:
```python
_ref_prefix = config_loader.get_booking_rules().get("booking_ref_prefix", "BM")
booking_ref = f"{_ref_prefix}-{time.strftime('%Y')}-{int(time.time()) % 100000:05d}"
```

Use:
```python
import random, string
_chars = string.ascii_uppercase + string.digits
booking_ref = ''.join(random.choices(_chars, k=6))  # e.g., "7K3X9M"
```

6 characters, truly alphanumeric (A-Z + 0-9), no prefix, no year. Short enough to read over the phone. 36^6 = ~2.2 billion combinations.

Add `import random, string` at top of both files (if not already present).

Update the returning customer regex to match the new format:
```python
_ref_match = re.search(r'\b[A-Z0-9]{6}\b', text)
```
This matches any standalone 6-char uppercase alphanumeric string. May have false positives with short words — the existing `state_registry.get_booking(ref)` check on the next line already confirms it's a real ref before acting on it. No change needed there.

### Step 5: Terminology in Marina's prompt (`marina_agent.py`)

In `_build_system_prompt()`, read terminology from config:
```python
terminology = config_loader.get_raw().get("terminology", {})
service_label = terminology.get("service_label", "service")
party_size_label = terminology.get("party_size_label", "guests")
slot_label = terminology.get("slot_label", "time slot")
```

Inject into the BOOKING BEHAVIOUR section (line 227):
```
When the customer wants to book, extract all fields you can find ({service_label} name,
date, {party_size_label}, service_key, {slot_label} time, customer_name, phone, email, special_requests).
```

Also update the asking instruction (line 232):
```
When no ACTION is given, reply naturally — ask for any missing required fields
({service_label} name, date, {party_size_label}) in a warm conversational way.
```

And in `process_message()` fallback dict (around line 487), update the fallback clarifications_needed to use the terminology:
```python
terminology = config_loader.get_raw().get("terminology", {})
_party_label = terminology.get("party_size_label", "guests")
...
"clarifications_needed": ["date", _party_label, "service_name"],
```
This is the Python fallback response when Claude API fails — not Claude's output.

### Step 6: Terminology in DM agent prompt (`dm_agent.py`)

In `_build_dm_system_prompt()`:

**6a.** Read terminology at the top of the function (after existing config reads):
```python
terminology = config_loader.get_raw().get("terminology", {})
service_label = terminology.get("service_label", "service")
party_size_label = terminology.get("party_size_label", "guests")
```

**6b.** Line 35: rename variable `trip_lines` → `service_lines` (cosmetic).

**6c.** Line 57: replace hardcoded "trips" in the intro:
```python
f"You are a Q&A helper. You answer questions about {service_label}s, pricing, availability, and general info."
```

**6d.** Line 59: replace hardcoded "TRIPS:" header:
```python
f"{service_label.upper()}S:"
```

**6e.** Line 72: replace hardcoded "trips" in listing instruction:
```python
f"- When listing {service_label}s, give names and brief descriptions. Only include prices if asked."
```

**6f.** Line 75: replace hardcoded "bookings" in redirect:
```python
f"You CANNOT process {service_label} bookings in DMs."
```

Leave the rest of the DM prompt unchanged — the redirect URLs and FAQ section are already config-driven.

## Tests

File: `tests/social/test_135_feature_toggles.py`

1. **test_booking_flow_off_escalates** — set `features.booking_flow` to False, mock marina returning a booking intent with fields, verify an escalation is created (not a booking) and `_skip_booking` prevents the booking state machine
2. **test_booking_flow_on_unchanged** — with `booking_flow: true` (default), verify booking flow works normally (regression)
3. **test_booking_ref_random_format** — generate a booking ref, verify it's 6 chars, uppercase alphanumeric (A-Z0-9), no dash, no prefix, no year
4. **test_booking_ref_detection** — put a valid random ref in a message, verify returning customer detection finds it AND confirms it exists in the database
5. **test_booking_ref_false_positive** — put a random 6-char hex that's NOT a booking ref in a message, verify it does NOT trigger returning customer (database check rejects it)
6. **test_terminology_in_prompt** — set terminology labels in config, build prompt, verify the labels appear in the prompt text
7. **test_terminology_defaults** — no terminology section in config, verify defaults ("service", "guests", "time slot") are used

## Success Condition

A client with `booking_flow: false` gets escalations instead of bookings. Terminology from config appears in Marina's prompt. Booking refs are random 6-char alphanumeric. All 7 tests pass.

## Rollback

Remove `features` and `terminology` sections from client.json. Revert the 3 code changes. Restore `booking_ref_prefix` to booking_rules.
