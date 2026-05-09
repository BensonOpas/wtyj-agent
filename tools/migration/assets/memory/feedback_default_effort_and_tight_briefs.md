---
name: Default-effort thinking + tight briefs (anti-bloat)
description: Max-effort thinking mode + oversized briefs + full subagent ceremony stack multiplicatively. Use default effort by default; size briefs to scope.
type: feedback
originSessionId: a8da0e6a-d80e-4538-ae7c-11b06ae6beb0
---
When `/model` is set to max effort, every tool call thinks for many minutes instead of seconds. Each subagent invocation also runs at full effort. Combined with oversized briefs and full subagent ceremony, simple work balloons 5-10x. Brief 205 (4 small UX fixes, ~50 lines of code) took 6h 30m on max effort and got rolled back anyway — wrong diagnosis caught only after a parallel-agent audit.

**Why:** Benson explicitly flagged this in 2026-05-06 session — "what the fuck you spend 4 hours mate, what are you doing". The 6.5-hour single-turn was visible on his Claude Code UI. He went to bed before it finished and was furious in the morning.

**How to apply:**
- Default effort unless user explicitly says max for hard reasoning. Most engineering work doesn't need it.
- Tight briefs: aim for ~200 lines max for small fixes. Rejected-alternatives + threat-models + JSON-escaping notes are appropriate for full-scope features (Brief 200's nginx cutover, Brief 207's full Tasks API), NOT for 5-line behavior changes.
- Quick-fix path covers more than I was using it for. CI script tweaks, contract-correction patches to recently-shipped briefs, doc additions — these don't need full brief ceremony.
- For tight briefs (smooth changes), skip output-reviewer + code-explainer + lessons-file + system_state-writeup if the user asks for speed. Commit + deploy + TLDR is enough.
- When a turn has been running for 30+ minutes, that's an outlier — abort and check in with the user. There's no internal heartbeat for this; I have to remember.

**Context for future sessions:** the brief workflow's safety gates (brief-reviewer, output-reviewer) are valuable for non-trivial changes. The post-exec ceremony (lessons, system_state, code-explainer) is valuable for the historical record. But ALL of it at max effort for ALL changes regardless of size is wrong. Match weight of process to weight of change.
