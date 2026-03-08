---
You are in BRIEF WRITING MODE. Do not execute any code. Do not edit source files.
For complex or ambiguous problems, use ultrathink to reason deeply before responding.

On activation:
1. Read CLAUDE.md and briefs/SYSTEM_STATE.md
2. Read the Decision Log entry for this brief
3. Read every file you will reference or instruct changes to
4. Determine the next brief number by counting existing files in briefs/
5. Write the brief to briefs/BRIEF_0XX_name.md using the mandatory template
6. When written, automatically invoke the brief-reviewer agent
7. If brief-reviewer flags discrepancies: patch the brief, invoke brief-reviewer again (one retry max)
8. If approved: tell the user "Brief approved — ready to execute"

Mandatory brief template:

# BRIEF 0XX — Title
**Status:** Draft | **Files:** [list] | **Depends on:** [brief or none] | **Blocks:** [brief or none]

## Context
Current state and why this brief exists.

## Why This Approach
What was considered, what was rejected, what tradeoff this carries.

## Source Material
Files read. Relevant excerpts.

## Instructions
[Step by step for Claude Code executor]

## Tests
[Exact assertions, specific values not just types]

## Success Condition

## Rollback

After brief is approved, remind the user: "Suggested: /compact before executing"

---

## After execution and OUTPUT file is written

1. Automatically invoke the output-reviewer agent
2. If output-reviewer flags issues: patch the source files and OUTPUT file, then re-invoke (one retry max)
3. If output-reviewer approves:
   a. Update SYSTEM_STATE.md Decision Log — change the brief's outcome from `pending` to `complete`
   b. Append an entry to LESSONS.md (create file if it doesn't exist):
      - Format: `## Brief 0XX — Title` / `Date:` / one or two sentences on what worked, what was tricky, or what to watch for in future briefs
   c. Run: `git add -A && git commit -m "Brief 0XX — title — N/N tests pass" && git push`
---
