# EXPLANATION 197 — Plain-English code explainer as a post-execution step

## In one sentence

Every brief from now on produces a plain-English translation of what its code does, and the control panel's Deploys tab lets an operator click any past deploy to read that translation.

## What's changing and why

Before this, an operator could see in the Deploys tab which briefs had been deployed — brief number, SHA, timestamp, success/failure — but not what any of them actually did. To understand that, they had to read the brief's own instructions, which are written for the person executing them (file paths, line numbers, technical steps). That's no good for someone who doesn't read code.

This brief adds a fourth artifact per brief: a translation file. After each brief ships, a dedicated translator subagent reads the commit and writes a plain-English walkthrough — "the system now does X when Y happens, here's why it matters, here are the edge cases." No code. No file paths. No jargon. The translation file is committed alongside the other post-execution documents, and the Deploys tab surfaces it on click.

The aim is that the operator's understanding of "what just shipped" doesn't require reading a brief or asking the developer. Click a deploy, read the translation, know what's different.

## Step by step — what the code does now

STEP: The translator subagent

There is now a new persona called the code-explainer. It runs after every brief's source has been committed and pushed, but while the deploy is still running in the background so it adds no waiting time. The persona reads the commit's changes and the brief's stated intent, then writes the translation to a new file whose name includes the brief number (for example, a translation for Brief 200 lives at a file called marina_explanation_200). The persona has strict rules: no code snippets, no file names, no line numbers, no AI warnings (which are unreliable anyway because the AI overlooks its own mistakes), no jargon. It's forced to write in operator-friendly prose.

STEP: The brief workflow inserts the translator

The instruction set that Claude Code follows for every brief has been restructured. Where it used to go "commit source → deploy → update the session log, lessons, and any docs → verify the deploy succeeded → commit the post-execution documents," there is now a new step between the docs update and the verify step: "run the translator." Because the deploy is still running in the background during all of this, the translator does its work during otherwise idle time — no slowdown. By the time the post-execution commit happens, the translation file exists and gets committed alongside the output summary, the session log update, and the lessons entry.

A small related fix was made at the same time: a stale cross-reference in the instructions now points at the correct step (the post-execution commit moved from "step f" to "step i" due to the insertion). A future brief writer will also see a note that the translation file is auto-generated and should not be added to the brief's file list or written by hand.

STEP: The control panel learns to show translations

The Deploys tab now has clickable rows in the "Recent deploys" section. Clicking a row expands it inline and fetches the translation for that brief from the repository (using the existing document-reading endpoint; no new backend code). The translation is rendered as formatted text using the same library the Workspace tab already uses. Click the row again and it collapses.

If a row is for a brief from before this one (brief 196 and earlier), there's no translation file. The tab shows a single italic line: "No explanation available (brief predates Brief 197)." The operator immediately understands this isn't a broken display — just an older deploy that didn't have the translator yet.

## Edge cases

- **If the translator fails or takes unusually long.** Because it runs during the deploy window (typically 90 seconds), there is plenty of time. If it somehow doesn't finish before the post-execution commit, the commit will fail to find the translation file and the whole post-execution step errors out — the operator sees the problem immediately rather than having the commit silently omit the file. Acceptable, because this case is unlikely and better loud than silent.

- **If the translator is invoked manually on a very old commit.** The agent reads the brief file whose number matches; if none exists, the agent errors out before writing. No corrupt file gets produced.

- **If the brief number can't be extracted from a commit message.** The Deploys tab shows "Brief —" for that row. Clicking it shows the same fallback message as pre-197 entries. The operator understands the row represents a deploy that doesn't correspond to a numbered brief (for example, the hotfix health-check retry commit earlier today).

- **If this brief's own translation fails to be produced.** The infrastructure is brand new. Claude Code only discovers agent personas at session start, so the very first invocation — this one — can't use the new persona. It's been done by hand as a bootstrap. From the next brief onward, the persona will be auto-discovered and the whole thing is automatic.

## What did NOT change

No change to how the agent answers customers. No change to the booking flow, the email poller, the webhook handler, or any customer data. The test suite is untouched (904 tests, same as before). Nothing about how pushes enter the queue or drain at off-hours is different. The only surfaces that changed are: the instruction file Claude Code follows when executing briefs, the list of personas Claude Code can use, and the Deploys tab UI. Every other part of the system is identical to yesterday.
