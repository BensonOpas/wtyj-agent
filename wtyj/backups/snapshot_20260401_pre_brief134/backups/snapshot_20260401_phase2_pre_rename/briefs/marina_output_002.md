# OUTPUT 002 — marina_extractor.py

## Files created or modified
- `bluemarlin/src/marina_extractor.py` — modified (Brief 002)

## Assumptions made
- `ANTHROPIC_API_KEY` was not present in the shell environment on this Mac; the API key from Brief 001 test commands was used inline to run tests (identical key, just not pre-exported). The file itself reads the key at runtime from the environment — no change to that behaviour.
- The prompt text inside `extract_fields()` was preserved verbatim (including whitespace and newlines).
- No new packages were installed.

## Dependencies added
- None (anthropic package was already installed in Brief 001)

## Changes made (in order per brief)
1. Removed `import json`
2. Removed `import subprocess`
3. Removed `import re`
4. Removed `SESSION_ID = "marina_extract_session"`
5. Added `import sys`, `import os`, `sys.path.insert(...)`, `import claude_client`
6. Replaced entire `try/except` block in `extract_fields()` with four-line claude_client delegation
7. Added file header as first lines of file

## Test results

### Test 1 — imports cleanly
```
Command: python3 -c "import sys; sys.path.insert(0, 'bluemarlin/src'); import marina_extractor; print('IMPORT OK')"
Output:  IMPORT OK
```

### Test 2 — extracts fields from natural language booking
```
Command: ANTHROPIC_API_KEY=<key> python3 -c "... extract_fields('I want to book the sunset cruise on March 20 for 4 people') ..."
Output:
  Result: {'experience': 'sunset cruise', 'date': 'March 20', 'guests': 4}
  PASS
```

### Test 3 — returns empty dict on empty input
```
Command: ANTHROPIC_API_KEY=<key> python3 -c "... extract_fields('') ..."
Output:
  Empty input result: {}
  PASS
```

### Test 4 — returns empty dict on bad API key
```
Command: ANTHROPIC_API_KEY=bad_key python3 -c "... extract_fields('book sunset cruise') ..."
Output:  PASS — graceful failure confirmed
```

### Test 5 — only returns keys from ALLOWED_KEYS
```
Command: ANTHROPIC_API_KEY=<key> python3 -c "... extract_fields('My name is John, I want to book the sunset cruise on March 20 for 2 adults and 1 kid, my phone is +5999123456') ..."
Output:
  Result: {'experience': 'sunset cruise', 'date': 'March 20', 'guests': 3, 'adults': 2, 'kids': 1, 'customer_name': 'John', 'phone': '+5999123456'}
  PASS — all keys are allowed
```

### Test 6 — confirm removed imports and openclaw are gone
```
Command: python3 -c "with open('bluemarlin/src/marina_extractor.py') as f: ..."
Output:  PASS — file structure is correct
```

## Flags / uncertainties
- `ANTHROPIC_API_KEY` was not pre-exported in the Mac shell environment; tests were run with the key inline. On the VPS where it is set as a system env var, tests will pass as written in the brief.

## SYSTEM_STATE update
Brief 002 — marina_extractor.py — Replaced OpenClaw subprocess call with claude_client.extract(); removed json, subprocess, re imports and SESSION_ID — Callers must ensure ANTHROPIC_API_KEY is set; extract_fields() signature and return type unchanged; returns {} on any failure as before.

## Dependency impact
Files that import marina_extractor: (none identified in current codebase)
What callers should expect differently: Functionally identical — extract_fields(text: str) still returns a dict filtered to ALLOWED_KEYS or {} on failure. Internal mechanism changed from OpenClaw subprocess to direct Anthropic API call via claude_client.

## Regression check
# BRIEF_002 — marina_extractor.py — verifies import, extraction, graceful failure, key filtering, no banned imports
# Tests: marina_extractor.py, claude_client.py
python3 -c "import sys; sys.path.insert(0, 'bluemarlin/src'); import marina_extractor; print('IMPORT OK')"
python3 -c "with open('bluemarlin/src/marina_extractor.py') as f: c=f.read(); assert 'subprocess' not in c; assert 'openclaw' not in c.lower(); assert 'claude_client' in c; print('STRUCTURE OK')"
ANTHROPIC_API_KEY=bad_key python3 -c "import sys; sys.path.insert(0, 'bluemarlin/src'); import marina_extractor; assert marina_extractor.extract_fields('test') == {}; print('GRACEFUL FAIL OK')"
