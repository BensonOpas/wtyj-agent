# OUTPUT 149 — Structured agent_persona Config + operating_mode Alias

## What was done

### Code changes

- **`bluemarlin/agents/marina/marina_agent.py`**
  - Added `"agent_persona"` to `_SKIP_TOP_LEVEL` set with comment explaining why (prevents double injection via the auto-iterator in `_build_client_context`).
  - Added new `_build_agent_persona_block()` function (~55 lines) that reads `config_loader.get_raw().get("agent_persona", {})` and assembles a multi-section prompt block from 10 structured fields. Falls back to legacy `common_sense_knowledge.marina_persona` if the structured section is missing or empty.
  - Updated `_build_system_prompt` to replace `PERSONA: {csk.get('marina_persona', '')}` with `AGENT PERSONA:\n{_build_agent_persona_block()}`.

- **`bluemarlin/dashboard/api.py`**
  - Removed dead `csk = config_loader.get_common_sense_knowledge()` binding (no longer used after migration).
  - Replaced `persona = csk.get("marina_persona", "")` with `persona_block = marina_agent._build_agent_persona_block()` (uses the already-imported marina_agent module).
  - Updated the draft-email system prompt template from `PERSONA: {persona}` to `AGENT PERSONA:\n{persona_block}`.

### Config migrations

- **`bluemarlin/config/client.json`** (BlueFinn) — added new top-level `agent_persona` section with all 10 fields (tone, language_register, greeting_style, closing_style, brand_voice_rules as 7-item array, topics_allowed as 6-item array, topics_refused as 4-item array, small_talk, escalation_tone, freeform_notes). Added `business.operating_mode: "full_booking"`. Preserved legacy `common_sense_knowledge.marina_persona` as fallback.

- **`clients/adamus/config/client.json`** (Adamus) — added new top-level `agent_persona` section with restaurant-appropriate content for all 10 fields. Added `business.operating_mode: "full_booking"`. Preserved legacy `common_sense_knowledge.marina_persona` as fallback. Zero BlueFinn/BlueMarlin/charter references in the new persona content.

### Test file

- **`bluemarlin/tests/marina/test_149_agent_persona.py`** (new) — 19 tests covering:
  - Persona section presence (2)
  - All 10 fields populated in both clients (2)
  - Vocabulary consistency (BlueFinn mentions charter terms, Adamus mentions restaurant terms, Adamus has no BlueFinn references) (3)
  - operating_mode consistency with booking_flow (2)
  - Prompt block assembly (section headings, sample content) (1)
  - All array elements preserved in assembled block (brand_voice_rules, topics_allowed, topics_refused) (3)
  - Legacy fallback via monkeypatch (1)
  - Empty fields skipped cleanly (1)
  - System prompt injection (1)
  - marina_agent `_SKIP_TOP_LEVEL` constant guard (1)
  - Runtime verification that `_build_client_context()` does NOT contain `=== AGENT PERSONA ===` (1)
  - Dashboard migration source-text scan (1)

### Pre-existing test fix

- **`bluemarlin/tests/marina/test_marina_tone.py::test_client_context_includes_all_sections`** — this test hardcoded `skip = {"service_aliases"}` which is now out of sync with marina_agent's `_SKIP_TOP_LEVEL`. Changed to import the set directly from `marina_agent._SKIP_TOP_LEVEL` so the test stays in sync automatically with any future additions.

## Test results

### New tests (Brief 149)

All 19 pass:

```
test_bluefinn_client_json_has_agent_persona_section PASSED
test_adamus_client_json_has_agent_persona_section PASSED
test_bluefinn_agent_persona_has_all_10_fields PASSED
test_adamus_agent_persona_has_all_10_fields PASSED
test_bluefinn_persona_mentions_charter_vocabulary PASSED
test_adamus_persona_mentions_restaurant_vocabulary PASSED
test_adamus_persona_has_no_bluefinn_or_bluemarlin_references PASSED
test_bluefinn_operating_mode_matches_booking_flow PASSED
test_adamus_operating_mode_matches_booking_flow PASSED
test_build_agent_persona_block_assembles_bluefinn PASSED
test_build_agent_persona_block_contains_all_brand_rules PASSED
test_build_agent_persona_block_contains_all_allowed_topics PASSED
test_build_agent_persona_block_contains_all_refused_topics PASSED
test_build_agent_persona_block_fallback_to_legacy PASSED
test_build_agent_persona_block_skips_empty_fields PASSED
test_system_prompt_contains_agent_persona_section PASSED
test_marina_agent_skips_agent_persona_in_client_context PASSED
test_marina_build_client_context_does_not_contain_agent_persona PASSED
test_dashboard_draft_email_uses_structured_persona PASSED

============================== 19 passed in 0.29s ==============================
```

### Full regression

Before Brief 149: 681 passed / 7 pre-existing failures (688 total).
After Brief 149 (round 1): 699 passed / 8 failures — 1 new failure in `test_client_context_includes_all_sections`.
After test fix: **700 passed / 7 failures** (707 total).

