# OUTPUT 135 — Feature Toggles: Booking Flow + Terminology + Random Ref

## What was done

### config/client.json
- Added `features.booking_flow: true`
- Added `terminology` section with `service_label: "trip"`, `party_size_label: "guests"`, `slot_label: "departure"`
- Removed `booking_ref_prefix` from booking_rules

### agents/social/social_agent.py
- Added booking flow toggle: when `features.booking_flow` is false, booking intents create a detailed escalation (with chat log, collected fields, Marina's note) instead of entering the booking state machine
- Replaced prefix-based booking ref with random 6-char alphanumeric (`random.choices(string.ascii_uppercase + string.digits, k=6)`)
- Updated returning customer regex from `BF-\d{4}-\d{5}` to `\b[A-Z0-9]{6}\b`
- Added `import random, string`

### agents/marina/email_poller.py
- Same random booking ref change
- Updated `_detect_booking_ref()` to use new regex + DB verification to avoid false positives
- Added `import random, string`

### agents/marina/marina_agent.py
- Added terminology reads from config at top of `_build_system_prompt()`
- BOOKING BEHAVIOUR section now uses `{service_label}`, `{party_size_label}`, `{slot_label}` from config
- Fallback response in `process_message()` uses terminology for clarifications and reply text

### agents/social/dm_agent.py
- Added terminology read from config
- Service list header uses `{service_label.upper()}S:` instead of hardcoded "TRIPS:"
- Q&A intro, listing instruction, and booking redirect all use `{service_label}`

## Test results
- Brief 135 tests: 7/7 passed
- Full social regression: pending

## Unexpected
- `config_loader.get_raw()` returns a shallow copy. Tests modifying it don't affect the cached original. Had to modify `config_loader._cache` directly in tests with try/finally cleanup.
- `save_booking()` takes `(ref, fields_dict, flags_dict)` not positional args — test had wrong signature.
