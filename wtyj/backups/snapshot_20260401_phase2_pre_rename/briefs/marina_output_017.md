# OUTPUT_017 — Warm confirmation email

## Files modified
- `bluemarlin/src/email_poller.py`

## Files created
- `bluemarlin/briefs/OUTPUT_017.md` (this file)

## Changes made

### File header
- `LAST MODIFIED` updated from `Brief 016` to `Brief 017`

### confirm block — replaced (around line 779)
Added two conditional variables before the `confirm` string:

- `social_opener` — fires when `"social" in intents`; adds warm "that means so much" line
- `special_note` — fires when `fields_now.get("special_requests")` is truthy; echoes the special request

New `confirm` string:
- Greeting changed from `"Hi,"` to `f"Hi {name},"`
- `social_opener` inserted after greeting (empty string when no social intent)
- Hold created line updated: `"you're one step closer to an unforgettable day on the water!"`
- Fields reordered: Package, Date, Guests (Name removed — already in greeting)
- `special_note` inserted after fields block
- Payment section reworded: "Your hold is valid for 6 hours. To confirm…"
- Payment link prefixed with 💳 emoji; payment status line removed (redundant)
- Added: "If you have any questions at all, just reply…"
- Added: "See you on the water! 🐟"
- Sign-off unchanged: `"Warm regards,\nMarina\nBlueMarlin Tours Curaçao\n"`

## Assumptions
- `name` variable is already defined above the block (`fields_now.get("customer_name", "—")`) — not redefined
- `intents` variable is in scope at this point in the dispatch block — confirmed by Brief 016
- `social_opener` and `special_note` are string concatenations only — cannot raise exceptions
- Emoji literals encoded as `\Uxxxxxxxx` unicode escapes for safety (same pattern as rest of file)

## Test results

```
# Test 1 — imports cleanly
IMPORT OK

# Test 2 — confirm template contains warm elements
PASS — warm confirmation template present

# Test 3 — social_opener only fires when social in intents
PASS — social intent check present
```

All 3 tests pass.

## Dependencies added
None.

## SYSTEM_STATE update block
```
Brief 017 — email_poller.py — confirm email warmed up
  Greeting now uses customer name: f"Hi {name},"
  social_opener fires when "social" in intents (empty string otherwise)
  special_note fires when special_requests present (empty string otherwise)
  Hold valid / payment CTA / "See you on the water" closing added
  No other logic changed. No new functions. No new imports.
```

## Dependency impact
```
Files that import email_poller: none (standalone poller)
What callers should expect differently: N/A — internal confirmation email only
```

## Regression check block
```
# BRIEF_017 — email_poller.py — warm confirm template present and intact
python3 -c "
import sys; sys.path.insert(0, 'bluemarlin/src')
import email_poller
with open('bluemarlin/src/email_poller.py') as f:
    content = f.read()
assert 'unforgettable day on the water' in content
assert 'social_opener' in content
assert 'special_note' in content
assert '\"social\" in intents' in content
assert 'Hi {name}' in content
print('email_poller Brief 017 regression OK')
"
```
