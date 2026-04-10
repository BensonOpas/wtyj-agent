# BRIEF 180 — Prompt hardening: date verification, language matching, cancellation ref echo
**Status:** Draft | **Files:** `wtyj/agents/marina/marina_agent.py` (prompt text only), new `wtyj/tests/marina/test_180_prompt_hardening.py` | **Depends on:** Brief 175 (date disambiguation), Brief 178 (cross-channel rule) | **Blocks:** None

## Context

Three findings from the 2026-04-09 e2e test that are all prompt-level fixes — no Python logic changes, just text additions/modifications inside `_build_system_prompt`'s template string.

1. **Dutch date drift (Finding 1).** Marina said "aanstaande zondag (13 april)" when April 12 was the correct Sunday. The field extraction was right (`date: 2026-04-12`) but the reply text had the wrong date. The DATE AMBIGUITY RESOLUTION block (`marina_agent.py:527-535`) tells Marina to state her interpretation but has no instruction to VERIFY the weekday matches the date.

2. **Language matching inconsistency (Finding 2).** Marina stayed in Dutch when the user switched to English mid-conversation. The LANGUAGE RULE (`marina_agent.py:317-326`) says "match the customer's language" and has a fallback for short messages: "use the language from the previous turn." Loophole: Marina can interpret this as "use the thread's established language" even for full-length messages that switch language.

3. **Cancellation doesn't echo booking ref (Finding 6).** When a customer requests cancellation mid-conversation, Marina's reply doesn't include the booking reference that's being cancelled. The ESCALATION BEHAVIOUR section (`marina_agent.py:580-606`) has no instruction to echo the ref, but it IS accessible in `thread_flags.booking_ref`.

## Why This Approach

All three are prompt text additions — the cheapest and lowest-risk category of change. No new Python logic, no schema changes, no API changes. The alternative (writing Python post-processing to validate date consistency, force language detection, or inject booking refs) would violate Rule 2 (Python routes, Claude understands) and add unnecessary complexity.

## Instructions

### Step 1: Date verification rule

In the `_build_system_prompt` template string, after the existing "Do NOT resolve ambiguity silently..." paragraph (line 533) and before the "If the date phrase is so vague..." paragraph (line 535), insert:

```
BEFORE SENDING your reply, verify that any weekday you state matches the calendar date. If you write "zondag 12 april", confirm April 12 is actually a Sunday. If you write "Saturday April 18", confirm April 18 is actually a Saturday. If you cannot verify the match, omit the weekday and write only the date (e.g. "12 april" instead of "zondag 12 april"). A wrong weekday-date pair is worse than no weekday at all.
```

### Step 2: Language matching sharpening

In `_build_system_prompt`, replace the LANGUAGE RULE block at `marina_agent.py:317-326`. The current text ends with:
```
"do not count. Read the body text only. Only fall back to English if "
"the body is actually in English or is too short to identify (e.g. just "
'"ok" or "yes" — use the language from the previous turn).'
```

Replace with:
```
"do not count. Read the body text only.\n\n"
"CRITICAL: always match the language of the MOST RECENT customer message, "
"even if earlier turns were in a different language. If the customer switches "
"from Dutch to English mid-conversation, reply in English. If they switch back "
"to Dutch, reply in Dutch. Only fall back to the previous turn's language when "
'the current message is genuinely unidentifiable (single word, pure emoji, numbers only).'
```

### Step 3: Cancellation ref echo

In the ESCALATION BEHAVIOUR section, after the line "In both cases: do NOT attempt to resolve the issue yourself." (`marina_agent.py:606`), insert:

```
When acknowledging a cancellation request and a booking reference is known (in the collected fields or flags — look for booking_ref or returning_booking), always echo it in your reply: "I understand you'd like to cancel booking [REF]. I'm escalating this to the team right away." Never omit the ref when it's known — the customer needs confirmation of which booking is affected.
```

## Tests

Create `wtyj/tests/marina/test_180_prompt_hardening.py`:

1. **Date verification rule is in the system prompt.** Build the prompt, assert it contains `"verify that any weekday you state matches the calendar date"`.

2. **Language rule says MOST RECENT.** Build the prompt, assert it contains `"MOST RECENT customer message"` and does NOT contain the old `"Only fall back to English if"` phrasing.

3. **Cancellation ref echo rule is in the system prompt.** Build the prompt, assert it contains `"cancel booking"` and `"Never omit the ref"`.

## Success Condition

847 baseline + 3 new tests = **850 passing / 0 failures**. System prompt now instructs Marina to verify weekday-date matches, match the most recent message's language, and echo booking refs on cancellation.

## Rollback

`git revert <commit>`, deploy. Restores previous prompt wording. No data change, no schema change.
