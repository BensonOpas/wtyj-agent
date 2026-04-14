# BRIEF 198 — task-sync subagent: automatic tasks.json updates after each brief

**Status:** Draft | **Files:** `.claude/agents/task-sync.md` (NEW), `.claude/commands/brief.md` (MODIFY) | **Depends on:** Brief 197 (established the foreground-subagent pattern for post-exec steps) | **Blocks:** —

## Context

Three briefs in a row (194, 195, 196) completed work that mapped cleanly to subtasks in `tools/control-panel/data/tasks.json` (s40 CI/CD, s41 staging, s42 backups, s43 monitoring — all part of the `jr.inProgress` "Production infrastructure" task), yet none of those subtasks were marked `done: true` and the task stayed in `inProgress` until Benson pointed it out today.

The skill already tells the executor to do this. From `.claude/commands/brief.md` line 151-155, post-execution step e:

> *If the brief completed a task or subtask on the board, update `tools/control-panel/data/tasks.json` (mark subtask done, move task to inProgress/done, etc). This runs in parallel with the deploy — do not block on it.*

The reminder is there. It was ignored three times in a row. Three reasons:

1. **Buried.** It's the last sentence of step `e`, sharing space with SystemMap + Clients updates which are conditional on channel/capability changes. The eye parses the step as "control-panel sync if channels changed," scans the SystemMap/Clients instructions, skips the tasks.json bit.
2. **Reactive phrasing.** "If the brief completed a task..." reads as conditional. In practice I'd decide "my brief was reviewer-caught patches" or "my brief was a workflow fix" — both feel like NOT completing a task — and skip the step, even though those patches belong to subtask s40.
3. **Fire-and-forget posture.** "Runs in parallel with the deploy — do not block on it" tells the executor this is low-priority; easy to drop.

The result: the control-panel board lied to Benson. Production infrastructure was 100% built but the UI showed it as 0% done with the task still in `inProgress`.

Prompt wording alone won't fix this. I've re-read this section every brief and still skipped it. What fixes it: remove the "did I remember?" decision from the executor entirely.

## Why This Approach

Rejected — **prompt tightening only.** Making the tasks.json reminder more prominent inside step `e`. I've re-read the current step `e` text dozens of times across the last week and still skipped the tasks.json update. Making it bolder is a weak intervention against a habit.

Rejected — **Python script parsing git diff.** A script that scans the diff + brief title and auto-updates tasks.json. Brittle because the mapping from "files changed in diff" to "subtask in the board" isn't mechanical — subtask titles are operator-facing English ("CI/CD pipeline", "Staging environment"), diffs are code paths. Requires exactly the same semantic-matching judgment as a subagent would, with none of the flexibility.

**Chosen — dedicated subagent.** Follow the exact pattern Brief 197 established for `code-explainer`: a foreground subagent invoked automatically during post-execution. The subagent reads the brief + tasks.json + commit diff, makes the semantic-matching call, writes the JSON, reports what it did. Removes the "did I remember?" decision from the main executor — it's now a tool call that runs every time.

