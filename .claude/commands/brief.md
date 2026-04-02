---
description: Write a brief, review it, and execute end-to-end
---

Brief mode. Write the brief, review it, and if approved execute it end-to-end.

## Writing the brief

1. Read CLAUDE.md, briefs/system_state.md, briefs/infra.md, briefs/roadmap.md
2. Read every file you will reference or modify — ACTUALLY read them, don't trust memory
3. Determine the next brief number from existing files in briefs/
4. Write to briefs/marina_brief_XXX_name.md using the template in CLAUDE.md

Test philosophy: a few basic "it works" tests + harder tests for edge cases,
failure modes, and real behavioral checks. Number of tests is your judgment
based on complexity. Tests should catch bugs, not just confirm types.

## Review cycle

5. Invoke the brief-reviewer agent automatically
6. If flagged: patch and re-invoke (one retry max)
7. If approved: continue to execution (do NOT wait for user approval)

## Execution

8. Read the brief completely before touching any file
9. Read every file listed in the brief header
10. Execute instructions exactly as written
11. Run the tests. If they fail: fix and re-run in foreground
12. Run the full social regression suite in background
13. Write briefs/marina_output_XXX.md (what was done, test results, unexpected)

## Post-execution

14. Invoke the output-reviewer agent automatically
15. If flagged: patch source + OUTPUT, re-invoke (one retry max)
16. If approved:
    a. Update system_state.md (add brief entry at the end)
    b. Write detailed lessons entry in briefs/marina_lessons.md:
       - Problem briefs: full story (what happened, why it failed, what we did, the principle, what to watch for) — 10+ lines
       - Smooth briefs: decision + outcome + any non-obvious technique — 3-5 lines
       - NEVER skip this step. NEVER write less than 3 lines.
    c. If new credentials, env vars, services, or URLs were added: update briefs/infra.md
    d. git add -A && git commit && git push
17. End with a TLDR: what changed, what file, what it does now. Plain English.

## Quick fix path

If the user says "just fix it" or the change is a one-liner / config tweak
with no architectural significance: skip the brief. Just make the change,
test it, commit with a descriptive message, and TLDR.
