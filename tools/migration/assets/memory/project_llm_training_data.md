---
name: LLM training data — preserve all decision-making traces
description: Long-term goal to train a custom LLM from BlueMarlin's build history. All docs, briefs, conversations, decisions should be preserved and structured for future fine-tuning.
type: project
---

**Goal:** Train a custom LLM on the complete history of building BlueMarlin from zero to production.

**Why this is valuable:** The data being generated is rare — real decision-making traces from building a product, not polished tutorials. It includes: initial ideas, wrong approaches, pivots, architecture decisions with reasoning, prompt engineering iterations, live production bugs and fixes, scaling decisions, client-specific vs generic design tension. This is the kind of data that would make an AI genuinely good at building things.

**What to preserve:**
- All brief files (the planned approach before execution)
- All output files (what actually happened)
- All lesson entries (what went wrong)
- system_state.md (brief-by-brief changelog)
- roadmap.md (how priorities shifted over time)
- master_plan.md (how the vision evolved)
- The archive/ folder (historical snapshots, drift logs, old plans)
- Memory files (decisions, feedback, project context)
- Conversation transcripts (if available via Claude Code logs)

**How to apply:** Never delete documentation permanently — archive it. When updating docs, the old version is in git history. When making architectural decisions, write down the reasoning (not just the outcome). Brief files + output files are the core training pairs: "here's what we planned" → "here's what happened."

**Format consideration for future:** The data will need to be structured as instruction/response pairs or decision trees for fine-tuning. The brief→output format is already close to this. Lessons are the correction signal.
