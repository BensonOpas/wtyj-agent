---
name: Always run both reviewers
description: Brief-reviewer before execution and output-reviewer after are mandatory — never skip them
type: feedback
---

Always invoke brief-reviewer before executing a brief, and output-reviewer after writing the OUTPUT file. This is mandatory every time, even if the user doesn't explicitly ask for it.

**Why:** The user had to remind me multiple times to run the output-reviewer. The workflow is defined in the /brief skill instructions and should be automatic.

**How to apply:** After writing a brief → invoke brief-reviewer → patch if needed → execute → write OUTPUT → invoke output-reviewer → patch if needed → then commit/deploy. Never skip either step.
