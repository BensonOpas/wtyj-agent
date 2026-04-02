# OUTPUT 003 — social_drafter.py

## Files created or modified
- `bluemarlin/src/social_drafter.py` — modified (Brief 003)

## Assumptions made
- `ANTHROPIC_API_KEY` is not pre-exported in the Mac shell environment; tests requiring a real key were run with the key inline (same key used in Briefs 001/002).
- The `# Uses the same OpenClaw session as the rest of the demo` comment above SESSION_ID was removed along with SESSION_ID, as it referred only to the SESSION_ID line.
- No new packages were installed.

## Dependencies added
- None.

## Changes made (in order per brief)
1. Removed `import subprocess`
2. Kept `import sys` and `import json` (used by `__main__` block)
3. Kept `import social_registry`
4. Removed `SESSION_ID = "c5613944-cb20-4c34-941e-fd0e53f70494"` (and its comment)
5. Added `import os`, `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))`, `import claude_client`
6. Replaced 4-line `subprocess.run(...)` + `text = (r.stdout or "").strip()` with `text = claude_client.complete(prompt)`; fallback string unchanged
7. Added file header as first lines of file

## Test results

### Test 1 — imports cleanly
```
Command: python3 -c "import sys; sys.path.insert(0, 'bluemarlin/src'); import social_drafter; print('IMPORT OK')"
Output:  IMPORT OK
```

### Test 2 — draft_post returns dict with expected keys
```
Command: ANTHROPIC_API_KEY=<key> python3 -c "... draft_post('instagram', 'A sunset cruise hold was just created for 4 guests on March 20') ..."
Output:
  Result keys: ['content_id', 'platform', 'text', 'status', 'created_at', 'approved_at', 'posted_at', 'platform_post_id', 'meta']
  Platform: instagram
  Status: draft
  Text preview: Just secured a sunset cruise hold for 4 guests on March 20th! 🌅 There's somethin
  PASS
```

### Test 3 — fallback text used when API key is bad
```
Command: ANTHROPIC_API_KEY=bad_key python3 -c "... draft_post('instagram', 'test context') ..."
Output:
  Fallback text: BlueMarlin Tours Curaçao — private charters available. DM us or email hello@wetakeyourjob.com
  PASS — fallback confirmed
```

### Test 4 — idempotency: same platform+context returns same content_id
```
Command: ANTHROPIC_API_KEY=<key> python3 -c "... draft_post('facebook', ...) x2, assert content_id equal ..."
Output:
  AssertionError: FAIL: content_id differs
  FAIL
```
**Root cause:** `content_id` in `social_registry.py` is a SHA-256 hash of `platform|text`. The LLM generates non-deterministic text on each call, so two calls with the same context produce different text → different hashes → different `content_id` values. The test assumes idempotency but the registry's idempotency gate is keyed on generated text, not on input context. This is a design-level issue. The implementation in this brief is correct per Steps 1–7 — no step adds context-based caching, and the brief constraints prohibit touching `social_registry.py`.

### Test 5 — confirm subprocess and openclaw are gone
```
Command: python3 -c "with open('bluemarlin/src/social_drafter.py') as f: ..."
Output:  PASS — file structure is correct
```

## Flags / uncertainties
- **Test 4 FAILS** — not an implementation bug. The `content_id` idempotency relies on identical LLM output across calls, which is not guaranteed. To fix Test 4 the system would need to either: (a) key drafts on input context rather than output text, or (b) cache the first LLM response per (platform, context) before hashing. Both require a change to `social_registry.py` or new logic in `draft_post()` — neither is within scope of this brief.
- `ANTHROPIC_API_KEY` not pre-exported on Mac; tests run with key inline.

## SYSTEM_STATE update
Brief 003 — social_drafter.py — Replaced OpenClaw subprocess call with `claude_client.complete()`; removed `import subprocess` and `SESSION_ID`; all other logic unchanged — Callers must ensure `ANTHROPIC_API_KEY` is set; `draft_post(platform, context) -> dict` signature and return shape unchanged; returns fallback-text draft on API failure.

## Dependency impact
Files that import social_drafter: (none identified in current codebase)
What callers should expect differently: Functionally identical — `draft_post()` still returns a dict from `social_registry.create_draft()`. Internal mechanism changed from OpenClaw subprocess to direct Anthropic API call via `claude_client.complete()`.

## Regression check
# BRIEF_003 — social_drafter.py — verifies import, draft shape, fallback, no banned imports
# Tests: social_drafter.py, claude_client.py, social_registry.py
python3 -c "import sys; sys.path.insert(0, 'bluemarlin/src'); import social_drafter; print('IMPORT OK')"
python3 -c "with open('bluemarlin/src/social_drafter.py') as f: c=f.read(); assert 'subprocess' not in c; assert 'SESSION_ID' not in c; assert 'openclaw' not in c.lower(); assert 'claude_client' in c; print('STRUCTURE OK')"
ANTHROPIC_API_KEY=bad_key python3 -c "import sys; sys.path.insert(0, 'bluemarlin/src'); import social_drafter; r=social_drafter.draft_post('instagram','test'); assert 'BlueMarlin Tours' in r.get('text',''); assert r.get('status')=='draft'; print('FALLBACK OK')"
