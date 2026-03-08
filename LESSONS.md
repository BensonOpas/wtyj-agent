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

### Brief 038 — 2026-03-07 — Child age pricing + mid-confirmation day-of-week check
**What happened:** Two prompt fixes from Brief 037 stress test. Fix 1 (child age): Marina now asks ages before pricing when "kids" are mentioned — S21 re-run produced "How old are your 3 children?" with correct tier explanation. Fix 2 (S12 mid-confirmation date bug): day-of-week check now runs when a customer changes a date mid-confirmation thread. Both verified via live API calls (T6/T7).
**What was tricky:** Brief test assertions used capitalized strings ("If the change involves", "ask for them before") that didn't match the actual multiline f-string prompt (lowercase "if", line break between "ask" and "for them"). Silently fixed during execution — flagged by output-reviewer. Next time: test assertions in the brief should be verified against the exact replacement text in the same brief before submission, especially for multiline f-strings where whitespace breaks substring matches.
**Lesson:** When writing test assertions for f-string prompt content: (1) check exact case against the find/replace text in the same brief, (2) watch for line breaks — `"ask\n  for them"` does not match `"ask for them"`. If a substring spans a line break, test for a phrase that falls entirely on one line.
**Contradicts:** none

---

### Brief 037 — 2026-03-07 — Extended stress test: 8 new edge case scenarios
**What happened:** Added S15–S22 to test_marina_stress.py and ran all 22 scenarios. 6 PASS, 2 PARTIAL (S21 child pricing, S22 "in 3 weeks"), 1 pre-existing bug surfaced (S12 day-of-week check doesn't block summary when customer changes date mid-confirmation). brief-reviewer flagged T3 as duplicate of T1, hardcoded expected dates for S19/S22, and structural-only tests not catching silent failure. Three targeted patches resolved all reviewer issues.
**What worked:** Test-before-fix discipline paid off — S21 performed better than expected (Marina assumed child rate and flagged under-4 exception) but exposed a real teen-pricing gap. The S12 pre-existing bug wouldn't have been noticed without running the full 22-scenario suite.
**Lesson:** "Structural-only test" briefs should explicitly acknowledge in the success condition that tests verify execution happened, not that execution was correct — otherwise the brief-reviewer will flag it as incomplete coverage. Also: SYSTEM_STATE.md Decision Log is consistently the most-missed step; treat it as the first instruction, not the last.
**Contradicts:** none

---

### Brief 036 — 2026-03-07 — Marina prompt bug fixes from stress test
**What happened:** Stress test (14 scenarios) exposed 3 bugs: language detection fired on sender name not body text, day-of-week validation was inconsistent (snorkeling_3in1 caught, west_coast_beach didn't), reply_hold_failed generated for group escalations. Brief 036 fixed all 3. Fix 1 required two iterations — the first patch ("Do not infer from sender's name") was insufficient for names like "Müller"; needed an explicit MUST rule.
**What worked:** Stress tests before calling code "done" are essential — found 3 real bugs that would embarrass in a demo. The day-of-week fix (pointing Marina at days_available in the TRIPS data) correctly avoided hardcoding business values in the prompt.
**Lesson:** When a prompt fix doesn't work on first try, escalate the language from advisory ("do not infer") to mandatory ("MUST be in English"). Soft instructions are ignored when strong signals (like Germanic names) compete. Also: output-reviewer will flag when executed prompt text deviates from the brief's exact find/replace — document the deviation clearly.
**Contradicts:** none

---

### Brief 035 — 2026-03-07 — Marina prompt polish: language + trip key mapping
**What happened:** Added LANGUAGE detection block and trip_key mapping table to marina_agent.py prompt. Cleaned up CLAUDE.md Known Open Issues (3 resolved items removed, fallback exception formally accepted). brief-reviewer flagged 3 rounds of issues — mainly: missing file in header, T8 false-pass risk, incomplete CLAUDE.md replacement, silent removal of a bullet, undocumented fallback exception.
**What worked:** Prompt-only changes (no Python logic) are the right pattern for teaching Claude new behaviour. The mapping table is more reliable than hoping Claude infers trip key from context.
**Lesson:** When writing a brief that removes content from a multi-item list, explicitly state what is kept AND what is removed — and verify the count matches. Silent omissions get caught by brief-reviewer but add unnecessary retry rounds.
**Contradicts:** none

---

### Brief 034 — 2026-03-07 — Fill [VERIFY] placeholders in client.json
**What happened:** All 8 `[VERIFY]` items in `client.json` replaced with demo values. No source code changes. output-reviewer flagged SYSTEM_STATE.md Decision Log not updated on first pass — step was missed during execution.
**What worked:** Data-only brief kept scope very tight. Vessel assignments (TopCat/Red Dragon/Kailani) derived from fleet capacity data already in the file.
**Lesson:** SYSTEM_STATE.md Decision Log update is a required instruction step, not a post-execution formality — treat it the same as any other instruction in the brief.
**Contradicts:** none

---

### Brief 033 — 2026-03-07 — Thread key via Message-ID/In-Reply-To
**What happened:** `stable_thread_key()` accepted `msg` but never used it — thread state was keyed on subject alone. Replaced with `resolve_thread_key()` that checks `References` and `In-Reply-To` headers before falling back to subject.
**What worked:** Flat `message_id_index` dict stored alongside `threads` in the same state file. No schema migration, full backward-compat via `setdefault`.
**Lesson:** When the output-reviewer requires a test file on disk, writing the tests inline in a Bash call and discarding them is not sufficient — the file must be committed. The brief should have been more explicit, but output-reviewer correctly caught it.
