# BRIEF 161 — Race condition lock + ref regex + multi-language booking flow
**Status:** Draft | **Files:** webhook_server.py, social_agent.py, email_poller.py, marina_agent.py, test_070_whatsapp_booking.py, test_141_booking_ux.py, test_046_hybrid_state_machine.py | **Depends on:** Brief 160 | **Blocks:** —

## Context

Full E2E test run on 2026-04-08 found three distinct bugs in BlueMarlin that all affect real customers. One hits anyone who replies fast on WhatsApp. One hits anyone who shouts in all caps. One hits every non-English customer at the most important moment of a booking.

**Bug 1 — Race condition in concurrent WhatsApp messages** (`webhook_server.py:148`)
When a customer sends a second WhatsApp message while Marina is still processing the first, the second message reads stale empty state, runs Marina against empty context, generates a "who are you?" welcome, then saves empty state **overwriting** the rich state the first message just saved. Timeline from the live a1 test (cid `a1happyb69d5be9faaaaaaaa`):

```
02:34:10.572  msg 1 processing START
02:34:16.780  msg 2 processing START   ← overlap begins
02:34:17.404  msg 1 saves rich state (hold_id 133, awaiting_booking_confirmation, etc.)
02:34:20.911  msg 2 saves EMPTY state (it loaded empty at 16.780, overwrites msg 1)
```

Root cause: `_buffer_lock` in `webhook_server.py:52` only protects the message buffer dict, not the orchestrator call. Two `threading.Timer` callbacks for the same phone can run `handle_incoming_whatsapp_message` concurrently. The orchestrator reads state at the start, calls Marina, saves state at the end — if two instances overlap, the second one wipes the first.

Trigger condition: `msg_1_processing_time > debounce_window + inter_message_gap`. With `_DEBOUNCE_SECONDS = 2.0` and customers typically replying 4-6s later, msg 2 processing starts at 6-8s. Marina + availability check + hold creation takes 6-10s. Overlap is common.

**Bug 2 — ALL CAPS booking reference false positive** (`social_agent.py:289`)
The booking-ref detection regex `\b[A-Z0-9]{6}\b` matches any 6-character alphanumeric in uppercase. When a customer shouts "I WANT TO BOOK A SUNSET CRUISE RIGHT NOW FOR 4 PEOPLE FRIDAY!!!!", "SUNSET" matches. Marina sees `unknown_ref: "SUNSET"` in flags and writes "I couldn't find a booking under reference SUNSET, could you double-check?" while simultaneously extracting fields and placing a hold. The orchestrator state is correct; the customer-facing reply is wrong.

Note on `email_poller.py:300`: The email poller also has the same loose regex, but the caller at `_detect_booking_ref` only surfaces `unknown_ref` when `state_registry.get_booking(candidate)` actually returns None after being called — so the false-positive user-visible bug does not reproduce on the email path (the candidate is tried against the DB first). We still tighten the email regex as a defensive fix to prevent future divergence and to keep the two code paths symmetric.

**Bug 3 — Hardcoded English booking reply templates** (`social_agent.py:61-87`, `email_poller.py:389-415`, plus `_post_validate` rejection branches)
`_build_booking_summary` is a hardcoded English f-string template (`"Just to confirm: {svc_name} on {date_fmt}, {slot_time}..."`). It's called by `_post_validate` at `social_agent.py:170` and `email_poller.py:501` and its return value REPLACES Marina's Claude-generated reply at `social_agent.py:433` (`reply_text = _pv_override`). When a Dutch customer asks for a sunset cruise, Marina's Claude reply is fluent Dutch, but Python then overrides it with the English template. Same for Papiamentu, Spanish, German, Portuguese.

`_post_validate` has the same problem for three rejection branches:
- **Past date** (`social_agent.py:146-149`): returns `"That date ({date}) has already passed. Would you like to pick a different date?"` — English only
- **Wrong day of week** (`social_agent.py:132-137`): returns `"The {svc} doesn't run on {day_name}s, only {days_avail}. Would any of these work instead?"` — English only
- **Multi-departure prompt** (`social_agent.py:159-163`): returns `"The {svc} has a couple of departure times: ... Which one works for you?"` — English only

This is a **CLAUDE.md Rule 3 violation** ("No static reply templates"). It was flagged in the Brief 160 output as out-of-scope for that brief. Brief 161 fixes it.

The demo story "we handle six languages end-to-end" is false while these templates exist: non-English customers see English at the most critical step (booking confirmation).

## Why This Approach

**Bug 1 — per-phone lock (not increased debounce)**
Two options: (a) raise `_DEBOUNCE_SECONDS` from 2 to 8, swallowing the race in the debounce window; (b) add per-phone `threading.Lock` around the orchestrator call.

Rejected (a) because it forces every first reply to wait 8 seconds, which feels unresponsive in a live demo. The debounce is there to coalesce "Hi\nI want to book", not to serialize state writes.

Chosen (b): per-phone lock registry keyed by `conversation_id` (or phone for legacy Meta path). Registry grows monotonically but each lock is a few bytes; in realistic usage this is negligible. No cleanup needed for now — can add stale-lock gc later if memory ever matters.

**Bug 2 — require at least one digit in the regex (not prefix-anchored)**
Rejected the prefix-anchored approach `\b{prefix}\d{{3,8}}\b` because neither BlueMarlin nor Adamus currently sets `terminology.booking_ref_prefix` in client.json — their refs are random alphanumeric (`BF9999` is legacy). Prefix-anchored would require a config migration for every client.

Chosen: `\b(?=[A-Z0-9]*\d)[A-Z0-9]{6}\b` — still matches `BF9999` and any 6-char ref with at least one digit, but rejects pure-letter words like `SUNSET`, `CRUISE`, `FRIDAY`. Works for all current and future clients without config change.

**Bug 3 — Marina does validation + summary generation herself in her single Claude call (not a 2nd call, not translated Python templates)**
Three options considered:

- (i) Keep Python templates and translate them per-language inside Python. Violates Rule 5 (no Python language classifiers) and requires maintaining 6 translations of every string.
- (ii) Do the Python checks first, then call Marina a second time with the outcome. Violates Rule 1 (one Claude call per message).
- (iii) Move validation LOGIC + reply generation into Marina's prompt. She has today's date, service data, all fields. She can check past date, wrong day, multi-departure, and generate the summary herself in the customer's language in one Claude call. Risk: she hallucinates prices. Mitigation: prompt says "use EXACT values from SERVICE DATA". Test with all 6 languages.