The new failure was expected collateral: the test hardcoded `skip = {"service_aliases"}` which didn't include the new `agent_persona` skip entry. Fixed by importing `_SKIP_TOP_LEVEL` from marina_agent so future skip additions don't re-break this test.

The same 7 pre-existing failures (test_047 x5, test_048 x1, test_068 x1) remain unchanged. Zero NEW failures.

## Deployment

### BlueMarlin image rebuild + BlueFinn redeploy

```bash
ssh root@108.61.192.52 "cd /root && git pull && docker compose down && docker compose build && docker compose up -d"
```

New image `sha256:1b5ba469dd00...`. Container `bluemarlin-default` running on port 8001, health `{"status":"ok"}`.

### Adamus restart (uses the new image)

```bash
ssh root@108.61.192.52 "cd /root/clients/adamus && docker compose down && docker compose up -d"
```

Container `bluemarlin-adamus` running on port 8002, health `{"status":"ok"}`.

### Live persona verification — BlueFinn container

```
$ docker exec bluemarlin-default python3 -c '... marina_agent._build_agent_persona_block() ...'

Tone: warm, calm, practical, guest-aware
Language register: professional but approachable; match the sender's formality and language

Greeting style:
On the first message only, a brief warm hello. Don't announce yourself or over-introduce...

Closing style:
Brief and confident. No 'let me know if you need anything else' on every message...

Brand voice rules (MUST follow):
- Never use em-dashes or en-dashes
- Avoid 'I'd be happy to', 'Absolutely', 'Amazing', 'Great choice', 'Shall I'
[...truncated]
```

The new structured block is active, not the legacy fallback.

### Live persona verification — Adamus container

```
$ docker exec bluemarlin-adamus python3 -c '... marina_agent._build_agent_persona_block() ...'

Tone: warm, casual, beachy
Language register: informal and friendly; use first names, contractions are fine

Greeting style:
Simple hello on the first message only. Don't announce yourself, don't over-introduce...

Closing style:
Brief and relaxed. No 'let me know if you need anything else' on every message. Sign off as Sofia only on email.

Brand voice rules (MUST follow):
- Never use em-dashes or en-dashes
- Avoid 'I'd be happy to', 'Absolutely', 'Great choice'
- One exclamation mark per message maximum
[...truncated]
```

Distinct tone from BlueFinn. Distinct language register. Distinct brand voice rules (Adamus has "one exclamation mark per message maximum," BlueFinn doesn't). The two containers are reading their own structured personas, not sharing any.

## Unexpected / problems encountered

1. **Reviewer round 1 found 5 issues.** Four were valid and patched (double-injection via auto-iterator in both marina_agent and content_agent, dashboard/api.py second reader of marina_persona, 9-vs-10 field count inconsistency). The 5th was a minor rollback wording note, not addressed.

2. **Reviewer round 2 found 3 more issues** after the patches. Two were valid and fixed inline during execution:
   - Test 19 originally called `_build_system_prompt()`, but `_build_client_context()` is called from `_build_user_prompt()`, not the system prompt builder. So test 19 was decorative — it couldn't catch the regression it claimed to catch. Fixed: changed to call `_build_client_context()` directly and assert `=== AGENT PERSONA ===` is absent.
   - Dead `csk` binding in dashboard/api.py after the migration. Fixed by deleting the binding line.
   - The third issue (content_agent's `_SKIP_TOP_LEVEL` side effect on the dashboard `/config` endpoint) led me to REVERT the content_agent skip-list change entirely. Rationale: the dashboard `/config` view uses the same function, so skipping agent_persona would silently hide the new persona from operators. Brand voice rules transfer cleanly to social post generation anyway, and the token cost is marginal. Documented the decision in the brief.

3. **One pre-existing test broke** (`test_client_context_includes_all_sections`) because it hardcoded `skip = {"service_aliases"}`. Not a new failure — it was stale the moment we added to `_SKIP_TOP_LEVEL`. Fixed by importing the set directly from marina_agent so it tracks future additions automatically.

4. **Brief was extensively patched across both reviewer rounds.** Final brief has ~900 lines. Most patches were surgical — adding steps, updating test names, renaming "9 fields" to "10 fields" consistently.

## What this means functionally

Marina and Sofia now receive meaningfully different persona prompts instead of one vague line. Sofia is now "warm, casual, beachy" with "one exclamation mark per message maximum" and specific restaurant topic boundaries. Marina is "warm, calm, practical, guest-aware" with multilingual Caribbean knowledge and charter-specific topic handling. Both inherit from a shared 10-field schema that any future client can populate.

When a third client gets onboarded, all they need is a new `agent_persona` section in their client.json with their own tone, greeting style, voice rules, etc. No code changes required. The platform is genuinely client-agnostic at the voice layer now.

## Post-execution

- Committed as `823986c` on main
- Pushed to origin
- Deployed to VPS
- Both containers verified with distinct personas active
