# BRIEF 033 — Thread Key via Message-ID/In-Reply-To
**Status:** Draft | **Files:** `src/email_poller.py`, `briefs/SYSTEM_STATE.md` | **Depends on:** Brief 032 | **Blocks:** nothing

## Context
Thread state is keyed on `sender + normalized subject` via `stable_thread_key()` (email_poller.py:163). The `msg` parameter is accepted but never used. If a customer's email client changes the subject line on reply (common on mobile apps), Marina loses all previously collected fields and starts the conversation over. Standard email threading headers (`References`, `In-Reply-To`) are already available in every inbound message and provide reliable thread continuity regardless of subject changes.

## Why This Approach
The simplest correct fix is to build a flat `message_id_index` dict (`message_id → thread_key`) stored alongside `threads` in the same state file. When a reply arrives, we check its `References` header (first ID = thread root) and `In-Reply-To` header against this index before falling back to subject-based keying. This requires no new files, no schema migration, and is fully backward-compatible — existing `"subj:..."` keys remain valid and pre-033 state files are handled by `setdefault`. Alternatives considered: storing threading data per-thread (more complex, harder to query), or using only `In-Reply-To` (misses clients that omit it but include `References`).

## Source Material

### Current `stable_thread_key` (email_poller.py:163–173)
```python
def stable_thread_key(msg, from_email: str, subject: str) -> str:
    """
    Deterministic thread key to prevent looping.

    We ALWAYS group by: sender + normalized subject.
    This avoids the "first email uses fallback, replies use refroot/irt" split-brain issue.
    """
    return "subj:{}:{}".format(
        from_email.strip().lower(),
        normalize_subject(subject).strip().lower()
    )
```

### Current call site (email_poller.py:215)
```python
thread_key = stable_thread_key(msg, from_email, subj)
```

### Current state load (email_poller.py:180)
```python
state = load_json(THREAD_STATE_PATH, {"threads": {}})
```

### Email headers available on every inbound `msg` object
- `msg.get("Message-ID")` — unique ID of this specific message
- `msg.get("References")` — space-separated chain of Message-IDs; first entry is thread root
- `msg.get("In-Reply-To")` — Message-ID of the message being replied to

## Instructions

### Step 1 — Update state load (email_poller.py:180)
Replace:
```python
state = load_json(THREAD_STATE_PATH, {"threads": {}})
```
With:
```python
state = load_json(THREAD_STATE_PATH, {"threads": {}, "message_id_index": {}})
state.setdefault("message_id_index", {})
```

### Step 2 — Replace `stable_thread_key` with `resolve_thread_key` (email_poller.py:163–173)
Replace the entire `stable_thread_key` function with:
```python
def resolve_thread_key(msg, from_email: str, subject: str, mid_index: dict) -> str:
    """
    Resolve thread key for an inbound message.
    Priority: References first-ID -> In-Reply-To -> sender+subject fallback.
    """
    refs = (msg.get("References") or "").strip()
    if refs:
        first_ref = refs.split()[0].strip()
        if first_ref in mid_index:
            return mid_index[first_ref]

    irt = (msg.get("In-Reply-To") or "").strip()
    if irt and irt in mid_index:
        return mid_index[irt]

    return "subj:{}:{}".format(
        from_email.strip().lower(),
        normalize_subject(subject).strip().lower()
    )
```

### Step 3 — Replace call site and store Message-ID (email_poller.py:215)
Replace:
```python
thread_key = stable_thread_key(msg, from_email, subj)
```
With:
```python
mid_index = state.setdefault("message_id_index", {})
thread_key = resolve_thread_key(msg, from_email, subj, mid_index)
msg_id = (msg.get("Message-ID") or "").strip()
if msg_id:
    mid_index[msg_id] = thread_key
```

### Step 4 — Update file header
Change:
```
# LAST MODIFIED: Brief 032
```
To:
```
# LAST MODIFIED: Brief 033
```

### Step 5 — Append to SYSTEM_STATE.md Decision Log
Append at the end of `briefs/SYSTEM_STATE.md`:
```
Brief 033 — Thread key via Message-ID/In-Reply-To
Decision: Replace subject-based thread keying with Message-ID index lookup. Store message_id_index in state file. Fallback to sender+subject for first messages.
Outcome: pending
```

## Tests
Write a standalone test block (can be a temporary script or added to test_marina_live.py) that constructs mock `email.message.Message` objects and asserts the following. Do NOT run against live email — test the function directly.

```python
import email.message, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
import email_poller

# Test 1: First email — no threading headers → subject-based key
m1 = email.message.Message()
m1["Message-ID"] = "<msg001@test>"
idx = {}
k1 = email_poller.resolve_thread_key(m1, "alice@example.com", "Book Klein Curacao", idx)
assert k1 == "subj:alice@example.com:book klein curacao", f"T1 fail: {k1}"
idx["<msg001@test>"] = k1

# Test 2: Reply with References → resolves to same thread
m2 = email.message.Message()
m2["Message-ID"] = "<msg002@test>"
m2["References"] = "<msg001@test>"
m2["In-Reply-To"] = "<msg001@test>"
k2 = email_poller.resolve_thread_key(m2, "alice@example.com", "Re: Different Subject", idx)
assert k2 == k1, f"T2 fail: {k2}"
idx["<msg002@test>"] = k2

# Test 3: Reply with only In-Reply-To (no References) → resolves to same thread
m3 = email.message.Message()
m3["Message-ID"] = "<msg003@test>"
m3["In-Reply-To"] = "<msg001@test>"
k3 = email_poller.resolve_thread_key(m3, "alice@example.com", "whatever subject", idx)
assert k3 == k1, f"T3 fail: {k3}"

# Test 4: References chain with first ID not in index, but In-Reply-To is → uses In-Reply-To
m4 = email.message.Message()
m4["Message-ID"] = "<msg004@test>"
m4["References"] = "<unknown@test> <msg001@test>"
m4["In-Reply-To"] = "<msg001@test>"
k4 = email_poller.resolve_thread_key(m4, "alice@example.com", "Re: Book Klein Curacao", idx)
assert k4 == k1, f"T4 fail: {k4}"

# Test 5: No threading headers at all → subject-based fallback, no crash
m5 = email.message.Message()
k5 = email_poller.resolve_thread_key(m5, "bob@example.com", "Sunset cruise inquiry", idx)
assert k5 == "subj:bob@example.com:sunset cruise inquiry", f"T5 fail: {k5}"

# Test 6: Different sender same subject → different thread key
m6 = email.message.Message()
k6 = email_poller.resolve_thread_key(m6, "carol@example.com", "Book Klein Curacao", idx)
assert k6 != k1, f"T6 fail: same key for different sender"

# Test 7: State file without message_id_index → setdefault handles gracefully
import json, tempfile, os as _os
state_old = {"threads": {"subj:x@y.com:hello": {"fields": {}, "flags": {}}}}
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump(state_old, f); fname = f.name
loaded = json.load(open(fname))
loaded.setdefault("message_id_index", {})
assert "message_id_index" in loaded, "T7 fail: setdefault did not add key"
_os.unlink(fname)

print("All 7 tests passed.")
```

## Success Condition
All 7 tests pass and a test email replied-to with a modified subject on the VPS shows the same ThreadKey in journalctl as the original message.

## Rollback
Revert `email_poller.py` to Brief 032 state via `git checkout HEAD~1 -- bluemarlin/src/email_poller.py`. The `message_id_index` key in `email_thread_state.json` is harmless and does not need to be removed.
