# LESSONS.md
# Accumulated learnings across all BlueFinn/BlueMarlin work.
# Two sources: observations reported by Benson, decisions made during execution.
# Format per entry below.

---

## Template
### [Brief 0XX or Observation] — [date] — [one line title]
**What happened:**
**What was tried:**
**What worked:**
**Lesson:**
**Contradicts:** [previous lesson number if applicable, or none]

---

## Session — 2026-03-07 — Workflow Optimization (JR Workflow v2)

### What we built
Complete overhaul of the development workflow. Claude Chat removed from the
daily operational loop. Everything operational now runs in Claude Code CLI.

### Changes made
1. CLAUDE.md — created. Dual-mode (plan + execute). Architecture rules,
   interfaces, communication style, /compact at 50% discipline. Under 200 lines.
2. LESSONS.md — this file. Created for accumulated learnings across projects.
3. SYSTEM_STATE.md — Decision Log section added.
4. .claude/commands/think.md — planning command. Reads CLAUDE.md + relevant
   files, thinks out loud, no file writes, appends to Decision Log when direction
   confirmed, reminds to /compact before /brief.
5. .claude/commands/brief.md — brief writing command. Reads Decision Log + all
   relevant files, writes BRIEF_0XX using mandatory template, auto-invokes
   brief-reviewer, patches on failure (one retry), reminds to /compact before
   executing.
6. .claude/agents/ — brief-reviewer, drift-detector, output-reviewer confirmed
   in correct location. brief-reviewer updated: added ## Why This Approach check.
   drift-detector updated: stale violations cleared, heading updated to Brief 032.
7. ultrathink — added to both /think and /brief for complex reasoning.
8. Status line — installed at ~/.claude/scripts/status-line.sh. Shows live
   context usage, git status, model. Warns at 80%.

### Workflow: JR v2
/think → discuss + read relevant files → Direction Log entry → /compact
/brief → reads Decision Log + files → writes brief → brief-reviewer auto-runs
→ patch loop (one retry max) → /compact → execute → OUTPUT_0XX written
→ SYSTEM_STATE updated → git push → VPS pull

Claude Chat role: architecture decisions only. Short sessions. Close when done.

### Bookmarked for later
- Agent Teams — native Anthropic multi-agent coordination. Use when running
  parallel briefs across a future project. Enable with
  CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1.
- mcp-builder skill — use when building VPS SSH MCP server. Guides MCP server
  creation instead of designing from scratch.
- context-mode plugin — 98% context reduction for heavy MCP tool output sessions.
  Not needed now. Revisit when project involves heavy API calls or log analysis.

### Key decisions
- agentchattr skipped — replaced natively by Agent Teams
- hallucination-detector skipped — brief-reviewer and drift-detector already cover this
- Ralph Wiggum skipped — Claude Code already one-shots execution
- Claude Chat removed from daily loop — CLI has no browser lag, reads files
  directly, sessions stay short

### Lesson
The relay between tools was the bottleneck, not execution quality.
Moving planning into the CLI eliminates browser lag and reduces copy-pastes
from 8-10 per brief to 3-4. Architecture discipline was already correct.

---

### Brief 033 — 2026-03-07 — Thread key via Message-ID/In-Reply-To
**What happened:** `stable_thread_key()` accepted `msg` but never used it — thread state was keyed on subject alone. Replaced with `resolve_thread_key()` that checks `References` and `In-Reply-To` headers before falling back to subject.
**What worked:** Flat `message_id_index` dict stored alongside `threads` in the same state file. No schema migration, full backward-compat via `setdefault`.
**Lesson:** When the output-reviewer requires a test file on disk, writing the tests inline in a Bash call and discarding them is not sufficient — the file must be committed. The brief should have been more explicit, but output-reviewer correctly caught it.
