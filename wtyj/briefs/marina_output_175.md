# OUTPUT 175 — Marina date disambiguation

## What was done

Added a `DATE AMBIGUITY RESOLUTION` block to Marina's system prompt in `marina_agent.py`, inserted between `STATE MANAGEMENT` and `HARD REFUSAL RULES`. The rule tells Marina that "next [day]" (e.g. "next Saturday") means the NEAREST upcoming instance, NOT a week later — fixing the secondary issue Anne-Sophie hit where Claude interpreted "next Saturday" from a Thursday as April 18 instead of April 11. Critical addition: Marina must state her interpretation inline in her reply ("I'm reading 'next Saturday' as April 11 — let me know if you meant a different date") so the customer can correct without a round-trip. Also covers related phrases: "this [day]", "[day] week" / "a week from [day]", "in N days", "tomorrow", "this weekend". Truly-vague phrases ("sometime next month") still defer to the existing FIELD EXTRACTION RULES behaviour.

## Tests

**828 passing / 0 failures** (825 baseline + 3 new).

## Deployment

Source committed `7a43fa5`, pushed to main. Background deploy fired to both containers. Prompt-only change — no schema, no code path, no data migration.
