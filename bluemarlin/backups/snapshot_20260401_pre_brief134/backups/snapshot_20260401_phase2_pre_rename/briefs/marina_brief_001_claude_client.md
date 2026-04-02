# BRIEF 001 — claude_client.py
# Read CODEX_CONTEXT.md before executing this brief
## Objective
Create claude_client.py — a clean wrapper around the Anthropic
API that replaces all OpenClaw subprocess calls in this project.
## Context
Currently marina_extractor.py and social_drafter.py call OpenClaw
via subprocess. This file replaces that entirely. Nothing else
changes in this brief — only this new file is created.
## File to create
bluemarlin/src/claude_client.py
## What this file must do
Expose two functions:
1. complete(prompt: str, system: str = None) -> str
   - Calls Anthropic API with the given prompt
   - Returns the response text as a plain string
   - Returns empty string "" on any failure
   - Never raises exceptions — always fails gracefully
2. extract(prompt: str) -> dict
   - Calls Anthropic API expecting a JSON response
   - Parses and returns the JSON as a dict
   - Returns empty dict {} on any failure — never raises
   - Strips any markdown code fences before parsing
## API details
Package: anthropic
Client: anthropic.Anthropic(api_key=...)
Method: client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1000,
    messages=[{"role": "user", "content": prompt}]
)
With system prompt: add system="..." parameter
## API key
Read from environment variable: ANTHROPIC_API_KEY
Do not hardcode. Do not read from file.
## Allowed dependencies
anthropic (install with: pip install anthropic --break-system-packages)
## Rules
- No other dependencies
- No global state
- No retries — fail fast and return empty
- File must be importable with no side effects on import
## Test commands
Run these after creating the file and report exact output:
# Test 1 — imports cleanly
python3 -c "import sys; sys.path.insert(0, 'bluemarlin/src'); import claude_client; print('IMPORT OK')"
# Test 2 — complete() returns a string
ANTHROPIC_API_KEY=YOUR_ANTHROPIC_API_KEY python3 -c "
import sys; sys.path.insert(0, 'bluemarlin/src')
import claude_client
result = claude_client.complete('Reply with exactly: HELLO')
print('complete() result:', result)
assert isinstance(result, str) and len(result) > 0, 'FAIL: empty result'
print('PASS')
"
# Test 3 — extract() returns a dict
ANTHROPIC_API_KEY=YOUR_ANTHROPIC_API_KEY python3 -c "
import sys; sys.path.insert(0, 'bluemarlin/src')
import claude_client
result = claude_client.extract('Return this exact JSON: {\"test\": true}')
print('extract() result:', result)
assert isinstance(result, dict), 'FAIL: not a dict'
print('PASS')
"
# Test 4 — fails gracefully with bad key
ANTHROPIC_API_KEY=bad_key python3 -c "
import sys; sys.path.insert(0, 'bluemarlin/src')
import claude_client
result = claude_client.complete('test')
assert result == '', f'FAIL: expected empty string, got {result!r}'
result2 = claude_client.extract('test')
assert result2 == {}, f'FAIL: expected empty dict, got {result2!r}'
print('PASS — graceful failure confirmed')
"
## Definition of done
- [ ] claude_client.py exists in bluemarlin/src/
- [ ] File has correct header comment
- [ ] All 4 tests pass
- [ ] OUTPUT_001.md written to bluemarlin/briefs/
