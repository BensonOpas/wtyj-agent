# OUTPUT 033 — Thread Key via Message-ID/In-Reply-To

## What was done
- `email_poller.py`: `stable_thread_key()` replaced with `resolve_thread_key()` — checks `References` (first ID) then `In-Reply-To` against a `message_id_index` before falling back to `sender+subject`
- `email_poller.py`: state load updated to include `message_id_index: {}` in default; `setdefault` added for backward-compat
- `email_poller.py`: call site updated — resolves thread key then stores inbound `Message-ID → thread_key` in index
- `email_poller.py`: file header updated to Brief 033
- `SYSTEM_STATE.md`: Brief 033 Decision Log entry appended

## Test results
All 7 tests passed.
1. First email (no threading headers) → subject-based key ✓
2. Reply with References → same thread ✓
3. Reply with In-Reply-To only → same thread ✓
4. References first ID unknown, In-Reply-To known → resolves via In-Reply-To ✓
5. No headers at all → subject-based fallback, no crash ✓
6. Different sender, same subject → different thread key ✓
7. Pre-033 state file (no message_id_index) → setdefault handles gracefully ✓

## Unexpected
Nothing unexpected. The change is minimal and self-contained.
