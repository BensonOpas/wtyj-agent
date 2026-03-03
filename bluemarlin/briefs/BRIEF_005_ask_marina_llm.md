# BRIEF 005 — email_poller.py — ask_marina_llm()
# Read CODEX_CONTEXT.md before executing this brief
## Objective
Replace the OpenClaw subprocess call inside ask_marina_llm()
in email_poller.py with a direct call to claude_client.complete().
This is the last remaining OpenClaw call in the codebase.
Surgical change only — one function body changes, nothing else.
## Context
email_poller.py contains a function ask_marina_llm() that generates
email reply text by calling OpenClaw via subprocess.run().
claude_client.py was created in Brief 001 and exposes complete()
which returns plain text from the Anthropic API directly.
The prompt text does not change. The fallback string does not change.
The function signature does not change.
The return type does not change — still a plain string.
## File to modify
bluemarlin/src/email_poller.py
## Files to read before making changes
bluemarlin/src/claude_client.py
Do not modify any other file.
## Current behavior
ask_marina_llm(from_email, subject, body, mode) builds a prompt
string, passes it to OpenClaw via subprocess.run(), reads stdout
as plain text, falls back to a hardcoded string if stdout is empty,
returns the text string.
## Required behavior after this change
ask_marina_llm(from_email, subject, body, mode) builds the exact
same prompt string, passes it to claude_client.complete(prompt),
uses the result as plain text, falls back to the same hardcoded
string if the result is empty string "", returns the text string.
Behavior is identical from the caller's perspective.
## Exact changes — do exactly this, nothing more, nothing less
STEP 1
Add these lines at the top of email_poller.py after the existing
imports block — after the line "import smtplib, base64":
  import sys as _sys
  import os as _os
  _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
  import claude_client
Use the underscore-prefixed names (_sys, _os) only for the
path insertion to avoid any conflict with the existing
"import os" and any future "import sys" in the file.
After the path insertion, import claude_client normally.
STEP 2
Inside ask_marina_llm(), remove these lines exactly:
  r = subprocess.run(
      ["openclaw", "agent", "--session-id", SESSION_ID, "--message", prompt, "--local"],
      capture_output=True, text=True, timeout=120
  )
  out = (r.stdout or "").strip()
Replace them with exactly this one line:
  out = claude_client.complete(prompt)
STEP 3
The fallback block stays exactly as it is — do not touch it:
  if not out:
      out = "Hi — thanks for your email. Could you share your preferred date, number of guests, and which experience you want?"
STEP 4
Do not remove SESSION_ID from the CONFIG block at the top of
the file. SESSION_ID removal is out of scope for this brief.
Do not remove the subprocess import — it is still used on
line 283 for the calendar.js call.
STEP 5
Update the file header at the very top of the file.
If no header exists, add one. If one exists, update it:
  # FILE: email_poller.py
  # CREATED: Before Brief 001 (original codebase)
  # LAST MODIFIED: Brief 005
  # DEPENDS ON: claude_client.py (Brief 001)
  # DEPENDS ON: state_registry.py (Brief 004)
  # DEPENDS ON: payment_stub.py (original)
  # DEPENDS ON: bm_logger.py (original)
  # DEPENDS ON: marina_extractor.py (Brief 002)
  # DEPENDS ON: social_registry.py (original)
  # IMPORTS FROM: claude_client.py (Brief 001)
  # IMPORTS FROM: state_registry.py (Brief 004)
  # IMPORTS FROM: marina_extractor.py (Brief 002)
  # IMPORTS FROM: payment_stub.py (original)
  # IMPORTS FROM: bm_logger.py (original)
## Constraints
- Do not change the prompt text inside ask_marina_llm()
- Do not change the fallback string
- Do not change the function signature
- Do not remove the subprocess import
- Do not remove SESSION_ID
- Do not touch line 283 or the create_calendar_hold() function
- Do not touch any other file
- Do not install any new packages
- The function must always return a string — never raise
## Test commands
ANTHROPIC_API_KEY is already set as an environment variable.
Run all tests from the project root directory.
Report the exact output of each test.
# Test 1 — file imports cleanly
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
print('IMPORT OK')
"
# Test 2 — ask_marina_llm returns a non-empty string
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
result = email_poller.ask_marina_llm(
    'test@example.com',
    'Booking inquiry',
    'I want to book a sunset cruise for 4 people',
    mode='general'
)
print('Result type:', type(result).__name__)
print('Result preview:', result[:100])
assert isinstance(result, str), 'FAIL: not a string'
assert len(result) > 0, 'FAIL: empty result'
print('PASS')
"
# Test 3 — fallback string returned on bad API key
ANTHROPIC_API_KEY=bad_key python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
result = email_poller.ask_marina_llm(
    'test@example.com',
    'test subject',
    'test body',
    mode='general'
)
print('Fallback result:', result)
assert 'preferred date' in result, f'FAIL: fallback not used, got: {result!r}'
print('PASS — fallback confirmed')
"
# Test 4 — confirm openclaw is gone from ask_marina_llm
python3 -c "
with open('bluemarlin/src/email_poller.py') as f:
    content = f.read()
assert 'openclaw' not in ''.join(open('bluemarlin/src/email_poller.py').read().split('def ask_marina_llm')[1].split('def ')[0]), 'FAIL: openclaw in ask_marina_llm body'
assert 'claude_client' in content, 'FAIL: claude_client not found'
print('PASS — openclaw removed, claude_client present')
"
# Test 5 — subprocess import still present (needed for calendar.js)
python3 -c "
with open('bluemarlin/src/email_poller.py') as f:
    content = f.read()
assert 'subprocess' in content, 'FAIL: subprocess removed from file'
print('PASS — subprocess still present for calendar.js')
"
## Definition of done
- [ ] email_poller.py modified in bluemarlin/src/
- [ ] File header added or updated at top (Brief 005)
- [ ] claude_client imported in email_poller.py
- [ ] ask_marina_llm() uses claude_client.complete() not subprocess
- [ ] subprocess import still present
- [ ] SESSION_ID still present
- [ ] All 5 tests pass with exact output shown
- [ ] OUTPUT_005.md written to bluemarlin/briefs/
- [ ] OUTPUT_005.md includes SYSTEM_STATE update block
- [ ] OUTPUT_005.md includes dependency impact block
- [ ] OUTPUT_005.md includes regression check block
