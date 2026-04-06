# OUTPUT_020 — Booking intake fixes

## Files modified
- `bluemarlin/src/email_poller.py`
- `bluemarlin/src/marina_extractor.py`

## Files created
- `bluemarlin/briefs/OUTPUT_020.md` (this file)

## Changes made

### File headers
- `email_poller.py` LAST MODIFIED: Brief 019 → Brief 020
- `marina_extractor.py` LAST MODIFIED: Brief 018 → Brief 020

### email_poller.py

#### Change 1 — GROUP_BOOKING_THRESHOLD constant
```python
GROUP_BOOKING_THRESHOLD = 15
```
Added after REQUIRED_FIELDS constant block.

#### Change 2 — safe_large_group_reply(guests)
Added before `safe_date_confirmation_reply()`. Returns a warm hand-off
message for groups of GROUP_BOOKING_THRESHOLD or more, without attempting
an automated booking.

#### Change 3 — safe_date_confirmation_reply() updated
Return string rewritten from formal/robotic tone to conversational:
```python
return (
    f"Hi there!\n\n"
    f"Just making sure — are you thinking {friendly}? "
    f"Say yes and I'll get your spot held right away, or "
    f"send me a different date if that's not right \U0001f60a\n\n"
    f"Warm regards,\nMarina\nBlueMarlin Tours Curaçao\n"
)
```

#### Change 4 — safe_date_past_reply(resolved_date, original)
Added after `safe_date_confirmation_reply()`. Tells customer the date
has passed and suggests same date next year (formatted with strftime).

#### Change 5 — safe_date_implausible_reply(resolved_date, original)
Added after `safe_date_past_reply()`. Asks customer to confirm a
far-future date (>2 years ahead) before proceeding.

#### Change 6 — safe_date_vague_reply(original, resolvable_date="")
Added after `safe_date_implausible_reply()`. Asks for a specific date
when the input is too vague to parse reliably.

#### Change 7 — experience_is_clear(exp)
```python
def experience_is_clear(exp: str) -> bool:
    return bool(package_key_from_experience(exp))
```
Added after `package_key_from_experience()`.

#### Change 8 — safe_experience_unclear_reply(provided)
Added after `experience_is_clear()`. Shows the three available
BlueMarlin packages with duration and departure time.

#### Change 9 — classify_date_input(date_val) replaces is_date_ambiguous()
Full 5-category classifier replacing the old boolean helper:
- `CLEAR_FUTURE` — today, tomorrow, or date with explicit year in the future
- `PAST` — resolved date is before today
- `IMPLAUSIBLE` — explicit year is more than 2 years ahead
- `VAGUE_RESOLVABLE` — relative phrases (next Friday, in two weeks, etc.)
- `VAGUE_NEEDS_INPUT` — no year, no recognisable relative pattern

The old `is_date_ambiguous()` reference in the date confirmation intercept
(Brief 019 code) was also updated to:
```python
if classify_date_input(new_date) in ("VAGUE_RESOLVABLE", "VAGUE_NEEDS_INPUT"):
```

#### Change 10 — Three-check block in booking dispatch
Replaced the old single ambiguous-date check with three sequential checks
inside `if "booking" in intents:`, each using `continue` with state saved:

1. **Date classification check** — calls `classify_date_input(raw_date)`:
   - PAST → `safe_date_past_reply()` → continue
   - IMPLAUSIBLE → `safe_date_implausible_reply()` → continue
   - VAGUE_NEEDS_INPUT or VAGUE_RESOLVABLE → sets `awaiting_date_confirmation`,
     calls `safe_date_vague_reply()` or `safe_date_confirmation_reply()` → continue
   - CLEAR_FUTURE → fall through

2. **Experience clarity check** — `experience_is_clear(provided_experience)`:
   - Unknown experience → sets `awaiting_experience_clarification`,
     calls `safe_experience_unclear_reply()` → continue
   - Clear → fall through

3. **Large group check** — `int(guest_count) >= GROUP_BOOKING_THRESHOLD`:
   - Over threshold → `safe_large_group_reply()` → continue
   - Under threshold → fall through

4. Existing missing fields check unchanged below all three.

### marina_extractor.py

#### Change 11 — guests/adults/kids annotation updated
```
- guests (total number of people — must be an exact integer.
  "Just me" = 1. "Me and my wife" = 2. "A family of 4" = 4.
  "Family of 4 plus a baby/infant/toddler" = 4 — do NOT count
  infants under 2 in the guest total; add them to special_requests
  instead. "Around 10" or "about 10" — do NOT extract guests,
  omit the field so Marina can ask for an exact number.)
- adults (if specified separately as an integer)
- kids (if specified separately as an integer — does not include infants)
```

