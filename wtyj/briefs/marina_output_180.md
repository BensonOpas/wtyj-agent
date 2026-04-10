# OUTPUT 180 — Prompt hardening: date verification, language matching, cancellation ref echo

## What was done

Three prompt-text insertions into `_build_system_prompt`'s template string in `marina_agent.py`, no Python logic changes: (1) date verification rule after the DATE AMBIGUITY RESOLUTION block — "verify that any weekday you state matches the calendar date" with explicit instruction to omit the weekday rather than risk a mismatch; (2) language matching sharpening — replaced the old "fall back to English if too short" phrasing with explicit "always match the MOST RECENT customer message, even if earlier turns were in a different language"; (3) cancellation ref echo in the ESCALATION BEHAVIOUR section — "when a booking reference is known, always echo it in your reply."

## Tests

850 passing / 0 failures (847 baseline + 3 new).

## Deployment

Source committed `b822522`, pushed to main. Background deploy to all three containers.
