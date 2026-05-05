# OUTPUT 203 — Wire agent_persona.freeform_notes injection in dm_agent + install SR's master prompt

## What was done
Two changes shipped together. (1) `wtyj/agents/social/dm_agent.py:_build_dm_system_prompt()` was refactored from a single hardcoded f-string into named structural blocks plus a conditional branch on `agent_persona.freeform_notes`. When the field is present, the master prompt replaces the hardcoded WRITING STYLE / AVOID blocks AND the "friendly, casual, and human" tone tail (single tone source — no contradictions). When absent, the fallback path is byte-equivalent to today's behavior. Structural blocks (services, FAQ, booking redirect, language line) stay in both modes. (2) `clients/unboks/config/client.json` → `agent_persona.freeform_notes` content was replaced with SR's master prompt verbatim (~17,400 chars), preserving the IDENTITY tail block from the older content. Brief-reviewer FAIL round 1 (3 issues: silent `(none configured)` empty-state change, hacky case-insensitive test assertion, unjustified "VOICE & BEHAVIOR:" wrapper). All three patched, PASS round 2. Output-reviewer pending.

## Tests
917 passing / 0 failures (baseline 913 + 4 new — master prompt mode replaces hardcoded blocks; master prompt mode keeps structural blocks; fallback mode preserves WRITING STYLE; end-to-end with em-dash post-process intact).

## Deployment
Source commit will be `<source-sha>`. Standard deploy via the canary pipeline rebuilds the shared image and restarts all 4 production containers + staging. Post-deploy verification: `docker exec wtyj-unboks python3` to confirm calvin-csa's rendered system prompt now contains "You are the Unboks AI assistant" and does NOT contain the hardcoded WRITING STYLE block. Real validation is the manual eyeball test against SR's per-Q&A "after" examples — send 3-5 prospect-style questions to calvin-csa via Calvin's WhatsApp, voice should match SR's spec.
