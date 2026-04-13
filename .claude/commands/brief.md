---
description: Write a brief, review it, and execute end-to-end
---

Brief mode. Write the brief, review it, and if approved execute end-to-end.

**The brief is the backbone of this project.** Keep it detailed and rich.
Speed comes from cutting specific fat (no Source Material section, no
structural-guard tests, background deploys, right-sized post-exec docs),
NOT from cutting substance or skipping safety gates.

## Writing the brief

1. Read CLAUDE.md, briefs/system_state.md, briefs/infra.md, briefs/roadmap.md, tools/control-panel/data/tasks.json
2. Read every file you will reference or modify. "Read" = open the file
   and read the relevant section. Grep output or stale memory are NOT
   substitutes for reading the current source before editing it.
3. Determine the next brief number from existing files in briefs/. If
   the user explicitly specifies a number ("write Brief 174 to ..."),
   their number wins.
4. Write to briefs/marina_brief_XXX_name.md using the template in
   CLAUDE.md. The template in CLAUDE.md is authoritative — use it as-is.
   Note: older briefs (before 173) sometimes have a "## Source Material"
   section. That pattern is banned going forward; the CLAUDE.md template
   does not include it. Do not copy it from historical briefs.

**Why no Source Material:** pasting 5-10 blocks of current repo source
into a brief was the biggest source of brief bloat in briefs 162-172.
Reference repo code by `path:line` — the reviewer and executor open the
file themselves. External data (API specs, third-party schemas, payload
shapes, log excerpts that prove a bug) DOES get pasted directly because
briefs must be self-contained for non-repo context.

**Test philosophy:** tests that check real behavior. Aim for 3-5 on a
focused brief; scale up when the brief genuinely covers multiple
behaviors (e.g. a new schema + helper + prompt integration). If you're
going over 10 tests, stop and ask whether this should be two briefs. NO
source-level string guards (`assert "foo" in open(...).read()`) — those
are tautologies that pass because you just wrote the string. Good test
shape: given state X, call function F, assert return value Y. Mock-based
integration tests exercising real branches are fine.

**Regression baseline:** the expected "N passing" count is in the latest
entry of briefs/system_state.md. After your new tests land, the new
count should be baseline + N-new + 0 failures.

**Agent filenames stay "marina_":** brief/output/lessons files continue
to use the `marina_` prefix (marina_brief_XXX, marina_output_XXX,
marina_lessons.md) even though the agent name may change per-client via
client.json. The prefix is a historical project convention, not a
per-client label.

## Review cycle (ALWAYS RUNS — never skip)

5. Invoke the `brief-reviewer` agent automatically (defined at
   `.claude/agents/brief-reviewer.md`, auto-discovered by Claude Code)
6. If flagged: patch and re-invoke (one retry max). **If still flagged
   after the retry, STOP and ask the user how to proceed. Do not execute
   a brief that failed two review rounds.**
7. If approved: continue to execution (do NOT wait for user approval)

Skipping `brief-reviewer` to save time is banned. Same for
`output-reviewer` (`.claude/agents/output-reviewer.md`) at step 14. The
~6 min combined cost is cheap insurance against shipping a mistake.

## Execution

8. Read the brief completely before touching any file
9. Read every file listed in the brief header
10. Execute instructions exactly as written
11. Run the focused tests in foreground (from repo root:
    `/Users/benson/Projects/bluemarlin-agent/` on Mac, `/root/` on VPS)
12. Run the full regression (`python3 -m pytest wtyj/tests/ -q`) in
    foreground from the repo root, before commit. Compare passing
    count against the baseline in the latest system_state.md entry.
13. Write briefs/marina_output_XXX.md — ~250 words, see template below

**marina_output_XXX.md template:**
```
# OUTPUT XXX — Title

## What was done
One paragraph (4-5 sentences). Files touched, what changed, key decision.

## Tests
One line: "N passing / 0 failures (baseline M + K new)"

## Unexpected findings
Only include if there were genuine surprises (a stub that was already
wired, a mock target that was wrong, an edge case the brief missed).
If execution was clean, SKIP this section entirely.

## Deployment
Commit SHA(s). "Both containers healthy post-deploy."
```

## Post-execution

14. Invoke the output-reviewer agent automatically
15. If flagged: patch source + OUTPUT, re-invoke (one retry max). **If
    still flagged after the retry, STOP and ask the user what to do.
    Do not proceed.**