Chosen (iii). Python still runs `_post_validate` as a pure state manager — it decides whether to set `awaiting_booking_confirmation` — but it no longer generates any reply text. Marina's Claude-generated reply is always kept as-is.

The safety question: "what if Marina forgets to check past date?" Answer: Python `_post_validate` still refuses to set `awaiting_booking_confirmation` when the date has passed (or the day is wrong, etc.). So even if Marina's reply is technically wrong (asks for confirmation on a past date), the state machine won't advance. The customer will see a confusing reply but won't get a hold on a past date. Worst case = wording bug, not state corruption.

Tradeoff: we accept a tiny risk of Marina writing incorrect replies in edge cases in exchange for native multi-language support. We mitigate with explicit prompt instructions + E2E tests in all 6 languages.

## Source Material

### Current `_build_booking_summary` (social_agent.py:61-87)

```python
def _build_booking_summary(fields, service):
    """Build a data-driven booking summary. WhatsApp adaptation: shorter intro than email."""
    svc_name = service.get("display_name", fields.get("service_key", ""))
    date_str = fields.get("date", "")
    guests = int(fields.get("guests") or 1)
    slot_time = fields.get("slot_time", "")
    slots = service.get("slots", [])
    slot_info = next((d for d in slots if d.get("time") == slot_time), None)
    if not slot_info and slots:
        slot_info = slots[0]
        slot_time = slot_info.get("time", "")
    resource = slot_info.get("resource", "") if slot_info else ""
    location = slot_info.get("location", "") if slot_info else ""
    price_base = service.get("price", 0)
    total = price_base * guests
    included = ", ".join(service.get("included", [])) or "see details"
    try:
        date_fmt = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A, %d %B %Y")
    except ValueError:
        date_fmt = date_str
    return (
        f"Just to confirm: {svc_name} on {date_fmt}, "
        f"{slot_time} from {location} on {resource}. "
        f"{guests} guests, ${total} total (${price_base} each). "
        f"Includes {included}.\n\n"
        f"Want me to check availability and hold a spot for you?"
    )
```

### Current `_post_validate` (social_agent.py:112-171)

```python
def _post_validate(fields, flags, result, service):
    """
    Validate extracted fields after Claude call.
    Returns (reply_override, should_set_awaiting).
    """
    if not any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
        return None, False
    if not all(fields.get(k) for k in ("service_name", "date", "guests", "service_key")):
        return None, False
    if flags.get("awaiting_booking_confirmation") or flags.get("booking_confirmed"):
        return None, False

    date = fields["date"]
    slots = service.get("slots", [])

    # 1. Day-of-week check
    try:
        day_name = datetime.strptime(date, "%Y-%m-%d").strftime("%A")
        days_avail = service.get("days_available", "daily")
        if not _day_matches(day_name, days_avail):
            return (
                f"The {service.get('display_name', fields['service_key'])} "
                f"doesn't run on {day_name}s, only {days_avail}. "
                f"Would any of these work instead?\n\n"
                f"{_suggest_dates(date, days_avail)}"
            ), False
    except ValueError:
        pass

    # 1b. Past date check
    try:
        _pv_date_obj = datetime.strptime(date, "%Y-%m-%d").date()
        _pv_today = datetime.now(timezone(timedelta(hours=-4))).date()
        if _pv_date_obj < _pv_today:
            return (
                f"That date ({date}) has already passed. "
                f"Would you like to pick a different date?"
            ), False
    except ValueError:
        pass

    # 2. Departure time check (multi-departure trips only)
    if len(slots) > 1 and not fields.get("slot_time"):
        dep_lines = "\n".join(
            f"- {d['time']} aboard {d.get('resource', '?')} from {d.get('location', '?')}"
            for d in slots
        )
        return (
            f"The {service.get('display_name', fields['service_key'])} has "
            f"a couple of departure times:\n\n{dep_lines}\n\n"
            f"Which one works for you?"
        ), False

    # 3. Child pricing — Claude sets needs_child_ages flag
    if result.get("flags", {}).get("needs_child_ages"):
        return None, False

    # 4. All checks pass — build data-driven summary
    summary = _build_booking_summary(fields, service)
    return summary, True
```

### Current caller in social_agent.py (step 6)

```python
    reply_text = reply

    # Step 6: Post-validation (booking intents only)
    _pv_service_key = fields.get("service_key", "")
    _pv_service = config_loader.get_service(_pv_service_key) if _pv_service_key else {}
    _run_pv = any(i in _BOOKING_INTENTS for i in result.get("intents", []))
    # Guard: if customer was responding to a booking summary and didn't change
    # any booking fields, skip post-validate to prevent decline loop
    if _run_pv and _was_awaiting and not flags.get("booking_confirmed"):
        _new_f = result.get("fields", {}) or {}
        if not any(_new_f.get(k) for k in ("service_name", "date", "guests", "service_key", "slot_time")):
            _run_pv = False
    if _run_pv:
        _pv_override, _pv_set_awaiting = _post_validate(fields, flags, result, _pv_service)
        if _pv_override:
            _intents = result.get("intents", [])
            _has_side_topics = any(i not in _BOOKING_INTENTS for i in _intents)
            if _has_side_topics:
                reply_text = result["reply"].rstrip() + "\n\n" + _pv_override
            else:
                reply_text = _pv_override
            if _pv_set_awaiting:
                flags["awaiting_booking_confirmation"] = True
```

### Current `_flush_buffer` orchestrator call (webhook_server.py:148-222)
See `webhook_server.py`. The key line is 175 (`reply_text = handle_incoming_whatsapp_message(final_msg)`) — this is what must be serialized per-phone.

### Current BOOKING BEHAVIOUR prompt block (marina_agent.py:324-340)

```
BOOKING BEHAVIOUR:
When the customer wants to book, extract all fields you can find ({service_label} name,
date, {party_size_label}, service_key, {slot_label} time, customer_name, phone, email, special_requests).
Python handles all booking validation, state management, and summary generation.
If you receive an ACTION instruction below, follow it exactly.
When no ACTION is given, reply naturally — ask for any missing required fields
({service_label} name, date, {party_size_label}) in a warm conversational way.

BOOKING PACING:
When a customer first mentions they want to book and you don't have all the required fields yet, briefly mention what the service includes and any key details (schedule, what's included, duration) from the service data before asking for the missing fields. Keep it to one or two sentences — enough to be helpful, not a sales pitch. Then naturally ask for what you still need.
```

The sentence `"Python handles all booking validation, state management, and summary generation."` is exactly the lie this brief deletes.

