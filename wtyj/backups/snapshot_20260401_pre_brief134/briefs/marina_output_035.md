# OUTPUT 035 — Marina prompt polish: language adaptation + trip key mapping

## What was done

1. **LANGUAGE block added to marina_agent.py prompt** — new line after PERSONA: instructs Marina to detect the customer's inbound language and reply in kind, listing supported languages (English, Dutch, German, Spanish, Portuguese), defaulting to English if unclear.

2. **Trip key mapping table added to prompt** — expanded the `trip_key` field description in the JSON spec from a bare list of 5 keys to a 5-entry mapping table with common customer phrasings → exact key (e.g. "snorkeling", "snorkel", "3-in-1" → snorkeling_3in1).

3. **File header updated** — `# LAST MODIFIED: Brief 031` → `# LAST MODIFIED: Brief 035`

4. **CLAUDE.md Active Source Files table updated** — marina_agent.py brief column: 031 → 035

5. **CLAUDE.md Known Open Issues updated** — removed 3 resolved items (thread key, [VERIFY] items, payment_stub). Added formal accepted-exception entry for fallback reply string. 5 entries remain.

6. **SYSTEM_STATE.md Decision Log updated** — Brief 035 entry appended and outcome set to `complete — 9/9 tests pass`.

## Test results
```
T1 pass — LANGUAGE block present in prompt
T2 pass — language detection instruction present
T3 pass — supported languages listed
T4 pass — all 5 trip keys present in prompt
T5 pass — trip key aliases present in prompt
T6 pass — file header updated to Brief 035
T7 pass — stale thread key issue removed from CLAUDE.md
T8 pass — stale [VERIFY] issue removed from CLAUDE.md
T9 pass — all surviving known issues present in CLAUDE.md

All 9 tests passed.
```

## Unexpected findings
None. All edits applied cleanly on first attempt.

## Status
9/9 tests pass. Brief executed exactly as written.
