# OUTPUT 036 — Marina prompt bug fixes: language body-only, day-of-week validation, reply_hold_failed scope

## What was done

1. **Fix 1 — Language detection (strengthened beyond brief):** Initial patch ("from the body text only, do not infer from sender's name") was insufficient — S11 (Hans Müller, English body) still replied in Dutch. Strengthened to an explicit rule: "If the body is written in English, your reply MUST be in English — even if the sender has a German, Dutch, or other non-English name." Verified fixed: S11 now replies "Hi Hans!" in English.

2. **Fix 2 — Day-of-week validation before booking summary:** Added FIRST step to BOOKING CONFIRMATION BEHAVIOUR — instructs Marina to check the trip's days_available field before sending a summary. If the date doesn't match, do NOT set awaiting_booking_confirmation and do NOT send a booking summary. S7 (Thursday, west_coast_beach): flags now empty (no hold will be attempted). Marina still shows trip info but adds a caveat about operating days — acceptable UX. The critical fix (no confirmation flag, no hold) is working.

3. **Fix 3 — reply_hold_failed scope:** Changed from "Write this field whenever..." to "Write this field ONLY when you are setting awaiting_booking_confirmation to true OR booking_confirmed to true in your current JSON response." S8 (large group escalation): reply_hold_failed is now absent.

4. **File header updated** — `# LAST MODIFIED: Brief 036`

5. **SYSTEM_STATE.md Decision Log** — Brief 036 entry appended.

## Test results
```
T1 pass — LANGUAGE RULE specifies body text
T2 pass — LANGUAGE RULE addresses non-English names
T3 pass — days_available validation present in prompt
T4 pass — day-of-week validation block present in prompt
T5 pass — reply_hold_failed scoped with 'ONLY when'
T6 pass — reply_hold_failed exclusion of non-booking paths present
T7 pass — file header updated to Brief 036

All 7 tests passed.
```

## Manual verification results
- **S7 (Thursday, west_coast_beach):** flags={} — no awaiting_booking_confirmation, no hold will be attempted. ✅
- **S11 (English body, Hans Müller):** Reply starts "Hi Hans!" in English. ✅
- **S8 (20 people, escalation):** reply_hold_failed: False — not generated. ✅

## Unexpected findings
Fix 1 required two iterations. The first patch ("Do not infer language from the sender's name") was not strong enough — Claude still picked up Dutch from the name "Müller." The instruction was strengthened to an explicit MUST rule with a named example of German/Dutch names. Second iteration resolved the bug.

## Status
7/7 tests pass. All 3 bugs confirmed fixed via manual re-run. Brief executed as written with one in-scope prompt strengthening on Fix 1.