### BlueMarlin service data (sample, for prompt reference)
```json
"sunset_cruise": {
  "display_name": "Sunset Cruise",
  "price": 79,
  "days_available": "Tuesday, Thursday, Friday, Saturday",
  "slots": [{"time": "17:30", "resource": "Kailani", "location": "Village Marina/Mood pier"}],
  "included": ["open bar (beer, wine, cocktails)", "snacks"],
  "duration_hours": 2.5
}
```

### BlueMarlin languages
```json
"languages": ["English", "Dutch", "German", "Spanish", "Portuguese", "Papiamentu"]
```

### Adamus languages
```json
"languages": ["English", "Dutch", "Spanish", "Papiamentu"]
```

## Instructions

### Fix 1 — Per-phone lock (webhook_server.py)

**1.1** After line 52 (`_buffer_lock = threading.Lock()`), add a new lock registry:

```python
# Brief 161: per-phone lock serializes concurrent handle_incoming_whatsapp_message
# calls for the same phone/conversation. Fixes race where msg 2 reads stale state
# before msg 1 has persisted its orchestrator output. Keyed by conversation_id
# (Zernio) or phone (legacy Meta). Registry grows monotonically; locks are cheap.
_phone_locks = {}  # key -> threading.Lock
_phone_locks_registry_lock = threading.Lock()


def _get_phone_lock(key: str) -> threading.Lock:
    """Get or create a per-phone lock for serializing orchestrator calls."""
    with _phone_locks_registry_lock:
        lock = _phone_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _phone_locks[key] = lock
        return lock
```

**1.2** The orchestrator is called from THREE places in `webhook_server.py` — all three must be wrapped by the per-phone lock to fully close the race:
- Line 175: `_flush_buffer` → `handle_incoming_whatsapp_message` (WhatsApp via Zernio, debounced)
- Line 214: `_flush_buffer` → `handle_incoming_whatsapp_message` (legacy Meta WhatsApp, debounced)
- Line 307: `_process_zernio_event` → `handle_incoming_whatsapp_message` (IG/FB DM with `booking_flow=True`, NOT debounced — direct call)
- Line 326: `_process_zernio_event` → `handle_incoming_dm` (IG/FB DM with `booking_flow=False`, NOT debounced)

In `_flush_buffer`: wrap the entire `try:` block (currently lines 165-222) with a per-phone lock. The lock key is `final_msg.get("_zernio_conversation_id") or phone`:

```python
    # Brief 161: acquire per-phone lock BEFORE the try block so both Zernio
    # and legacy Meta paths are serialized. Lock key: zernio conv id (if
    # present) or phone.
    _lock_key = final_msg.get("_zernio_conversation_id") or phone
    _phone_lock = _get_phone_lock(_lock_key)
    with _phone_lock:
        try:
            # Check if this came from Zernio (has _zernio metadata)
            _zernio_conv = final_msg.get("_zernio_conversation_id")
            ...
```

Indent the entire existing try/except body by 4 spaces. Keep the `except` block inside the `with`.

In `_process_zernio_event`: wrap the orchestrator-call block starting at the `if _booking_flow_on:` branch (currently around line 295) up to and including the `send_dm_reply` call and the `dm_store_message` assistant write. The lock key is `conversation_id` (already available in scope).

```python
        # Brief 161: per-phone lock serializes the IG/FB DM path the same way
        # the WhatsApp debounce path is serialized — required so concurrent
        # Zernio webhooks for the same conversation cannot race.
        _dm_lock = _get_phone_lock(conversation_id)
        with _dm_lock:
            # Route based on booking_flow toggle
            _booking_flow_on = config_loader.get_raw().get("features", {}).get("booking_flow", True)
            if _booking_flow_on:
                ...
            else:
                ...
            if reply_text:
                send_dm_reply(conversation_id, account_id, reply_text)
                state_registry.dm_store_message(...)
```

