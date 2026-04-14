# EXPLANATION 198 — task-sync subagent: automatic tasks.json updates after each brief

## In one sentence

Every brief from now on will automatically keep the internal task board in sync with what just shipped, so when a brief finishes a piece of work the matching item on the board ticks itself off instead of waiting for a human to remember.

## What's changing and why

Before this, whenever a brief shipped, the executor was supposed to open the task board file and manually mark the matching subtask as done. That instruction existed in the brief skill for days but kept getting skipped — three briefs in a row delivered production-infrastructure subtasks and left all of them unchecked on the board. The board ended up lying to the operator about what was actually built.

This brief replaces the "remember to update the board" instruction with a dedicated assistant that runs every time. After the source commit for any brief goes out, the assistant reads the brief's stated deliverables, reads the current state of the board, looks at what actually changed in the commit, and decides: did this brief deliver something that's waiting on the board? If yes, it ticks the matching subtask. If every subtask under a bigger task is now ticked, it moves that task into the Done column and collapses it. If nothing on the board matches what this brief delivered, it reports "no match" and does nothing.

The aim is that the board matches reality without anyone having to think about it. You open the control panel, you see the real state.

## Step by step — what the code does now

STEP: The task-board assistant

There is a new assistant persona called the task-sync. It runs after the brief's source commit has been made, in the same phase as the plain-English explainer introduced last brief. The assistant reads three things: the brief itself, the current task board, and the list of files that just changed in the commit. It then walks the Junior column of the board (never the Senior column, which is for a human co-worker), looks at every task and subtask not yet marked done, and asks: does this brief's stated deliverable match what this subtask describes? If yes, it ticks the subtask. If uncertain, it leaves it alone. It never invents new subtasks, never un-ticks a previously done item, and never touches the Senior column.

STEP: The brief workflow invokes it

The instruction set the executor follows for every brief has been restructured. The post-execution step that used to bundle three concerns ("update the system map, update the client cards, update the tasks board — if any of these apply") has been split into two clearer sub-steps. The first sub-step is always-run: fire the task-sync assistant. The second sub-step is conditional and only triggers when the brief touched channels, capabilities, or escalation routes — in which case a separate background assistant updates the system-map and client-card visuals. By separating the always-run from the conditional, the tasks-board update can never again be skipped on the grounds that "this brief didn't change a channel."

STEP: The board edits stay local

The task board is a local-only file, not committed to the shared repository. Every person running the control panel has their own copy. That means the task-sync assistant's edit to the board is strictly personal — it changes what the operator sees when they open the control panel on this machine, and nothing else. No deployment to the servers. No effect on paying clients. It is purely a bookkeeping update for the person who owns this local control panel.

STEP: The assistant's safety rules

The assistant has four hard rules that cap how much damage a wrong decision can do. First, it can only tick subtasks, never un-tick them — once something is marked done, it stays done, even if the assistant later thinks it was ticked in error (in that case it reports the suspicion and stops, leaving the fix for a human). Second, it can only touch subtasks that already exist on the board; it cannot invent new ones. Third, it cannot touch the Senior column. Fourth, when the match between the brief and a subtask is ambiguous, it defaults to leaving the subtask alone rather than ticking it optimistically — a missed tick just leaves work for the next brief's task-sync to consider, whereas a wrong tick deceives the operator into thinking work is done.

## Edge cases

- **If the assistant mis-matches and ticks the wrong subtask.** The hard rule of "never un-tick" means you will see a wrongly-ticked subtask on the board and you will need to either live with it or edit the file by hand. Not ideal, but better than the assistant flipping back and forth. If this happens more than rarely, the agent's match rules need tightening.

- **If the assistant misses an obvious match.** The subtask stays open. The next brief that ships something related will trigger another task-sync run, and the assistant will see the same subtask and try again — if the newer commit makes the match clearer, it ticks. In practice, work rarely spans multiple briefs without at least one of them being an obvious match, so misses self-heal over time.

- **If the brief doesn't correspond to any subtask on the board.** Common for meta-infrastructure work, reviewer-caught patches, bug fixes, refactors, and documentation updates. The assistant reports "no matching subtasks found" and the board stays unchanged. Not an error — just the honest output for that case.

- **If the assistant is invoked on a brief whose file can't be found.** The assistant prints an error and exits without writing anything. The brief skill's post-execution step will see the error in the agent's report and the operator can decide what to do. No silent corruption.

- **If this brief's own task-sync needed to run.** The infrastructure is brand new. The assistant persona is discovered once at the start of a Claude Code session, so the very first invocation — on this brief — can't use the assistant. Handled by hand: the bootstrap path in the brief instructed the executor to print the canonical "no match found" line manually, since the current board doesn't have a subtask matching "meta-infra assistant for tasks-board automation." From the next brief onward, the assistant is auto-discovered and runs on its own.

## What did NOT change

No change to how the agent answers customers, takes bookings, escalates conversations, or sends replies. No change to any customer-facing channel — WhatsApp, email, Instagram, Facebook all behave identically to before. No change to the test suite (904 tests, same as before). No change to the CI/CD pipeline, the staging or canary rules, or the deployment behavior. No change to the servers that run paying clients' containers. The only things that changed are a new assistant persona file in the developer tooling and a few paragraphs in the developer's own brief-execution checklist. Every other part of the system is identical to before Brief 198.
