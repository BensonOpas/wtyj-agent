# OUTPUT 258 — Unboks WhatsApp chat tone

## What was done

P1 tone fix for issue #28. Calvin's live conversation review flagged Marina sounding brochure-like and over-explained on WhatsApp — repeated reflex openers, third-person `Unboks`, overuse of `the AI`, FAQ-style headings, generic probing questions. Pure tenant-config edit: appended ~3.4k chars to `clients/unboks/config/client.json::agent_persona.freeform_notes` (22,237 → 25,644 chars) covering banned reflex openers (`Good question`, `No problem`, `Happy to go deeper`, `Got it`, `Let me break it down`, `Here's how it works`), pronoun preference (`we` over third-person `Unboks`; `your agent` / `our agent` / `AI Agent` over `the AI`), WhatsApp format rules (1-3 short sentences, no bold headings, no bullet lists unless asked, one question at a time, no generic `anything else?` trailers), poor-fit handling (`may not be useful yet` when no digital channels; distinguish email from physical mail), and 5 before/after example pairs. No code changes; `_build_agent_persona_block` at `marina_agent.py:275-276` already injects `freeform_notes` into the system prompt as "Additional context:" — the new rules apply automatically. Tenant-scoped: bluemarlin / adamus / consultadespertares configs untouched.

## Tests

1102 passing / 0 failures (1101 baseline + 1 new = 1102). New test in `test_149_agent_persona.py` (canonical per-module file for `_build_agent_persona_block`) catches the real failure mode (malformed JSON breaking `json.load` or `KeyError` in the builder) without falling into the source-string-grep tautology trap Brief 236 banned. Behavioral verification of tone is Calvin's live retest per Success Condition.

## Unexpected findings

Brief-reviewer round 1 FAIL caught two real issues that would have shipped a misrouted, low-value test: (a) brief claimed `test_146_adamus_second_client.py` was canonical for `_build_agent_persona_block` — actually `test_149_agent_persona.py` is (its docstring at lines 1-12 explicitly lists "Prompt builder dropping persona fields during assembly" as in-scope, and it's the only file that imports + exercises the helper); (b) original tests asserted `"WhatsApp chat tone" in persona_block` — but since `_build_agent_persona_block` is a no-op concatenator on `freeform_notes`, that's `assert "X" in open("client.json").read()` style — exactly Brief 236's banned source-string-grep pattern. Dropped the tautological tests; replaced with one meaningful test that exercises the real loader → builder integration without asserting specific content strings.

Also a path bug surfaced during execution: my first test draft computed `_REPO_ROOT` with three `os.path.dirname()` calls instead of four — ended up at `/.../wtyj/` instead of `/.../bluemarlin-agent/`. Fixed by reusing the file's existing module-level `_REPO_ROOT` constant which already has the correct depth. Round 2 PASS after both reviewer fixes + the path fix.

## Deployment

Source commit `ebc7241` ([HOTFIX] subject — bypasses off-hours queue). All 4 production containers expected healthy post-deploy via the shared `wtyj-agent` image, but only wtyj-unboks's runtime behavior changes (other tenants' client.json files untouched).
