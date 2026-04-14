# OUTPUT 197 — Plain-English code explainer as a post-execution step

## What was done

Added a new `code-explainer` subagent at `.claude/agents/code-explainer.md` that reads a brief's source commit and writes a plain-English translation to `wtyj/briefs/marina_explanation_<NNN>.md`. Modified `.claude/commands/brief.md` to insert a new post-execution step `g` (foreground) that invokes the agent, renumbered the verify-deploy and post-exec-commit sub-steps to `h` and `i` respectively, updated the git add line in step `i` to include the explanation file, and fixed the stale cross-reference in step `a` (now points to step `i`, not `f`). Updated `tools/control-panel/src/pages/Deploys.tsx` to make history rows clickable — click expands the row inline and fetches the explanation via the existing `/api/docs/read` endpoint, rendered as markdown via the already-installed `react-markdown` dep. Missing/pre-197 explanations show the canonical fallback string: `No explanation available (brief predates Brief 197).` Added corresponding CSS. No Python source changes.

## Tests

904 passing / 0 failures (unchanged from baseline — this brief adds no Python code).

## Unexpected findings

None.

## Deployment

To be filled after push. Because this brief's commit subject won't contain `[HOTFIX]`, the canary pipeline will run on BlueMarlin + E2E, then off-hours-decide will queue the commit for the next off-hours window (or you can hit `Deploy queued now` in the control panel to force it). The explanation file for THIS brief will be generated in step `g` of the post-exec sequence via the newly-added code-explainer agent — self-demonstrating on its own commit.