Tradeoff: the subagent will occasionally mismatch (mark the wrong subtask done, or miss a match that was obvious). Mitigation: safety rules in the agent prompt cap the blast radius — only mark done (never undone), only touch existing subtasks (never invent), require high-confidence match (when uncertain, no-op + report), never touch the `sr` column (that's Benson's human co-worker's lane).

Same bootstrap wrinkle as Brief 197: Claude Code discovers agent personas at session start, so this brief's own post-exec can't use the new agent. The executor hand-updates `tasks.json` for Brief 198 itself as a one-off, then from Brief 199 onward the subagent runs automatically.

## Instructions

### Step 1 — Create `.claude/agents/task-sync.md`

New file. Frontmatter follows the project convention (see `.claude/agents/code-explainer.md` and `.claude/agents/brief-reviewer.md`). The body defines the persona and rules.

Exact file content:

```markdown
---
name: task-sync
description: "Post-execution task board updater. Reads a brief + the commit diff + tools/control-panel/data/tasks.json, decides which subtask (if any) the brief delivered, and marks it done. Invoke with: task-sync: update tasks for Brief <N>"
tools:
  - Read
  - Bash
  - Glob
  - Grep
  - Write
  - Edit
---

# Task Sync

You are the post-execution task board updater. You run after a brief's source commit lands and decide whether the brief delivered a subtask on the internal task board. If yes, you mark it done.

## Your reader

The control panel at `localhost:4000` reads `tools/control-panel/data/tasks.json` live. When you mark a subtask done, Benson sees it done the next time he opens the Tasks tab. When you leave stale subtasks open after their work shipped, the board lies.

## What you read

You are given a brief number N. Run:

```
cd /Users/benson/Projects/bluemarlin-agent
cat wtyj/briefs/marina_brief_<NNN>_*.md       # the brief itself
cat tools/control-panel/data/tasks.json       # current board state
git show --stat HEAD                          # last commit's file list
```

If the brief number is missing or the brief file doesn't exist, print an error and exit without writing.

## What you decide

For every subtask in `jr.todo` and `jr.inProgress` (the Jr column — never touch `sr`), ask:

> Does this brief's stated deliverable match what this subtask describes?

Match rules:

- **Strong match** (do mark done): the subtask title names a deliverable the brief explicitly ships. Example: brief delivers "canary pipeline in .github/workflows/ci-deploy.yml" → subtask s40 "CI/CD pipeline (GitHub Actions)" is a strong match.
- **Partial match** (do mark done): the brief ships a meaningful fraction of the subtask. Example: brief adds rclone Google Drive sync → subtask s42 "Automated backups (VPS snapshot + SQLite)" was already partly done, this completes the off-site half. Use judgment — if the remaining work is "the rest of backups" and this brief shipped a large chunk, mark done.
- **No match** (leave alone): the brief doesn't clearly correspond to any subtask. Common for refactors, bug fixes, meta-infra briefs, subagent work. When in doubt, no-op.

**Never** invent new subtasks. Never add entries. Never reorder.

**Never** mark a subtask undone. Once done, always done. If you think a "done" subtask was wrongly marked, report it and stop — do not flip it.

**Never** touch the `sr` column. That's Benson's human co-worker's board.

## What you write

After deciding, edit `tools/control-panel/data/tasks.json` (using the Edit tool):

1. For each subtask you decided to mark done: flip its `"done": false` → `"done": true`.
2. After all subtask flips: check every task in `jr.inProgress`. If ALL of its subtasks are now `"done": true`, move that task object from `jr.inProgress` into `jr.done` (prepend to the done list), and set its `"collapsed": true`.
3. If a task in `jr.todo` has all subtasks done (rare but possible), same treatment — move to `jr.done`, collapse.

Preserve JSON formatting (2-space indent, key order unchanged). The file is gitignored — your edit is local-only, no commit needed.

## What you report

Print a single line:

```
TASKS UPDATED: <what you did>
```

Examples:
- `TASKS UPDATED: marked s40 (CI/CD pipeline) done; 3 subtasks remain in Production infrastructure`
- `TASKS UPDATED: marked s40, s41, s42, s43 done; moved "Production infrastructure" inProgress → done`
- `TASKS UPDATED: no matching subtasks found for Brief 197 (plain-English code explainer)`

If you made no changes, still print the line so the main executor has confirmation the agent ran.

## Rules for you

- **Read-first, decide-second, write-third.** Do not write before reading all three inputs.
- **One decision per subtask.** Don't mark + then unmark in the same run.
- **Low false-positive tolerance.** A wrong "done" mark deceives the operator; a missed "done" mark just means the next brief's task-sync has one more candidate to consider. Lean conservative — no-op when uncertain.
- **Plain-English match, not keyword match.** "Staging environment" matches a brief that ships the staging container even if the word "staging" appears only in one instruction. Don't require exact token overlap.
- **Never touch `sr`.** Hard rule.
- **Never invent subtasks.** You only flip existing `done` flags and move existing task objects.
```

### Step 2 — Modify `.claude/commands/brief.md`

Current step `e` (lines 146-155) bundles three things: SystemMap, Clients, tasks.json. Split tasks.json out into a new unconditional pre-check, and keep the SystemMap/Clients logic as the conditional second half.

Find this text:

```
    e. **Control panel sync (run as background subagent while deploy
       is in flight).** If the brief built, removed, or changed the
       status of a channel, capability, or escalation route: spawn a
       subagent to update the system map nodes/edges in
       `tools/control-panel/src/pages/SystemMap.tsx` and the client
       cards in `tools/control-panel/src/pages/Clients.tsx`. If the
       brief completed a task or subtask on the board, update
       `tools/control-panel/data/tasks.json` (mark subtask done, move
       task to inProgress/done, etc). This runs in parallel with the
       deploy — do not block on it.
```

Replace with:

```
    e. **Control panel sync.**
       - **ALWAYS run `task-sync` subagent.** Invoke synchronously:
         `task-sync: update tasks for Brief <NNN>`. The agent reads the
         brief + tasks.json + commit diff, marks any matching subtasks
         done, and moves fully-done tasks from inProgress → done. Runs
         concurrently with the background deploy from step `b`; the
         JSON edit is local-only (file is gitignored) so no commit
         follows. If the agent reports no match, that's fine — move on.
       - **IF the brief built, removed, or changed the status of a
         channel, capability, or escalation route:** spawn a background
         subagent to update the system map nodes/edges in
         `tools/control-panel/src/pages/SystemMap.tsx` and the client
         cards in `tools/control-panel/src/pages/Clients.tsx`. This is
         fire-and-forget — runs in parallel with the deploy, do not
         block on it.
```

The `task-sync` invocation is foreground-synchronous so the report line ("TASKS UPDATED: ...") appears in the executor's output and shows up in the TLDR. No file commit follows because `tasks.json` is gitignored per `.gitignore` line 79 (`tools/control-panel/data/`).

### Step 3 — Bootstrap: run the equivalent work manually for Brief 198 itself

This brief's own post-exec can't use the new `task-sync` agent (agent personas discovered at session start). Do the equivalent by hand:
- Read `tools/control-panel/data/tasks.json`.
- Scan `jr.todo` + `jr.inProgress` for any subtask matching "task-sync subagent" or "tasks board automation" or similar. None exists as of today's state — all existing subtasks are about runtime features (channels, escalations, dashboard, HD Azure). No edit needed.
- Print the `TASKS UPDATED: no matching subtasks found for Brief 198 (task-sync subagent)` line manually in the output so the pattern is established.

From Brief 199 onward, the agent runs automatically.

## Tests

No Python code added — no pytest assertions. The deliverable is a prompt file + a skill file edit. Testing is manual.

**Manual verification (after brief lands, next session):**
1. Claude Code session reloads; new `task-sync` agent appears in the agent list (visible via session's agent discovery on startup).
2. On the next brief that completes a subtask (any of the open items in `jr.todo` — HD Azure onboarding subtasks, Dashboard improvements, etc.), the post-exec flow invokes `task-sync: update tasks for Brief <N>` synchronously, the agent writes the tasks.json flip, prints the TASKS UPDATED line. Open control panel → Tasks tab → verify the subtask shows done.
3. On a brief that doesn't correspond to any subtask (a bug fix, a refactor), `task-sync` runs and reports `TASKS UPDATED: no matching subtasks found for Brief <N>`. Tasks tab unchanged.

**Regression baseline:** 904 passing / 0 failures (same as Brief 197, no Python changes).

## Success Condition

From Brief 199 onward: every brief's post-exec output includes a `TASKS UPDATED: ...` line (whether it marked anything or reported no-op), and Benson never has to ask "why isn't the board updated" because the board mirrors the brief history automatically.

## Rollback

`git revert <commit>` — deletes `.claude/agents/task-sync.md` and restores the old step `e` in `brief.md`. Reverts to manual task-board tending. Zero runtime impact because no production code changed.
