---
name: post-exec subagents run silent in background
description: Post-execution subagents (task-sync, code-explainer, SystemMap/Clients sync) must run in background and must NOT surface their output in the TLDR or add wall-time to briefs.
type: feedback
originSessionId: a8da0e6a-d80e-4538-ae7c-11b06ae6beb0
---
Post-execution subagents that update local tooling/state (task-sync for tasks.json, SystemMap/Clients sync, and similar meta-infra assistants) must:

1. Run in **background** (fire-and-forget, never foreground)
2. **Not** have their status lines surfaced in the main output / TLDR
3. Add **zero** wall-clock time to brief execution

**Why:** The user does not need feedback about whether a bookkeeping agent ran. The TLDR should describe what shipped, not what maintenance ran. Synchronous execution of a local-only agent is pure latency with no user-visible value.

**How to apply:**
- When designing any post-exec subagent that touches LOCAL state only (not committed, not deployed), always spec it as background
- Only foreground a subagent when its output is a committed artifact (e.g. `code-explainer` writes `marina_explanation_XXX.md` which IS tracked — but even then, consider whether the user needs to see the confirmation)
- Do not include subagent status lines in your user-facing TLDR
- Contrast: `brief-reviewer` and `output-reviewer` ARE foreground because they gate the flow (fail → fix → re-run). `task-sync` does not gate anything.