16. If approved:
    a. **Commit and push source changes first.** Stage and commit the
       brief file, test file(s), and any modified source files (NOT
       output.md, system_state.md, lessons.md, or infra.md — those come
       later in step f). Push immediately. This MUST happen before the
       deploy because the VPS deploy runs `git pull` and needs the new
       commit on origin.
       ```
       git add wtyj/briefs/marina_brief_XXX*.md wtyj/tests/... <source files>
       git commit -m "Brief XXX: <title>"
       git push origin main
       ```
    b. **Fire deploy in background.** Use Bash with
       `run_in_background: true`. The deploy takes ~90 seconds.
       Immediately proceed to steps c/d/e in parallel — do NOT wait.
       The command below rebuilds the shared `wtyj-agent` image ONCE
       via BlueMarlin's compose, then recreates Adamus's container so
       it picks up the newly-built image (both clients use the same
       image — only one `build` is needed):
       ```
       ssh root@108.61.192.52 "cd /root && git pull && cd /root/clients/bluemarlin && docker compose down && docker compose build && docker compose up -d && cd /root/clients/adamus && docker compose down && docker compose up -d && cd /root/clients/consultadespertares && docker compose down && docker compose up -d"
       ```
    c. Update system_state.md (append entry). **Size:** one descriptive
       paragraph, max ~200 words. Decision in 2-3 sentences, outcome in
       2-3 sentences. Not a bible, not a bullet point.
    d. Write a lessons entry in briefs/marina_lessons.md. **Never skip
       this step — the paper trail is non-negotiable.** Size it to the
       brief:
       - **Problem briefs** (bug hunts, reviewer-caught issues, things
         that went sideways): full story — what happened, why it
         failed, what we did, the principle, what to watch for. 10+
         lines. This is where the real wisdom is captured.
       - **Smooth briefs** (routine work, clean execution): decision +
         outcome + any non-obvious technique. 3-5 lines. If there was
         genuinely no non-obvious technique, still write the decision +
         outcome + one line of what made it smooth. The entry IS the
         chronological index of how the project evolved — routine ≠
         skippable.
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
    f. **Doc maintenance checkpoint:**
       - If new credentials, env vars, services, ports, containers,
         or URLs were added: update `briefs/infra.md`.
       - If the brief shifts a phase milestone: update `briefs/roadmap.md`
         (rare — only on major directional changes).
    g. **Verify deploy succeeded BEFORE committing post-exec docs.**
       Check the background job's output via BashOutput. If the job is
       still running (deploy hasn't finished yet because c/d/e went
       faster than 90s), wait for it — do NOT commit while the deploy
       is in flight. Once the job completes, verify health with a
       separate (foreground) curl:
       ```
       ssh root@108.61.192.52 "curl -s http://localhost:8001/health && curl -s http://localhost:8002/health && curl -s http://localhost:8003/health"
       ```
       All should return `{"status":"ok"}`. If the build failed, a
       container won't start, or health check returns non-OK: STOP.
       Fix the deploy, re-run. Do NOT commit post-exec docs claiming
       success while the deploy is on fire.
    h. Commit and push post-exec docs:
       ```
       git add wtyj/briefs/marina_output_XXX.md wtyj/briefs/system_state.md wtyj/briefs/marina_lessons.md [wtyj/briefs/infra.md]
       git commit -m "Brief XXX post-execution: output + system_state + lessons"
       git push origin main
       ```

17. End with a TLDR section. ALWAYS include this. Plain English, no jargon:
    - What changed (file names)
    - What it does now
    - What the user should notice

## Quick fix path

For changes with **NO behavioral impact**: typo fixes, log level
adjustments, config value changes that don't alter runtime logic,
comment cleanup, dead-code deletion, doc changes. Just fix, test,
commit, deploy, TLDR.

**Any behavioral code change requires a brief — even if the diff is
one line.** Examples that ARE behavioral and need a brief:
- regex change (affects what matches)
- validation rule change
- state machine transition
- Marina prompt wording change
- new field in a schema
- new API endpoint or modified signature
- changed log verbosity on a decision path
- any change that would alter a test's expected output

When in doubt, write the brief. The cost of a short brief is minutes;
the cost of a silent behavioral regression is hours plus customer trust.
