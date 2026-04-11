# OUTPUT 184 — Allow semi-escalation from fully-escalated conversations

## What was done

Added semi-escalation and re-escalation detection to the fully-escalated guard in `social_agent.py:222-242`. After `marina_agent.process_message()` returns in the escalated path, the code now checks `esc_result.get("semi_escalation")` and `esc_result.get("requires_human")` (both top-level keys, not inside the flags dict). If semi_escalation is true, creates a relay notification with the relay question so the operator sees it in the dashboard. If requires_human is true (and not semi), creates a full escalation notification. Previously, the guard returned the reply directly without any notification creation — the wheelchair accessibility scenario was the exact case that exposed this gap.

## Tests

867 passing / 0 failures (864 baseline + 3 new).

## Deployment

Source committed `e62bcd9`, pushed to main. Background deploy to all three containers.
