# OUTPUT 043 — Fix relay detection + poisoned relay bug

## What was done

### Step 1 — Added `from email.header import decode_header as _decode_header` import
### Step 2 — Added `_decode_subj()` helper before `log()` in helpers section
### Step 3 — Changed `subj = msg.get("Subject", "") or ""` to `subj = _decode_subj(msg.get("Subject", ""))`
### Step 4a — Fully escalated guard: creates `_esc_flags` copy with relay keys stripped before calling marina_agent
### Step 4b — Step 1: creates `agent_flags` copy with relay keys stripped before calling marina_agent
### Step 5 — Updated file header to Brief 043

## Test results

```
Running Brief 043 tests...
  T1 PASS: RFC 2047 subject decoded correctly
         raw:     '[RELAY-d820b609f103] NO-REF - Unknown'
         decoded: '[RELAY-d820b609f103] NO-REF - Unknown'
  T2 PASS: plain ASCII subjects pass through unchanged
  T3 PASS: relay detection matches on decoded RFC 2047 subject
  T4 PASS: escalation guard matches on decoded RFC 2047 subject
  T5 PASS: Step 1 call site strips relay flags from marina_agent input
  T6 PASS: fully_escalated guard strips relay flags from marina_agent input

All 6 tests passed.
```

## Unexpected

T5 test initially failed because the assertion checked for `th.get("flags", {})` anywhere in the Step 1 block — but it appears in the `dict()` wrapper line `agent_flags = dict(th.get("flags", {}))` which is correct usage. Fixed the assertion to check within the `process_message` call section specifically.