Indent the existing branch body by 4 spaces inside the `with`. Do NOT wrap `send_typing_indicator` (it's cheap and outside the critical section).

**1.3** Add a comment above `_DEBOUNCE_SECONDS` noting that debounce coalesces rapid messages into a single Claude call, and the per-phone lock (added below) is what prevents concurrent orchestrator access for the same conversation. They solve different problems.

### Fix 2 — Booking ref regex (social_agent.py + email_poller.py)

**2.1** In `wtyj/agents/social/social_agent.py` line 289, replace:
```python
_ref_match = re.search(r'\b[A-Z0-9]{6}\b', text)
```

with:
```python
# Brief 161: require at least one digit so all-caps service words like
# "SUNSET" or "FRIDAY" don't get misread as booking references.
_ref_match = re.search(r'\b(?=[A-Z0-9]*\d)[A-Z0-9]{6}\b', text)
```

**2.2** In `wtyj/agents/marina/email_poller.py` line 300, make the same substitution. Preserve the rest of the branch logic unchanged.

### Fix 3 — Multi-language booking flow

#### 3a. Update `marina_agent._build_system_prompt` BOOKING BEHAVIOUR block

In `wtyj/agents/marina/marina_agent.py`, `_build_system_prompt` returns an f-string (look for the `return f"""...""" ` at the end of the function). The BOOKING BEHAVIOUR + BOOKING PACING sections to replace are currently inside that f-string around lines 324-340.

**Replace the exact block from `BOOKING BEHAVIOUR:` down to the line ending `...then move into the booking.` with the EXACTLY-escaped text below.**

⚠️ **F-STRING BRACE RULES**: Because this block is inside an `f"""..."""` literal, every literal `{` that is NOT a Python placeholder MUST be written as `{{` and every literal `}` as `}}`. The only SINGLE-brace placeholders are the ones Python should interpolate at prompt-build time: `{service_label}` and `{party_size_label}`. Every other example placeholder (`{{service}}`, `{{days_available}}`, `{{nearby_valid_date_1}}`, `{{time1}}`, etc.) must use double braces so Python passes them through literally to Marina.

Paste the block below VERBATIM — it is already escaped correctly:

```
BOOKING BEHAVIOUR:
When the customer wants to book, extract all fields you can find ({service_label} name,
date, {party_size_label}, service_key, {slot_label} time, customer_name, phone, email, special_requests).

BOOKING VALIDATION — YOU must do these checks before writing your reply. Reply in the customer's language (see LANGUAGE RULE above).

1. PAST DATE: If the extracted date is earlier than TODAY (shown in the user prompt), the date has passed. Do NOT write a confirmation summary. Politely say the date has passed and ask for a new one. Example wording (translate to the customer's language): "That date has already passed. Which date would you like instead?"

2. WRONG DAY OF WEEK: Compare the extracted date's day of week against the service's days_available field (in CLIENT DATA SERVICES). If the service does NOT run on that day, do NOT write a confirmation summary. Tell the customer which days the service runs and suggest 2-3 nearby valid dates. Example wording: "The {{service}} only runs on {{days_available}}. Would {{nearby_valid_date_1}}, {{nearby_valid_date_2}}, or {{nearby_valid_date_3}} work instead?"

3. MULTI-DEPARTURE: If the service has more than one entry in its slots list AND the customer has not specified a slot_time, do NOT write a confirmation summary. List the available departures (time, resource, location) and ask which one the customer prefers. Example wording: "The {{service}} has a few departure options: {{time1}} aboard {{resource1}} from {{location1}}, {{time2}} aboard {{resource2}} from {{location2}}. Which one works for you?"

4. ALL CHECKS PASS (date is today or later, day matches service days, single departure or slot_time chosen, all required fields present): Write a confirmation summary containing:
   - Service display name
   - Day of week + date (formatted naturally for the customer's language)
   - Departure or time + location + resource (if present in SERVICE DATA)
   - Number of {party_size_label}
   - Total price — BUT ONLY IF the service's price is greater than zero. If the service's price is 0 (e.g. restaurant reservations that don't charge per person up front, or free events), OMIT the price line entirely. Never print "$0 total" — it looks broken.
   - What is included (from the service's "included" list, if present)
   End with a clear call-to-action asking if they'd like you to check availability and hold a spot for them. Translate the call-to-action into the customer's language.

CRITICAL PRICE ACCURACY: When the service price is greater than zero, compute total = {party_size_label} count × service base price using the EXACT numbers in SERVICE DATA. Never invent or round prices. If you are uncertain about a value, ask for clarification instead of guessing. When the service price is zero, write the summary WITHOUT a price line at all — do not say "free" either; just omit the price.

CRITICAL LANGUAGE: Write EVERY booking flow reply — rejection, multi-departure question, summary — in the customer's detected language. See LANGUAGE RULE above. Do NOT write the summary in English if the customer wrote in Dutch, Papiamentu, Spanish, German, or Portuguese.

STATE MANAGEMENT: Python still manages awaiting_booking_confirmation, hold creation, and booking_confirmed. Do not set these flags yourself unless an ACTION instruction in the user prompt explicitly tells you to.

If you receive an ACTION instruction below, follow it exactly — it overrides the validation checks above.

When the customer asks non-booking questions alongside a booking request (e.g. "book X for 2 on March 28, also is there food?"), answer those questions in your reply before doing the validation checks.

BOOKING PACING:
When a customer first mentions they want to book and you don't have all the required fields yet, briefly mention what the service includes and any key details (schedule, what's included, duration) from the service data before asking for the missing fields. Keep it to one or two sentences — enough to be helpful, not a sales pitch. Then naturally ask for what you still need.
Example flow: Customer says 'I want to book the sunset cruise' → you say something like 'The sunset cruise is a 2.5-hour trip with drinks and snacks, runs Tue/Thu/Fri/Sat. How many people and what date works for you?'
Do NOT list everything about the service. Just the highlights, then move into the booking.
```

**Verify immediately after the edit (before running any tests)** — these two commands are the only safety net for f-string escape bugs:

```bash
# 1. Compile check — catches any unbalanced brace
python3 -c "import ast; ast.parse(open('wtyj/agents/marina/marina_agent.py').read())"

# 2. Prompt build check — catches KeyError on bad single-brace placeholders
CLIENT_CONFIG_PATH=clients/bluemarlin/config/client.json \
  python3 -c "import sys, os; sys.path.insert(0, 'wtyj'); os.environ.setdefault('ANTHROPIC_API_KEY', 'test'); from agents.marina import marina_agent; p = marina_agent._build_system_prompt({}, channel='whatsapp'); assert 'BOOKING VALIDATION' in p and 'PAST DATE' in p and '{service}' in p and '{days_available}' in p; print('OK: prompt builds, instructional braces preserved')"
```

If either command fails, the escape is wrong — fix before proceeding.

#### 3b. Simplify `social_agent._post_validate`

In `wtyj/agents/social/social_agent.py`, replace the body of `_post_validate` (lines 112-171) with:

```python
def _post_validate(fields, flags, result, service):
    """
    Decide whether to advance booking state to awaiting_booking_confirmation.

    Brief 161: returns (None, should_set_awaiting). Always returns None for
    reply_override — Marina generates all booking-flow replies in the
    customer's language via her prompt (see BOOKING VALIDATION block in
    _build_system_prompt). This function is now a pure state manager.
    """
    if not any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
        return None, False
    if not all(fields.get(k) for k in ("service_name", "date", "guests", "service_key")):
        return None, False
    if flags.get("awaiting_booking_confirmation") or flags.get("booking_confirmed"):
        return None, False

    date = fields["date"]
    slots = service.get("slots", [])

    # Day-of-week: do not advance state on wrong day (Marina's reply will
    # have told the customer which days the service runs).
    try:
        day_name = datetime.strptime(date, "%Y-%m-%d").strftime("%A")
        days_avail = service.get("days_available", "daily")
        if not _day_matches(day_name, days_avail):
            return None, False
    except ValueError:
        pass

    # Past date: do not advance state on past date.
    try:
        _pv_date_obj = datetime.strptime(date, "%Y-%m-%d").date()
        _pv_today = datetime.now(timezone(timedelta(hours=-4))).date()
        if _pv_date_obj < _pv_today:
            return None, False
    except ValueError:
        pass

    # Multi-departure: do not advance state until the customer has chosen a slot.
    if len(slots) > 1 and not fields.get("slot_time"):
        return None, False

    # Child pricing: Marina is still gathering ages.
    if result.get("flags", {}).get("needs_child_ages"):
        return None, False

    # All checks pass — advance state. Marina has already written the summary
    # in the customer's language.
    return None, True
```

#### 3c. Delete `_build_booking_summary` (social_agent.py:61-87)

Delete the function entirely. Also delete `_suggest_dates` (lines 48-58) — it was only used by the now-removed day-of-week override. Keep `_day_matches` (still used by `_post_validate`).

#### 3d. Update the caller in social_agent.py (step 6)

Replace the block at the current lines 413-436 with:

```python
    reply_text = reply

    # Step 6: Post-validation (booking intents only). Brief 161: _post_validate
    # no longer returns reply text — Marina writes all booking-flow replies
    # in the customer's language. This step only decides whether to advance
    # state to awaiting_booking_confirmation.
    _pv_service_key = fields.get("service_key", "")
    _pv_service = config_loader.get_service(_pv_service_key) if _pv_service_key else {}
    _run_pv = any(i in _BOOKING_INTENTS for i in result.get("intents", []))
    # Guard: if customer was responding to a booking summary and didn't change
    # any booking fields, skip post-validate to prevent decline loop
    if _run_pv and _was_awaiting and not flags.get("booking_confirmed"):
        _new_f = result.get("fields", {}) or {}
        if not any(_new_f.get(k) for k in ("service_name", "date", "guests", "service_key", "slot_time")):
            _run_pv = False
    if _run_pv:
        _pv_override, _pv_set_awaiting = _post_validate(fields, flags, result, _pv_service)
        if _pv_set_awaiting:
            flags["awaiting_booking_confirmation"] = True
```

Note: `_pv_override` is kept as a variable name (always None) for minimum-diff, but no longer used. Remove any downstream references to it (there shouldn't be any outside step 6 — grep to confirm).

**NOTE on `_post_validate` signature divergence**: The social_agent version takes positional args `(fields, flags, result, service)` while the email_poller version takes `(th, result, service)` where `th` is a thread dict containing fields and flags as nested keys. **Keep both signatures unchanged** — unifying them would require updating every test in test_046, test_047, test_048, test_064, test_marina_tone. Brief 161 does NOT unify them; it only changes the return contract to `(None, bool)` in both.

#### 3e. Apply the same simplification to email_poller.py

In `wtyj/agents/marina/email_poller.py`:

- Delete `_build_booking_summary` (lines 389-415)
- Delete `_suggest_dates` (if only used by the removed override)
- Replace `_post_validate` body (lines 440-502) with the same pattern as 3b, adapted to use `th` (thread dict) instead of `(fields, flags)`:

```python
def _post_validate(th, result, service):
    """
    Decide whether to advance booking state to awaiting_booking_confirmation.

    Brief 161: returns (None, should_set_awaiting). Always returns None for
    reply_override — Marina generates all booking-flow replies in the
    customer's language via her prompt.
    """
    fields = th.get("fields", {})
    flags = th.get("flags", {})

    if not any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
        return None, False
    if not all(fields.get(k) for k in ("service_name", "date", "guests", "service_key")):
        return None, False
    if flags.get("awaiting_booking_confirmation") or flags.get("booking_confirmed"):
        return None, False

    date = fields["date"]
    slots = service.get("slots", [])

    try:
        day_name = datetime.strptime(date, "%Y-%m-%d").strftime("%A")
        days_avail = service.get("days_available", "daily")
        if not _day_matches(day_name, days_avail):
            return None, False
    except ValueError:
        pass

    try:
        _pv_date_obj = datetime.strptime(date, "%Y-%m-%d").date()
        _pv_today = datetime.now(timezone(timedelta(hours=-4))).date()
        if _pv_date_obj < _pv_today:
            return None, False
    except ValueError:
        pass

    if len(slots) > 1 and not fields.get("slot_time"):
        return None, False

    if result.get("flags", {}).get("needs_child_ages"):
        return None, False

    return None, True
```

Update the caller at `email_poller.py:874`:
```python
                    _pv_override, _pv_set_awaiting = _post_validate(th, result, _pv_service)
                    if _pv_set_awaiting:
                        th["flags"]["awaiting_booking_confirmation"] = True
                    # Brief 161: no reply override — Marina's reply text stands as-is.
```

Delete any code that referenced `_pv_override` to replace reply text (the `if _pv_override:` branch in the caller).

### Test updates

#### 3f. Update `wtyj/tests/social/test_070_whatsapp_booking.py`

- Delete `test_build_booking_summary_west_coast` and `test_build_booking_summary_single_departure_auto` (function removed)
- Delete `test_suggest_dates_*` if `_suggest_dates` is removed — check for any remaining usage before deletion
- Rewrite the `_post_validate` tests to match the new contract. The new assertions:

```python
def test_post_validate_day_of_week_does_not_advance():
    """Brief 161: wrong day returns (None, False) — Marina handles the rejection reply."""
    service = config_loader.get_service("west_coast_beach")
    fields = {"service_name": "West Coast Beach Trip", "date": _NEXT_MON,
              "guests": "2", "service_key": "west_coast_beach"}  # Monday — Wed/Sun only
    result = {"intents": ["booking"], "flags": {}}
    override, should_set = _post_validate(fields, {}, result, service)
    assert override is None
    assert should_set is False


def test_post_validate_past_date_does_not_advance():
    """Brief 161: past date returns (None, False)."""
    service = config_loader.get_service("klein_curacao")
    fields = {"service_name": "Klein Curacao", "date": "2025-01-15",
              "guests": "2", "service_key": "klein_curacao"}
    result = {"intents": ["booking"], "flags": {}}
    override, should_set = _post_validate(fields, {}, result, service)
    assert override is None
    assert should_set is False


def test_post_validate_multi_departure_does_not_advance():
    """Brief 161: multi-departure without slot_time returns (None, False)."""
    service = config_loader.get_service("klein_curacao")
    fields = {"service_name": "Klein Curacao", "date": _FUTURE_DATE,
              "guests": "2", "service_key": "klein_curacao"}
    result = {"intents": ["booking"], "flags": {}}
    override, should_set = _post_validate(fields, {}, result, service)
    assert override is None
    assert should_set is False


def test_post_validate_all_pass_advances_state():
    """Brief 161: all valid returns (None, True) — no reply override, just state."""
    service = config_loader.get_service("west_coast_beach")
    fields = {"service_name": "West Coast Beach Trip", "date": _NEXT_WED,
              "guests": "2", "service_key": "west_coast_beach",
              "slot_time": "09:00"}
    result = {"intents": ["booking"], "flags": {}}
    override, should_set = _post_validate(fields, {}, result, service)
    assert override is None
    assert should_set is True


def test_post_validate_skips_non_booking_intent():
    """Non-booking intent returns (None, False) unchanged."""
    service = config_loader.get_service("klein_curacao")
    fields = {"service_name": "Klein Curacao", "date": _FUTURE_DATE,
              "guests": "2", "service_key": "klein_curacao"}
    result = {"intents": ["inquiry"], "flags": {}}
    override, should_set = _post_validate(fields, {}, result, service)
    assert override is None
    assert should_set is False
```

- Update `test_orchestrator_post_validate_day_override` — rename to `test_orchestrator_wrong_day_keeps_marinas_reply` and change the assertion. The mock now returns Marina's own wrong-day rejection reply (e.g. `"The West Coast Beach only runs Wed/Sun — how about Sunday?"`), and the test asserts that reply is preserved AND `awaiting_booking_confirmation` is NOT set:

```python
@patch("agents.social.social_agent.marina_agent.process_message")
def test_orchestrator_wrong_day_keeps_marinas_reply(mock_process):
    """Brief 161: Marina's own wrong-day reply is preserved; state does not advance."""
    phone = "TEST_070_DAY_001"
    _cleanup_phone(phone)
    mock_process.return_value = {
        "intents": ["booking"],
        "fields": {"service_key": "west_coast_beach", "service_name": "West Coast Beach",
                    "date": _NEXT_MON, "guests": "2"},
        "confidence": "high",
        "reply": "The West Coast Beach Trip only runs Wednesdays and Sundays. Would Wednesday work?",
        "clarifications_needed": [], "requires_human": False,
        "flags": {}, "internal_note": ""
    }
    msg = {"from": phone, "text": "Book West Coast Beach Monday for 2", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert "Wednesday" in reply  # Marina's reply preserved
    state = state_registry.wa_get_booking_state(phone)
    assert not state["flags"].get("awaiting_booking_confirmation")
    _cleanup_phone(phone)
```

- Update `test_orchestrator_booking_summary_sent` — rename to `test_orchestrator_all_valid_advances_state_keeps_marinas_summary`:

```python
@patch("agents.social.social_agent.state_registry.create_soft_hold")
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_orchestrator_all_valid_advances_state_keeps_marinas_summary(mock_process, mock_cal, mock_pay, mock_sheets, mock_hold):
    """Brief 161: valid booking — Marina's own summary kept, awaiting flag set, hold placed.
    NOTE: patch agents.social.social_agent.state_registry (local import), not shared.state_registry,
    because social_agent.py imports state_registry at the top."""
    phone = "TEST_070_SUMMARY_001"
    _cleanup_phone(phone)
    mock_process.return_value = {
        "intents": ["booking"],
        "fields": {"service_key": "west_coast_beach", "service_name": "West Coast Beach",
                    "date": _NEXT_WED, "guests": "2",
                    "customer_name": "John"},
        "confidence": "high",
        "reply": "Just to confirm: West Coast Beach Trip on Wednesday, 2 guests, $240 total. Want me to check availability and hold a spot?",
        "clarifications_needed": [], "requires_human": False,
        "flags": {}, "internal_note": ""
    }
    mock_cal.check_availability.return_value = {"available": True, "spots_remaining": 23, "capacity": 25}
    mock_hold.return_value = 888
    msg = {"from": phone, "text": "West Coast Beach for 2", "from_name": "John"}
    reply = handle_incoming_whatsapp_message(msg)
    # Marina's own summary is preserved exactly
    assert "$240" in reply
    assert "check availability" in reply.lower()
    state = state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("awaiting_booking_confirmation") is True
    assert state["flags"].get("slot_checked") is True
    _cleanup_phone(phone)
```

#### 3g. Update `wtyj/tests/social/test_141_booking_ux.py`

- Delete `test_booking_summary_says_check_availability` (function removed)
- Keep `test_action_context_mentions_availability` — still valid
- Keep the DM agent tests (3 and 4) — unrelated

#### 3h. Update `wtyj/tests/marina/test_046_hybrid_state_machine.py`

- Delete `test_multi_departure_asks_for_time`, `test_single_departure_builds_summary`, `test_invalid_day_returns_error` — these assert string contents of overrides
- Update `test_multi_departure_no_awaiting`, `test_single_departure_sets_awaiting`, `test_invalid_day_no_awaiting` to match new contract: `override is None`
- Delete the four `test_summary_contains_*` tests — `_build_booking_summary` is gone
- Remove `_build_booking_summary` and `_suggest_dates` from the imports at the top if they're deleted
- Keep `_day_matches` tests (function still exists)
- If `_suggest_dates` is removed entirely, delete `test_suggest_dates_returns_friday`

#### 3h-bis. Update FOUR more marina test files (found by brief-reviewer, 2026-04-08)

These files all import `_build_booking_summary` or assert `_post_validate` returns a non-None string override and MUST be updated or tests deleted. Failure to update them makes the full test suite red after the core changes.

**`wtyj/tests/marina/test_marina_tone.py`**:
- Delete the import line `from agents.marina.email_poller import _build_booking_summary` (line 8).
- Delete the four tests that call `_build_booking_summary`: `test_booking_summary_no_old_header`, `test_booking_summary_no_old_lock_phrase`, `test_booking_summary_has_price`, `test_booking_summary_new_closer`.
- Delete `test_post_validate_day_of_week_no_em_dashes` (which asserts `override is not None`) — wrong-day override is no longer a string.
- Remove these test names from any `__main__` block list at the bottom of the file if present.

**`wtyj/tests/marina/test_048_human_speech_optimization.py`**:
- Delete the import of `_build_booking_summary` (leave `_post_validate` and `_BOOKING_INTENTS`).
- Delete the three `test_summary_*` / `test_booking_summary_*` tests that assert on summary content: `test_booking_summary_no_signature`, `test_summary_lock_in_question`, `test_summary_correct_price`.
- Delete `test_day_of_week_override_no_signature` and `test_departure_override_no_signature` — both assert `override` is a non-None string.
- Update `test_booking_still_builds_summary` — rename to `test_booking_flow_still_advances_state` and change assertion to `override is None and awaiting is True`.
- Leave `test_reschedule_still_triggers` as-is if it doesn't assert on override content (check it first — if it does, update to match new contract).

**`wtyj/tests/marina/test_047_reschedule_booking_flow.py`**:
- Keep the import of `_post_validate` (still exists, new signature compatible).
- Update tests T4-T10 that assert on override content (e.g. `"Want me to go ahead and book this" in override`, `"$220" in override`, `"3-in-1 Snorkeling Trip" in override`, `"next Tuesday" in override`). For each:
  - If the test was checking "happy path builds summary" → change to assert `override is None` and `awaiting is True`.
  - If the test was checking "wrong day produces rejection" → change to assert `override is None` and `awaiting is False`.
  - If the test was checking "past date produces rejection" → same as wrong day.
- Leave T1-T3 (thread setup, intent routing) as-is if they don't touch override content.

**`wtyj/tests/marina/test_064_hardening.py`**:
- Keep the import of `_post_validate`, `_day_matches`, `_SYSTEM_EMAIL_PREFIXES`.
- Update `test_past_date_returns_already_passed` — rename to `test_past_date_does_not_advance_state`. Change assertion from `reply is not None and "already passed" in reply` to `reply is None and awaiting is False`.
- If there's a similar `test_day_of_week_rejection` or `test_wrong_day_*` test, update with the same pattern.

**Verification command for all four test files:**
```bash
cd /Users/benson/Projects/bluemarlin-agent && python3 -m pytest wtyj/tests/marina/test_marina_tone.py wtyj/tests/marina/test_048_human_speech_optimization.py wtyj/tests/marina/test_047_reschedule_booking_flow.py wtyj/tests/marina/test_064_hardening.py -v --tb=short 2>&1 | tail -40
```

All four files must import cleanly and all remaining tests must pass.

#### 3i. Add new tests — `wtyj/tests/social/test_161_race_ref_multilang.py`

Create a new test file:

```python
"""Tests for Brief 161 — per-phone lock, ref regex, multi-language booking flow."""
import os
import re
import sys
import threading
import time
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")
os.environ.setdefault("ZERNIO_WEBHOOK_SECRET", "test")

from agents.marina import marina_agent


# --- Booking ref regex (Fix 2) ---

_BRIEF161_REF_REGEX = re.compile(r'\b(?=[A-Z0-9]*\d)[A-Z0-9]{6}\b')


def test_ref_regex_matches_real_booking_ref():
    """Real ref BF9999 still matches."""
    assert _BRIEF161_REF_REGEX.search("My booking ref is BF9999, please help") is not None


def test_ref_regex_matches_all_digits():
    """6-digit ref still matches."""
    assert _BRIEF161_REF_REGEX.search("ref 123456 please") is not None


def test_ref_regex_rejects_all_letters_sunset():
    """All-letter SUNSET must not be matched as a ref (the c13 bug)."""
    assert _BRIEF161_REF_REGEX.search("I WANT SUNSET CRUISE FOR 4 FRIDAY") is None


def test_ref_regex_rejects_all_letters_friday_cruise():
    """Common shout words that used to false-positive."""
    for word in ("FRIDAY", "CRUISE", "SUNSET", "CASTLE", "ACTION"):
        assert _BRIEF161_REF_REGEX.search(f"I want {word}") is None, f"false positive on {word}"


def test_ref_regex_matches_mixed_letters_and_digit():
    """Real-world ref shapes with digit + letters."""
    for ref in ("BF9999", "AB1234", "XY9Z8W", "A1B2C3"):
        assert _BRIEF161_REF_REGEX.search(f"ref {ref}") is not None, f"missed {ref}"


def test_social_agent_uses_new_regex():
    """Source-level verification that social_agent.py uses the new regex."""
    src = open(
        os.path.join(os.path.dirname(__file__), "..", "..",
                     "agents", "social", "social_agent.py")
    ).read()
    assert r"(?=[A-Z0-9]*\d)" in src, "social_agent.py must use digit-required regex"


def test_email_poller_uses_new_regex():
    """Source-level verification that email_poller.py uses the new regex."""
    src = open(
        os.path.join(os.path.dirname(__file__), "..", "..",
                     "agents", "marina", "email_poller.py")
    ).read()
    assert r"(?=[A-Z0-9]*\d)" in src, "email_poller.py must use digit-required regex"


# --- Per-phone lock (Fix 1) ---

def test_get_phone_lock_returns_same_lock_for_same_key():
    """Calling _get_phone_lock twice for the same key returns the same lock object."""
    from agents.social.webhook_server import _get_phone_lock
    lock_a1 = _get_phone_lock("TEST_BRIEF161_KEY_A")
    lock_a2 = _get_phone_lock("TEST_BRIEF161_KEY_A")
    lock_b = _get_phone_lock("TEST_BRIEF161_KEY_B")
    assert lock_a1 is lock_a2
    assert lock_a1 is not lock_b


def test_per_phone_lock_serializes_concurrent_handlers():
    """Two concurrent _flush_buffer-style handler calls for the same phone run one at a time.
    This is the regression test for the a1 race condition from the 2026-04-08 E2E run."""
    from agents.social.webhook_server import _get_phone_lock

    key = "BRIEF161_RACE_TEST_KEY"
    lock = _get_phone_lock(key)

    order = []
    start_barrier = threading.Barrier(3)  # 2 workers + main thread

    def worker(worker_id):
        start_barrier.wait()
        with lock:
            order.append(f"start_{worker_id}")
            time.sleep(0.05)
            order.append(f"end_{worker_id}")

    t1 = threading.Thread(target=worker, args=("A",))
    t2 = threading.Thread(target=worker, args=("B",))
    t1.start()
    t2.start()
    start_barrier.wait()
    t1.join(timeout=2)
    t2.join(timeout=2)

    # Serialized: each start is immediately followed by its own end — no interleaving
    assert len(order) == 4
    assert order[1] == order[0].replace("start_", "end_")
    assert order[3] == order[2].replace("start_", "end_")


# --- Prompt BOOKING VALIDATION section (Fix 3) ---

def test_prompt_has_booking_validation_section():
    """Brief 161: BOOKING VALIDATION block present in Marina's system prompt."""
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "BOOKING VALIDATION" in prompt


def test_prompt_mentions_past_date_check():
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "PAST DATE" in prompt or "past date" in prompt.lower()


def test_prompt_mentions_wrong_day_check():
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "WRONG DAY" in prompt or "days_available" in prompt


def test_prompt_mentions_multi_departure_check():
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "MULTI-DEPARTURE" in prompt or "multi-departure" in prompt.lower()


def test_prompt_tells_marina_to_generate_summary():
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "confirmation summary" in prompt.lower() or "write a confirmation" in prompt.lower()


def test_prompt_demands_exact_prices_no_hallucination():
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "CRITICAL PRICE ACCURACY" in prompt or "EXACT" in prompt


def test_prompt_demands_customer_language():
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "CRITICAL LANGUAGE" in prompt or "customer's detected language" in prompt


def test_prompt_no_longer_claims_python_handles_summary():
    """The old 'Python handles all booking validation, state management, and summary generation' is gone."""
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    assert "Python handles all booking validation, state management, and summary generation" not in prompt


def test_prompt_validation_section_uses_interpolated_terminology():
    """Brief 161: service_label and party_size_label from client terminology are interpolated.
    For BlueMarlin (service_label='trip', party_size_label='guests')."""
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    # BlueMarlin terminology
    assert "guests" in prompt
    assert "trip" in prompt


def test_prompt_for_adamus_uses_restaurant_terminology():
    """Brief 161: Adamus terminology (service_label='reservation', party_size_label='diners')
    must flow through the prompt builder.

    IMPORTANT: config_loader captures _CONFIG_PATH at module import time
    (shared/config_loader.py:16). Simply reassigning os.environ['CLIENT_CONFIG_PATH']
    after import has NO effect — we must directly rewrite config_loader._CONFIG_PATH
    and clear its cache. marina_agent itself does not need reloading because it
    calls config_loader.get_business() / get_raw() at every prompt build, which
    pick up the new cache contents.
    """
    from shared import config_loader

    adamus_path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "..",
        "clients", "adamus", "config", "client.json"
    ))
    assert os.path.exists(adamus_path), f"Adamus config not found at {adamus_path}"

    old_path = config_loader._CONFIG_PATH
    old_cache = dict(config_loader._cache)
    config_loader._CONFIG_PATH = adamus_path
    config_loader._cache = {}
    try:
        prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
        # Adamus terminology
        assert "diners" in prompt, f"Expected 'diners' in Adamus prompt, got: {prompt[:500]}"
        assert "reservation" in prompt, f"Expected 'reservation' in Adamus prompt"
        # BlueMarlin terminology should NOT leak
        assert "guests" not in prompt.split("BOOKING BEHAVIOUR:")[1].split("BOOKING PACING:")[0], \
            "Adamus prompt leaked BlueMarlin 'guests' terminology"
        # Adamus has 4 languages (English, Dutch, Spanish, Papiamentu) — not 6
        assert "German" not in prompt
        assert "Portuguese" not in prompt
    finally:
        config_loader._CONFIG_PATH = old_path
        config_loader._cache = old_cache
```

### Post-validation live E2E (manual, documented in output)

After tests pass and the code is deployed, run these via the existing `/tmp/e2e_full.py` harness (or equivalent) against the VPS and document in `marina_output_161.md`:

1. **Race condition fix**: run test a1 (happy booking with fast "Yes please" follow-up). Verify `wa_booking_state.flags` has `awaiting_booking_confirmation=true` + `hold_id` set AFTER both messages have been processed. Compare against the 2026-04-08 trace that showed the bug.

2. **ALL CAPS shout**: send "I WANT TO BOOK A SUNSET CRUISE RIGHT NOW FOR 4 PEOPLE FRIDAY!!!!". Verify Marina's reply does NOT contain "reference SUNSET" or "couldn't find a booking".

3. **Dutch booking summary**: send "Hallo Marina, ik wil graag een sunset cruise boeken voor 2 personen komende vrijdag". Verify Marina's reply IS a summary IN DUTCH containing the price and guest count.

4. **Papiamentu booking summary**: send "Bon dia Marina! Mi ke reservá un Sunset Cruise pa 2 hende djabierne". Verify reply is in Papiamentu and contains price/guest count.

5. **Spanish booking summary**: "Hola Marina, quiero reservar el sunset cruise para 2 personas el próximo viernes". Verify Spanish + price.

6. **German booking summary**: "Hallo Marina, ich möchte die Sunset Cruise für 2 Personen am nächsten Freitag buchen". Verify German + price.

7. **Portuguese booking summary**: "Olá Marina, quero reservar o sunset cruise para 2 pessoas na próxima sexta". Verify Portuguese + price.

8. **Dutch past date rejection**: "Ik wil Klein Curacao boeken voor gisteren voor 2 personen". Verify Marina's reply IS in Dutch and says the date has passed.

9. **Dutch wrong day rejection**: "Ik wil de 3-in-1 Snorkeling Trip voor aanstaande dinsdag voor 2 personen". Verify Marina says in Dutch that the trip only runs on Fridays.

10. **Adamus smoke test**: via direct container invocation, verify Sofia renders the BOOKING VALIDATION block with `diners`/`reservation` terminology.

## Tests

Full run: `python3 -m pytest tests/marina/ tests/social/ -q --tb=line`

Expected baseline: same or more tests as Brief 160 (738 pass). New Brief 161 tests add ~15 tests. Some existing tests get deleted (test_build_booking_summary_*, test_suggest_dates_* if removed). Net change should be roughly neutral (+10 / -8).

Specific must-pass tests from the new file:
- `test_ref_regex_rejects_all_letters_sunset`
- `test_ref_regex_matches_real_booking_ref`
- `test_per_phone_lock_serializes_concurrent_handlers`
- `test_prompt_has_booking_validation_section`
- `test_prompt_no_longer_claims_python_handles_summary`
- `test_prompt_for_adamus_uses_restaurant_terminology`

Specific rewritten tests from test_070:
- `test_post_validate_all_pass_advances_state`: `override is None`, `should_set is True`
- `test_orchestrator_all_valid_advances_state_keeps_marinas_summary`: Marina's reply preserved + awaiting flag set
- `test_orchestrator_wrong_day_keeps_marinas_reply`: Marina's wrong-day reply preserved, no awaiting flag

## Success Condition

1. `_build_booking_summary` is deleted from both `social_agent.py` and `email_poller.py`.
2. `_post_validate` in both files returns `(None, bool)` in every branch — no string reply overrides anywhere.
3. `grep -rn "Just to confirm" wtyj/agents/` returns no matches.
4. Marina's system prompt contains the BOOKING VALIDATION block with PAST DATE / WRONG DAY / MULTI-DEPARTURE / summary instructions.
5. Per-phone lock exists at `webhook_server._get_phone_lock` and is used in `_flush_buffer`.
6. The booking ref regex in both files requires at least one digit.
7. `python3 -m pytest tests/marina/ tests/social/ -q --tb=line` passes cleanly with zero failures.
8. The 10 live E2E cases above all produce the expected language and content.
9. Both containers deploy successfully and `/health` returns `ok`.

## Rollback

All changes are in-place edits to 4 files + test file additions/modifications. No schema, no deployment, no config. Rollback = `git revert <commit>` and redeploy.

Specifically, if something goes wrong in production with Marina hallucinating bad prices:

1. `git revert` the Brief 161 commit.
2. Redeploy (`docker compose build && up -d`).
3. The old `_build_booking_summary` + English templates are restored.
4. Multi-language booking summaries revert to English but no customer data is lost.

The race condition fix and the ref regex fix are orthogonal; they can be kept even if the multi-language fix is reverted. If needed, cherry-pick those two small changes into a separate commit first (race fix + ref regex), then do the multi-language change as a second commit on top. That gives us two independent revert points.
