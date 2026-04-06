# BRIEF 011 — marina_extractor.py — special_requests field
# Read CODEX_CONTEXT.md before executing this brief
## Objective
Add a special_requests field to marina_extractor.py so that
any dietary requirements, accessibility needs, allergies,
celebratory requests, or other customer notes are captured
during field extraction and carried through to the booking record.
## Context
Currently marina_extractor.py extracts 7 fields:
experience, date, guests, adults, kids, customer_name, phone.
Customer context like "I'm diabetic", "wheelchair user",
"celebrating a birthday", "allergies to shellfish" is currently
lost — not extracted, not logged, not shown anywhere.
This brief adds special_requests as an 8th field.
## File to modify
bluemarlin/src/marina_extractor.py
## Files to read before making any changes
Read bluemarlin/src/marina_extractor.py in full before touching anything.
## Changes required
STEP 1 — Add special_requests to ALLOWED_KEYS
Current set:
  ALLOWED_KEYS = {
      "experience", "date", "guests",
      "adults", "kids", "customer_name", "phone"
  }
Replace with:
  ALLOWED_KEYS = {
      "experience", "date", "guests",
      "adults", "kids", "customer_name", "phone",
      "special_requests"
  }
STEP 2 — Update the extraction prompt
Current allowed keys block in the prompt:
  Allowed keys:
  - experience
  - date
  - guests
  - adults
  - kids
  - customer_name
  - phone
Replace with:
  Allowed keys:
  - experience (which boat tour they want)
  - date (when they want to go)
  - guests (total number of people)
  - adults (if specified separately)
  - kids (if specified separately)
  - customer_name (their name)
  - phone (their phone number)
  - special_requests (dietary needs, allergies, accessibility
    requirements, celebrations, drink preferences, or any
    other personal notes — capture verbatim as a single string)
Also add this rule to the Rules block:
  - For special_requests: capture any personal context,
    dietary restrictions, accessibility needs, allergies,
    celebrations, or preferences verbatim. If none are
    mentioned, omit the field entirely.
STEP 3 — Update the file header
  # FILE: marina_extractor.py
  # CREATED: Before Brief 001 (original codebase)
  # LAST MODIFIED: Brief 011
  # DEPENDS ON: claude_client.py (Brief 001)
  # IMPORTS FROM: claude_client.py (Brief 001)
## Constraints
- Do not change the function signature
- Do not change the return type
- Do not change the claude_client import block
- Do not change the clean = {k: v ...} filter line —
  it already handles the new key correctly via ALLOWED_KEYS
- Do not touch any other file
## Test commands
Run all tests from the project root directory.
Report exact output of each test.
# Test 1 — imports cleanly
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import marina_extractor
print('IMPORT OK')
"
# Test 2 — special_requests extracted from clear message
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import marina_extractor
result = marina_extractor.extract_fields(
    'Hi I want to book the sunset cruise for 2 people on March 20. '
    'My name is Sarah. Phone +5999123456. '
    'By the way I am diabetic and my partner uses a wheelchair.'
)
print('Result:', result)
assert 'special_requests' in result, f'FAIL: special_requests not extracted, got {result}'
print('PASS — special_requests:', result['special_requests'])
"
# Test 3 — special_requests omitted when none mentioned
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import marina_extractor
result = marina_extractor.extract_fields(
    'I want to book the half day charter for 4 people on 2026-03-25.'
)
print('Result:', result)
assert 'special_requests' not in result or result.get('special_requests') in (None, ''), \
    f'FAIL: special_requests present when not mentioned: {result}'
print('PASS — special_requests correctly omitted')
"
# Test 4 — celebration context captured
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import marina_extractor
result = marina_extractor.extract_fields(
    'Booking for my dads birthday, he loves Blue Label whiskey. '
    'Sunset cruise, 6 people, March 28. Name: Carlos. Phone +5999777888.'
)
print('Result:', result)
assert 'special_requests' in result, f'FAIL: special_requests not extracted'
sr = result['special_requests'].lower()
assert 'whiskey' in sr or 'birthday' in sr or 'blue label' in sr, \
    f'FAIL: context not captured: {result[\"special_requests\"]}'
print('PASS — celebration context captured:', result['special_requests'])
"
# Test 5 — special_requests is a string not a list
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import marina_extractor
result = marina_extractor.extract_fields(
    'I have a nut allergy and my wife is vegan. '
    'Sunset cruise, 2 people, April 5. Name: Tom. Phone +5999444555.'
)
print('Result:', result)
if 'special_requests' in result:
    assert isinstance(result['special_requests'], str), \
        f'FAIL: special_requests is not a string: {type(result[\"special_requests\"])}'
    print('PASS — special_requests is string:', result['special_requests'])
else:
    print('SKIP — special_requests not returned for this input')
"
# Test 6 — all original fields still extracted correctly
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import marina_extractor
result = marina_extractor.extract_fields(
    'Hi I want to book the full day west coast escape for 3 people '
    'on 2026-04-10. My name is James. Phone +5999222333.'
)
print('Result:', result)
assert result.get('experience'), 'FAIL: experience missing'
assert result.get('date'), 'FAIL: date missing'
assert result.get('guests') or result.get('adults'), 'FAIL: guests missing'
print('PASS — all original fields present')
"
# Test 7 — ALLOWED_KEYS contains special_requests
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import marina_extractor
assert 'special_requests' in marina_extractor.ALLOWED_KEYS, \
    'FAIL: special_requests not in ALLOWED_KEYS'
print('PASS — ALLOWED_KEYS updated:', marina_extractor.ALLOWED_KEYS)
"
## Definition of done
- [ ] marina_extractor.py modified in bluemarlin/src/
- [ ] File header updated (Brief 011)
- [ ] special_requests added to ALLOWED_KEYS
- [ ] Extraction prompt updated with special_requests field and rules
- [ ] All 7 tests pass with exact output shown
- [ ] OUTPUT_011.md written to bluemarlin/briefs/
- [ ] OUTPUT_011.md includes SYSTEM_STATE update block
- [ ] OUTPUT_011.md includes dependency impact block
- [ ] OUTPUT_011.md includes regression check block
