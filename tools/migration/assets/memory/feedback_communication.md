---
name: Communication style
description: Plain language for explanations, TLDR after changes, no buzzwords
type: feedback
---

Technical details in code and briefs — precise is fine.
When explaining to the user what happened — name the file, say what it does, skip jargon.

**Why:** User gets lost when output references multiple files with technical names and unexplained relationships. "sigmapoop.py working with interval phsipenpsya.html" — they can't parse that.

**How to apply:**
- After any response with code changes, end with TLDR: what changed, what file, what it does now
- When explaining systems, use plain English not framework terminology
- Don't assume the user knows what internal file names mean — explain their purpose
