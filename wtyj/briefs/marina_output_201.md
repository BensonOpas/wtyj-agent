# OUTPUT 201 — dm_agent em-dash strip + dashboard message field aliases

## What was done
Two surgical fixes shipped in one brief. (1) `wtyj/agents/social/dm_agent.py:170` got a single-line em-dash strip (`reply.replace("—", ",")`) inside the existing post-process block — calvin-csa's WhatsApp/IG/FB DM replies will now have em-dashes substituted with commas before send, regardless of whether Claude follows the brand_voice_rule. (2) `wtyj/shared/state_registry.py:931` `wa_get_full_history()` now SELECTs and returns the row `id` alongside `role/text/created_at`. (3) `wtyj/dashboard/api.py:884` `get_conversation()` enriches each message dict with `content` (alias of `text`) and `timestamp` (alias of `created_at`) so SR's frontend at `Inbox.tsx:64` reads them correctly. (4) `wtyj/docs/project_open_work.md` got three new sections: HIGH PRIORITY Google Workspace email support (consolidated from main repo), Marina-is-not-a-template principle, and Brief 200 frontend-side follow-ups. Brief-reviewer FAIL round 1 (2 blocking: wrong mock paths, missing DASHBOARD_PASSWORD env setup), patches applied, PASS round 2.

## Tests
911 passing / 0 failures (baseline 907 + 4 new — em-dash replaced, em-dash absent passes through, wa_get_full_history returns id, get_conversation adds content/timestamp aliases via real DB+router integration).

## Unexpected findings
One small test-execution bug found during run: I wrote `state_registry.wa_save_message` in the brief and test file — the actual function name is `wa_store_message`. Fixed in both places before full regression. Single rename, 4 occurrences.

## Deployment
Brief commit will be `<source-sha>`. Standard deploy via the canary pipeline picks up the dm_agent + state_registry + dashboard changes — all 4 production containers + staging will rebuild on the same image. Post-deploy: re-test calvin-csa with em-dashes in his replies (manual), then click into a conversation in `dashboard.unboks.org` to verify message bubbles render with text + timestamps.
