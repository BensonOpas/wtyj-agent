# OUTPUT_024 — email_poller.py Refactor — Unified Claude Call Integration

## Files modified
- `bluemarlin/src/email_poller.py` — major refactor
- `bluemarlin/src/marina_agent.py` — one-line prompt amendment

## Files created
- `bluemarlin/briefs/OUTPUT_024.md` (this file)

---

## Part 1 — marina_agent.py amendment

Updated the `fields` description in the prompt inside `_build_prompt()`:

**Before:**
```
"fields": {"<extracted booking fields — experience, date, guests, customer_name, phone, special_requests — only if present and certain>"},
```

**After:**
```
"fields": {"<extracted booking fields — experience, date, guests, customer_name, phone, special_requests, trip_key — only if present and certain. trip_key is the exact key from the trips list that matches the experience: one of klein_curacao, snorkeling_3in1, west_coast_beach, sunset_cruise, jet_ski — only include if you are certain which trip they mean>"},
```

File header updated: LAST MODIFIED Brief 023 → Brief 024.

---

## Part 2 — email_poller.py refactor

### Removed functions (19)
detect_intent_and_fields, ask_marina_llm, classify_date_input, normalize_date_to_yyyy_mm_dd,
is_date_confirmation_yes, experience_is_clear, package_key_from_experience,
default_start_time_for_package, price_for_package, safe_out_of_scope_reply,
safe_complaint_reply, safe_social_reply, safe_inquiry_reply, safe_change_request_reply,
safe_large_group_reply, safe_date_confirmation_reply, safe_date_past_reply,
safe_date_implausible_reply, safe_date_vague_reply, safe_experience_unclear_reply

### Removed constants
- `REQUIRED_FIELDS`
- `GROUP_BOOKING_THRESHOLD`

### Import changes
- Removed: `import claude_client`, `import dateparser`
- Added: `import marina_agent`, `import config_loader`

### create_calendar_hold() — rewritten
- Accepts `trip_key` from `fields_now.get("trip_key")`; returns error if missing
- `start_time` from `config_loader.get_trip(trip_key)["departures"][0]["time"]` (fallback "09:00")
- `price_usd` from `config_loader.get_trip(trip_key)["price_adult_usd"]`
- Passes `trip_key` as `package_key` to calendar.js (unchanged interface)
- Past-date guard removed — Claude handles date validation

### Main loop — new structure

**Unchanged:** IMAP connect, UNSEEN fetch, uid iteration, RFC822 fetch, from/subject/body
extraction, deduplication via state_registry, anti-loop guard, thread state load/save, mark Seen.

**New dispatch (replaces old intent dispatch block):**

- **Step 1:** `marina_agent.process_message(from_email, subj, body, th["fields"], th["flags"])`
- **Step 2:** Merge result["fields"] into th["fields"] — existing non-empty values not overwritten
- **Step 3:** Merge result["flags"] into th["flags"]
- **Step 4:** If `requires_human` → send reply, log "human_required", persist, continue
- **Step 5:** If "booking" in intents:
  - If experience + date + guests all present AND hold_created not True → `create_calendar_hold()`
    - Fail → log hold_failed, send reply, persist, continue
    - Success → set hold flags, generate payment link, log hold_created
  - Send result["reply"] for all booking sub-cases
- **Step 6:** All other intents → send result["reply"], log primary_intent, log to sheets_writer
- **Step 7:** Mark Seen, append reply_time, update last_customer_hash, save state

**Constraint respected:** Python never modifies result["reply"]. Reply is sent exactly as returned
from marina_agent. Python routes on structured values only.

---

## Test results

| # | Test | Result |
|---|------|--------|
| 1 | email_poller imports cleanly; marina_agent present; claude_client absent | PASS |
| 2 | All 11 removed functions are gone | PASS |
| 3 | All 7 kept functions intact | PASS |
| 4 | create_calendar_hold with no trip_key → ok=False, "trip_key" in error | PASS |
| 5 | create_calendar_hold with mocked config → start_time=17:30, price_usd=79 | PASS |
| 6 | marina_agent sunset cruise message → fields.trip_key == "sunset_cruise" | PASS |
| 7 | GROUP_BOOKING_THRESHOLD and REQUIRED_FIELDS not present in email_poller | PASS |
| 8 | No "import dateparser" or "import claude_client" in source | PASS |

---

## Regression check block
```
python3 -c "
import sys; sys.path.insert(0, 'bluemarlin/src')
import email_poller

# imports
assert hasattr(email_poller, 'marina_agent')
assert not hasattr(email_poller, 'GROUP_BOOKING_THRESHOLD')
assert not hasattr(email_poller, 'REQUIRED_FIELDS')
assert not hasattr(email_poller, 'detect_intent_and_fields')
assert not hasattr(email_poller, 'safe_complaint_reply')
assert hasattr(email_poller, 'create_calendar_hold')
assert hasattr(email_poller, 'smtp_send')

# trip_key guard
r = email_poller.create_calendar_hold({'experience': 'sunset', 'date': '2026-04-20', 'guests': 2})
assert r['ok'] is False and 'trip_key' in r['error']

with open('bluemarlin/src/email_poller.py') as f: src = f.read()
assert 'import dateparser' not in src
assert 'import claude_client' not in src

print('email_poller Brief 024 regression OK')
"
```

## Architecture notes
- All language decisions now belong to Claude (via marina_agent)
- Python is a pure orchestrator: routes on structured values, persists state, calls calendar/payment APIs
- Drift items from ARCHITECTURE_DRIFT_LOG.md (Briefs 016–020) are fully removed from email_poller.py
- marina_agent.py retains the trip_key classification in its prompt (added Brief 024)
