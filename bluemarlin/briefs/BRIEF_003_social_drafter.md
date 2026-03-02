# BRIEF 003 — social_drafter.py
# Read CODEX_CONTEXT.md before executing this brief
## Objective
Replace the OpenClaw subprocess call in social_drafter.py
with a direct call to claude_client.complete(). Surgical
change only. Behavior stays identical from the caller's
perspective. No other files touched.
## Context
social_drafter.py currently calls OpenClaw via subprocess.run()
to generate social media post text.
claude_client.py was created in Brief 001 and exposes complete()
which returns plain text from the Anthropic API directly.
The prompt text does not change. Only the execution mechanism changes.
social_registry.py is not touched in this brief.
## Files to read before making changes
bluemarlin/src/claude_client.py
bluemarlin/src/social_registry.py
## File to modify
bluemarlin/src/social_drafter.py
## Current behavior
draft_post(platform, context) builds a prompt string, passes it
to OpenClaw via subprocess.run(), reads stdout as plain text,
falls back to a hardcoded string if stdout is empty, then calls
social_registry.create_draft() and returns the resulting dict.
## Required behavior after this change
draft_post(platform, context) builds the exact same prompt string,
passes it to claude_client.complete(prompt), uses the result as
plain text, falls back to the same hardcoded string if the result
is empty string "", then calls social_registry.create_draft() and
returns the resulting dict.
The function signature does not change.
The prompt text does not change.
The fallback string does not change.
The return type does not change — still a dict from create_draft().
## Changes required — follow this order exactly
STEP 1
Remove this import from the top of the file:
  import subprocess
STEP 2
Keep these imports exactly as they are — both are used
in the __main__ block at the bottom of the file:
  import sys
  import json
STEP 3
Keep this import exactly as it is:
  import social_registry
STEP 4
Remove this line:
  SESSION_ID = "c5613944-cb20-4c34-941e-fd0e53f70494"
STEP 5
Add these three lines after the remaining imports,
before the SESSION_ID line being removed:
  import os
  sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
  import claude_client
STEP 6
Inside draft_post(), remove these four lines:
  r = subprocess.run(
      ["openclaw", "agent", "--session-id", SESSION_ID, "--message", prompt, "--local"],
      capture_output=True, text=True, timeout=120
  )
  text = (r.stdout or "").strip()
Replace them with exactly this one line:
  text = claude_client.complete(prompt)
The fallback line that follows stays exactly as it is:
  if not text:
      text = "BlueMarlin Tours Curaçao — private charters available. DM us or email hello@wetakeyourjob.com"
STEP 7
Add this file header as the very first lines of the file,
before any imports:
  # FILE: social_drafter.py
  # CREATED: Before Brief 001 (original codebase)
  # LAST MODIFIED: Brief 003
  # DEPENDS ON: claude_client.py (Brief 001)
  # DEPENDS ON: social_registry.py (original)
  # IMPORTS FROM: claude_client.py (Brief 001)
  # IMPORTS FROM: social_registry.py (original)
## Known pre-existing issue — do not fix in this brief
social_registry.py uses SOCIAL_STATE_FILE = "social_state.json"
as a bare filename with no path. This resolves relative to
whatever the working directory is at runtime. This is a known
issue logged for a future brief. Do not touch it here.
## Constraints
- Do not change the prompt text inside draft_post()
- Do not change the fallback string
- Do not change the function signature draft_post(platform, context)
- Do not change the __main__ block at the bottom
- Do not touch social_registry.py
- Do not install any new packages
- The function must always return a dict — never raise an exception
## Test commands
ANTHROPIC_API_KEY is already set as an environment variable.
Run all tests from the project root directory.
Report the exact output of each test.
# Test 1 — file imports cleanly with no errors
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import social_drafter
print('IMPORT OK')
"
# Test 2 — draft_post returns a dict with expected keys
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import social_drafter
result = social_drafter.draft_post(
    'instagram',
    'A sunset cruise hold was just created for 4 guests on March 20'
)
print('Result keys:', list(result.keys()))
print('Platform:', result.get('platform'))
print('Status:', result.get('status'))
print('Text preview:', (result.get('text') or '')[:80])
required_keys = {'content_id','platform','text','status','created_at'}
assert required_keys.issubset(result.keys()), f'FAIL: missing keys'
assert result.get('platform') == 'instagram', 'FAIL: wrong platform'
assert result.get('status') == 'draft', 'FAIL: wrong status'
assert len(result.get('text','')) > 0, 'FAIL: empty text'
print('PASS')
"
# Test 3 — fallback text used when API key is bad
ANTHROPIC_API_KEY=bad_key python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import social_drafter
result = social_drafter.draft_post('instagram', 'test context')
print('Fallback text:', result.get('text'))
assert 'BlueMarlin Tours' in result.get('text',''), 'FAIL: fallback text not used'
assert result.get('status') == 'draft', 'FAIL: wrong status'
print('PASS — fallback confirmed')
"
# Test 4 — same platform+context returns same content_id (idempotent)
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import social_drafter
result1 = social_drafter.draft_post('facebook', 'unique test context for idempotency check')
result2 = social_drafter.draft_post('facebook', 'unique test context for idempotency check')
assert result1.get('content_id') == result2.get('content_id'), 'FAIL: content_id differs'
print('PASS — idempotent draft confirmed')
"
# Test 5 — confirm subprocess and openclaw are gone from the file
python3 -c "
with open('bluemarlin/src/social_drafter.py') as f:
    content = f.read()
assert 'subprocess' not in content, 'FAIL: subprocess still present'
assert 'SESSION_ID' not in content, 'FAIL: SESSION_ID still present'
assert 'openclaw' not in content.lower(), 'FAIL: openclaw reference still present'
assert 'claude_client' in content, 'FAIL: claude_client not found in file'
print('PASS — file structure is correct')
"
## Definition of done
- [ ] social_drafter.py modified in bluemarlin/src/
- [ ] File header added at top (Brief 003)
- [ ] import subprocess removed
- [ ] SESSION_ID removed
- [ ] claude_client imported and used in draft_post()
- [ ] Fallback string preserved exactly
- [ ] __main__ block unchanged
- [ ] All 5 tests pass with exact output shown
- [ ] OUTPUT_003.md written to bluemarlin/briefs/
- [ ] OUTPUT_003.md includes SYSTEM_STATE update block
- [ ] OUTPUT_003.md includes dependency impact block
- [ ] OUTPUT_003.md includes regression check block
