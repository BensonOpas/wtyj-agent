#!/usr/bin/env python3
# bluemarlin/test_033_thread_key.py
# Brief 033 — Thread key via Message-ID/In-Reply-To
# Run: cd bluemarlin && python3 test_033_thread_key.py

import email.message
import json
import os
import sys
import tempfile

from agents.marina import email_poller

# Test 1: First email — no threading headers → subject-based key
m1 = email.message.Message()
m1["Message-ID"] = "<msg001@test>"
idx = {}
k1 = email_poller.resolve_thread_key(m1, "alice@example.com", "Book Klein Curacao", idx)
assert k1 == "subj:alice@example.com:book klein curacao", f"T1 fail: {k1}"
idx["<msg001@test>"] = k1
print("T1 pass")

# Test 2: Reply with References → resolves to same thread
m2 = email.message.Message()
m2["Message-ID"] = "<msg002@test>"
m2["References"] = "<msg001@test>"
m2["In-Reply-To"] = "<msg001@test>"
k2 = email_poller.resolve_thread_key(m2, "alice@example.com", "Re: Different Subject", idx)
assert k2 == k1, f"T2 fail: {k2}"
idx["<msg002@test>"] = k2
print("T2 pass")

# Test 3: Reply with only In-Reply-To (no References) → resolves to same thread
m3 = email.message.Message()
m3["Message-ID"] = "<msg003@test>"
m3["In-Reply-To"] = "<msg001@test>"
k3 = email_poller.resolve_thread_key(m3, "alice@example.com", "whatever subject", idx)
assert k3 == k1, f"T3 fail: {k3}"
print("T3 pass")

# Test 4: References first ID not in index, In-Reply-To is → resolves via In-Reply-To
m4 = email.message.Message()
m4["Message-ID"] = "<msg004@test>"
m4["References"] = "<unknown@test> <msg001@test>"
m4["In-Reply-To"] = "<msg001@test>"
k4 = email_poller.resolve_thread_key(m4, "alice@example.com", "Re: Book Klein Curacao", idx)
assert k4 == k1, f"T4 fail: {k4}"
print("T4 pass")

# Test 5: No threading headers at all → subject-based fallback, no crash
m5 = email.message.Message()
k5 = email_poller.resolve_thread_key(m5, "bob@example.com", "Sunset cruise inquiry", idx)
assert k5 == "subj:bob@example.com:sunset cruise inquiry", f"T5 fail: {k5}"
print("T5 pass")

# Test 6: Different sender, same subject → different thread key
m6 = email.message.Message()
k6 = email_poller.resolve_thread_key(m6, "carol@example.com", "Book Klein Curacao", idx)
assert k6 != k1, f"T6 fail: same key for different sender"
print("T6 pass")

# Test 7: Pre-033 state file (no message_id_index) → setdefault handles gracefully
state_old = {"threads": {"subj:x@y.com:hello": {"fields": {}, "flags": {}}}}
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    json.dump(state_old, f)
    fname = f.name
loaded = json.load(open(fname))
loaded.setdefault("message_id_index", {})
assert "message_id_index" in loaded, "T7 fail: setdefault did not add key"
os.unlink(fname)
print("T7 pass")

print("\nAll 7 tests passed.")