#### Change 12 — guests rule added to Rules block
```
- For guests: extract ONLY a definite integer. If the customer uses
  approximate language ("around", "about", "roughly", "maybe",
  "approximately") do NOT extract guests — omit it entirely so
  Marina asks for an exact count. If an infant/baby is mentioned
  alongside a guest count, do NOT include the infant in the count —
  add "travelling with an infant" to special_requests instead.
```

## Test results

```
# Test 1 — imports cleanly
IMPORT OK

# Test 2 — classify_date_input() basic cases
PASS — classify_date_input() basic cases correct

# Test 3 — safe_large_group_reply() valid
Hi there!

Wow, a group of 20 — that sounds like an amazing trip! 🎉

For groups this size we like to make sure everything is set up perfectly
for you. One of our team will be in touch shortly to discuss the best
options and get everything arranged.

We can't wait to have you all on board!

Warm regards,
Marina
BlueMarlin Tours Curaçao

PASS — safe_large_group_reply() valid

# Test 4 — safe_date_past_reply() valid
PASS — safe_date_past_reply() valid

# Test 5 — safe_date_implausible_reply() valid
PASS — safe_date_implausible_reply() valid

# Test 6 — safe_experience_unclear_reply() valid
PASS — safe_experience_unclear_reply() valid

# Test 7 — experience_is_clear() correct
PASS — experience_is_clear() correct

# Test 8 — all new symbols present, old symbol removed
PASS — all new symbols present, old symbol removed
```

All 8 tests pass.

## Assumptions
- `classify_date_input()` placed immediately after `normalize_date_to_yyyy_mm_dd()` — it calls that function internally
- IMPLAUSIBLE threshold is >2 years (730 days) from today
- VAGUE_PATTERNS list: "some day", "someday", "eventually", "soon", "whenever", "asap", "at some point"
- RESOLVABLE_PATTERNS: "next", "this ", "in one", "in two", "in a", "in 1", "in 2", "week", "month"
- `safe_date_vague_reply()` is called for VAGUE_NEEDS_INPUT; `safe_date_confirmation_reply()` for VAGUE_RESOLVABLE
- The old `is_date_ambiguous` reference in the date confirmation intercept (Brief 019) was updated to use `classify_date_input()` — this is the only place it appeared
- marina_extractor.py prompt changes instruct the LLM; no runtime logic changed

## Dependencies added
None.

## SYSTEM_STATE update block
```
Brief 020 — email_poller.py + marina_extractor.py — booking intake fixes
  email_poller.py:
    GROUP_BOOKING_THRESHOLD = 15
    New functions: safe_large_group_reply(), safe_date_past_reply(),
      safe_date_implausible_reply(), safe_date_vague_reply(),
      experience_is_clear(), safe_experience_unclear_reply(),
      classify_date_input()
    Removed: is_date_ambiguous() (replaced by classify_date_input())
    Booking dispatch: three-check block (date → experience → large group)
      replaces old single ambiguous-date check
    New thread flags: awaiting_experience_clarification
    safe_date_confirmation_reply() tone updated (less robotic)
  marina_extractor.py:
    guests annotation updated — infant handling, approximate counts
    guests rule added to Rules block
```

## Dependency impact
```
Files that import email_poller: none (standalone poller)
Files that import marina_extractor: email_poller.py
What callers should expect differently:
  - Vague dates (no year, no pattern) → confirmation request before hold
  - Past dates → date correction reply, no hold
  - Far-future dates (>2yr) → implausibility check reply
  - Unknown experience names → clarification reply showing 3 packages
  - Groups >= 15 → hand-off reply, no automated hold
  - Approximate guest counts ("around 10") → LLM omits guests field,
    Marina's missing-fields check asks for exact count
  - Infants mentioned with group → not counted in guests, noted in
    special_requests by LLM
```

## Regression check block
```
# BRIEF_020 — email_poller.py + marina_extractor.py — intake fixes
python3 -c "
import sys; sys.path.insert(0, 'bluemarlin/src')
import email_poller
# classify_date_input
assert email_poller.classify_date_input('2026-04-15') == 'CLEAR_FUTURE'
assert email_poller.classify_date_input('today') == 'CLEAR_FUTURE'
assert email_poller.classify_date_input('2020-01-01') == 'PAST'
# large group
r = email_poller.safe_large_group_reply(20)
assert '20' in r and 'Marina' in r
# experience
assert email_poller.experience_is_clear('sunset') == True
assert email_poller.experience_is_clear('random') == False
# symbols
with open('bluemarlin/src/email_poller.py') as f: ep = f.read()
with open('bluemarlin/src/marina_extractor.py') as f: me = f.read()
assert 'GROUP_BOOKING_THRESHOLD' in ep
assert 'classify_date_input' in ep
assert 'is_date_ambiguous' not in ep
assert 'infants under 2' in me
print('email_poller + marina_extractor Brief 020 regression OK')
"
```
