# BRIEF 002 — marina_extractor.py
# Read CODEX_CONTEXT.md before executing this brief
## Objective
Replace the OpenClaw subprocess call in marina_extractor.py
with a direct call to claude_client.extract(). This is a
surgical change only. Behavior stays identical from the
caller's perspective. No other files are touched.
## Context
marina_extractor.py currently calls OpenClaw via subprocess.run()
to extract booking fields from customer email text.
claude_client.py was created in Brief 001 and exposes extract()
which does exactly the same job via the Anthropic API directly.
The prompt text inside extract_fields() does not change.
Only the mechanism that executes the prompt changes.
## File to modify
bluemarlin/src/marina_extractor.py
## Read this file before making any changes
bluemarlin/src/claude_client.py
## Current behavior
extract_fields(text: str) builds a prompt string, passes it to
OpenClaw via subprocess.run(), reads stdout, uses re.search to
find a JSON object in the output, parses it with json.loads,
filters the keys to ALLOWED_KEYS, and returns a dict.
Returns {} on any failure.
## Required behavior after this change
extract_fields(text: str) builds the exact same prompt string,
passes it to claude_client.extract(prompt), filters the result
to ALLOWED_KEYS, and returns a dict.
Returns {} on any failure.
The function signature does not change.
The prompt text does not change.
ALLOWED_KEYS does not change.
## Changes required — follow this order exactly
STEP 1
Remove this import from the top of the file:
  import json
STEP 2
Remove this import from the top of the file:
  import subprocess
STEP 3
Remove this import:
  import re
STEP 4
Remove this line from the top of the file:
  SESSION_ID = "marina_extract_session"
STEP 5
Add these four lines at the top of the file,
after the remaining imports:
  import sys
  import os
  sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
  import claude_client
STEP 6
Inside extract_fields(), remove the entire try/except block.
That is everything from the line "try:" down to and including
the final "return {}".
Replace it with the following four lines:
  result = claude_client.extract(prompt)
  if not isinstance(result, dict):
      return {}
  clean = {k: v for k, v in result.items() if k in ALLOWED_KEYS}
  return clean
STEP 7
Add this file header as the very first lines of the file,
before any imports:
  # FILE: marina_extractor.py
  # CREATED: Before Brief 001 (original codebase)
  # LAST MODIFIED: Brief 002
  # DEPENDS ON: claude_client.py (Brief 001)
  # IMPORTS FROM: claude_client.py (Brief 001)
## Constraints
- Do not change the prompt text inside extract_fields()
- Do not change ALLOWED_KEYS
- Do not change the function signature extract_fields(text: str)
- Do not touch any other file in this brief
- Do not install any new packages
- The function must always return a dict — never raise an exception
- Do not add retries or logging in this brief
## Test commands
ANTHROPIC_API_KEY is already set as an environment variable.
Run all tests from the project root directory.
Report the exact output of each test.
# Test 1 — file imports cleanly with no errors
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import marina_extractor
print('IMPORT OK')
"
# Test 2 — extracts fields from a natural language booking message
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import marina_extractor
result = marina_extractor.extract_fields(
    'I want to book the sunset cruise on March 20 for 4 people'
)
print('Result:', result)
assert isinstance(result, dict), 'FAIL: result is not a dict'
assert len(result) > 0, 'FAIL: result is empty'
print('PASS')
"
# Test 3 — returns empty dict on empty input
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import marina_extractor
result = marina_extractor.extract_fields('')
print('Empty input result:', result)
assert isinstance(result, dict), 'FAIL: result is not a dict'
print('PASS')
"
# Test 4 — returns empty dict on bad API key
ANTHROPIC_API_KEY=bad_key python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import marina_extractor
result = marina_extractor.extract_fields('book sunset cruise')
assert result == {}, f'FAIL: expected empty dict, got {result!r}'
print('PASS — graceful failure confirmed')
"
# Test 5 — only returns keys from ALLOWED_KEYS
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import marina_extractor
result = marina_extractor.extract_fields(
    'My name is John, I want to book the sunset cruise on March 20 for 2 adults and 1 kid, my phone is +5999123456'
)
print('Result:', result)
allowed = {'experience','date','guests','adults','kids','customer_name','phone'}
unexpected = [k for k in result.keys() if k not in allowed]
assert not unexpected, f'FAIL: unexpected keys found: {unexpected}'
print('PASS — all keys are allowed')
"
# Test 6 — confirm removed imports and openclaw are gone from the file
python3 -c "
with open('bluemarlin/src/marina_extractor.py') as f:
    content = f.read()
assert 'subprocess' not in content, 'FAIL: subprocess still present'
assert 'import json' not in content, 'FAIL: json import still present'
assert 'import re' not in content, 'FAIL: re import still present'
assert 'SESSION_ID' not in content, 'FAIL: SESSION_ID still present'
assert 'openclaw' not in content.lower(), 'FAIL: openclaw reference still present'
assert 'claude_client' in content, 'FAIL: claude_client not found in file'
print('PASS — file structure is correct')
"
## Definition of done
- [ ] marina_extractor.py exists in bluemarlin/src/ and is modified
- [ ] File header added at top (Brief 002)
- [ ] import json removed
- [ ] import subprocess removed
- [ ] SESSION_ID removed
- [ ] claude_client imported and used in extract_fields()
- [ ] All 6 tests pass with exact output shown
- [ ] OUTPUT_002.md written to bluemarlin/briefs/
- [ ] OUTPUT_002.md includes SYSTEM_STATE update block
- [ ] OUTPUT_002.md includes dependency impact block
- [ ] OUTPUT_002.md includes regression check block
