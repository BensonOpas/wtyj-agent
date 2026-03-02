# OUTPUT 001 — claude_client.py

## Files created or modified
- `bluemarlin/src/claude_client.py` — created (Brief 001)

## Assumptions made
- `anthropic` package was not pre-installed; installed via `pip3 install anthropic --break-system-packages`
- The model ID `claude-sonnet-4-20250514` is used exactly as specified in the brief
- `extract()` delegates to `complete()` internally; if `complete()` returns `""`, `extract()` returns `{}`
- Markdown fence stripping handles both ` ```json ` and bare ` ``` ` variants

## Dependencies added
- `anthropic` (PyPI) — installed with `pip3 install anthropic --break-system-packages`

## Test results

### Test 1 — imports cleanly
```
Command: python3 -c "import sys; sys.path.insert(0, 'bluemarlin/src'); import claude_client; print('IMPORT OK')"
Output:  IMPORT OK
```

### Test 2 — complete() returns a string
```
Command: ANTHROPIC_API_KEY=<key> python3 -c "... claude_client.complete('Reply with exactly: HELLO') ..."
Output:
  complete() result: HELLO
  PASS
```

### Test 3 — extract() returns a dict
```
Command: ANTHROPIC_API_KEY=<key> python3 -c "... claude_client.extract('Return this exact JSON: {\"test\": true}') ..."
Output:
  extract() result: {'test': True}
  PASS
```

### Test 4 — fails gracefully with bad key
```
Command: ANTHROPIC_API_KEY=bad_key python3 -c "... complete('test') ... extract('test') ..."
Output:  PASS — graceful failure confirmed
```

## Flags / uncertainties
- None. All tests passed on first run.

## SYSTEM_STATE update
Brief 001 — claude_client.py — New file created; exposes `complete()` and `extract()` wrapping the Anthropic API — Callers must set `ANTHROPIC_API_KEY` env var; both functions fail silently (return `""` / `{}`) on any error.

## Dependency impact
Files that import claude_client: (none yet — marina_extractor.py and social_drafter.py still use OpenClaw; migration is out of scope for this brief)
What callers should expect differently: N/A (no existing callers)

## Regression check
# BRIEF_001 — claude_client.py — verifies import, complete(), extract(), graceful failure
# Tests: claude_client.py
python3 -c "import sys; sys.path.insert(0, 'bluemarlin/src'); import claude_client; print('IMPORT OK')"
ANTHROPIC_API_KEY=bad_key python3 -c "import sys; sys.path.insert(0, 'bluemarlin/src'); import claude_client; assert claude_client.complete('test') == ''; assert claude_client.extract('test') == {}; print('GRACEFUL FAIL OK')"
