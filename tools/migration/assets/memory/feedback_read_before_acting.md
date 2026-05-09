---
name: Always read files before acting — never trust summaries or memory
description: Critical workflow rule. Claude must read actual file contents before every brief/change, even if it thinks it already knows what's in them. Compaction summaries and context memory are not substitutes for reading.
type: feedback
---

Always read the actual files before writing a brief, making changes, or giving advice about the codebase. Never trust:
- Compaction summaries (they describe files but don't contain them)
- Earlier reads in the same session (context window pushes them out)
- Your own memory of what a file contains (it may have changed)

**Why:** Multiple times Claude has made decisions based on stale mental models — wrong config paths (contact_for_booking vs email), wrong line numbers, wrong function signatures, missed hardcoded values. Every time, the fix was "read the file first."

**How to apply:** Before every brief, re-read the files listed in CLAUDE.md even if you think you already did. Before modifying any file, read it again even if you read it 20 messages ago. If you're unsure whether something exists or what it contains, read it — don't guess from context.

**Also applies to:** The planning docs (master_plan.md, roadmap.md, system_state.md, infra.md, marina_lessons.md). These change between sessions. Read them, don't assume their contents from memory.
