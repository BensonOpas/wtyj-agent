---
name: Lessons entries must be detailed and always written
description: Every brief gets a lessons entry in marina_lessons.md. Problem briefs get the full story (what happened, why it failed, what we did, the principle, what to watch for). Smooth briefs get a shorter entry (decision + outcome). Never skip.
type: feedback
---

After every brief execution, write a lessons entry in `briefs/marina_lessons.md`. This is not optional.

**When something went wrong (reviewer caught issues, live testing failed, approach changed):**

Write the full story:
- **What happened** — what we tried and what broke
- **Why it failed** — the root cause, not just the symptom
- **What we did** — the fix or pivot
- **The principle** — the general rule to follow in the future
- **What to watch for** — when this pattern might bite again

This should be 10-20 lines, not 2 sentences. This data trains a future LLM.

**When everything went smoothly:**

Write a shorter entry — what was decided, what the outcome was, any non-obvious technique used. 3-5 lines.

**Why:** The user is building a dataset for LLM fine-tuning. Short entries like "wrong config path, fixed it" are useless for training. The full decision trace (context → failure → analysis → fix → principle) is what makes the data valuable.

**How to apply:** This is step 16b in the brief workflow. It happens after output review passes, before commit. Never skip it. Never write less than 3 lines.
