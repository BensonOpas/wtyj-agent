# BRIEF 149 — Structured agent_persona Config + operating_mode Alias

**Status:** Draft (patched after reviewer round 1)
**Files:** `bluemarlin/agents/marina/marina_agent.py`, `bluemarlin/agents/social/content_agent.py`, `bluemarlin/dashboard/api.py`, `bluemarlin/config/client.json` (BlueFinn), `clients/adamus/config/client.json` (Adamus), `bluemarlin/tests/marina/test_149_agent_persona.py` (new)
**Depends on:** None (independent)
**Blocks:** Nothing directly. Enables richer per-client voice customization going forward.

---

## Context

Today both BlueFinn and Adamus squeeze the entire agent personality into one free-text string in client.json:

```json
"common_sense_knowledge": {
  "marina_persona": "Marina is warm, calm, practical, and guest-aware..."
}
```

`marina_agent.py:224` reads it with `csk.get('marina_persona', '')` and injects it into the system prompt as a single line:

```
PERSONA: Marina is warm, calm, practical, and guest-aware...
```

Problems with this:
1. **Wrong name in the config key.** Adamus doesn't use Marina, it uses Sofia. The key `marina_persona` is a BlueMarlin-legacy mislabel.
2. **No structure.** Tone, greeting style, closing style, brand voice rules, allowed/refused topics, small-talk behaviour, and escalation tone are all jammed into one paragraph. Claude reads it, but there's no way for a client to selectively customize one dimension (e.g. "make Sofia more formal") without rewriting the entire blob.
3. **No taxonomy.** Every new client has to freestyle their own prose. No field is enforced or testable. A typo or omission is invisible.

Brief 149 introduces a structured `agent_persona` section with **10 discrete fields** (tone, language_register, greeting_style, closing_style, brand_voice_rules, topics_allowed, topics_refused, small_talk, escalation_tone, freeform_notes — the user's original 9 plus a `freeform_notes` safety valve for context that doesn't fit the other buckets). Updates the prompt builders in `marina_agent.py`, `content_agent.py`, and `dashboard/api.py` to read from the new section. Migrates both current clients to the new format. Backward compat is preserved — if `agent_persona` is missing, the old `common_sense_knowledge.marina_persona` string is still used.

Also adds a `business.operating_mode` field that is a human-readable alias for `features.booking_flow`. Values: `"full_booking"` (agent completes the reservation, calendar hold, payment if applicable) or `"qualify_and_escalate"` (agent collects info, answers FAQ, escalates to human for booking). Zero behavioural change — the actual code still reads `features.booking_flow`. The alias is documentation: when a future onboarder opens client.json they can see "what business model is this client" in one glance instead of inferring it from a boolean.

---

## Why This Approach

**Alternative considered: free-text with structured headers inside the string.** Something like `"tone: warm. greeting_style: simple hello. brand_voice_rules: no em-dashes, no absolutely..."` all mashed into one field. Rejected. Same problems as today — no validation, no testability, no selective editing, no type safety.

**Alternative considered: 9 top-level client.json fields (no `agent_persona` wrapper).** Rejected. Pollutes the client.json namespace. A dedicated section groups related fields and makes migration/validation easier.

**Alternative considered: rename `marina_persona` to `agent_persona` in `common_sense_knowledge` and keep it a single string.** Rejected. Doesn't solve the structure problem, only renames the legacy key. The user explicitly asked for structured fields.

**Alternative considered: replace `booking_flow` boolean with `operating_mode` string, removing the boolean entirely.** Rejected. Would require touching every code path that reads `features.booking_flow` (Brief 137 added that guard across email_poller, social_agent, dm_agent, webhook_server). High risk of breakage for a cosmetic change. Keep the boolean as the source of truth, add the string as a readability alias only.

**Chosen:** structured `agent_persona` section, alongside (not replacing) the old `common_sense_knowledge.marina_persona` field. New prompt builder assembles a multi-section block from the structured fields. If the structured section is missing, fall back to the legacy string. `business.operating_mode` is purely documentation; code still reads the boolean.

**Tradeoff accepted:** the old `marina_persona` key stays in `common_sense_knowledge` as a legacy fallback. Removing it would require scrubbing every backup client.json and every test that uses it. The key name is still wrong, but it's invisible to customers and only lives in the fallback code path. Cleanup can come later.

**Tradeoff accepted:** the 10 fields are a judgement call, not a spec. Clients who need more dimensions can still extend `freeform_notes`. Clients who need less can leave any field empty; the prompt builder skips empty fields in the assembled block.

**Critical side-effect to prevent (caught by reviewer round 1):** Both `marina_agent._build_client_context()` (line 45-76) and `content_agent._build_client_context()` (line 44) auto-iterate every top-level key in client.json and emit a `=== KEY NAME ===` section in the CLIENT DATA block of their prompts, unless the key is in `_SKIP_TOP_LEVEL`. Adding `agent_persona` as a new top-level section would cause double injection into Marina's prompt (once under `AGENT PERSONA:` via the new helper, again under `=== AGENT PERSONA ===` via the auto-iterator). For the content agent it would inject booking-agent voice rules into Instagram post generation — wrong context entirely. Fix: add `"agent_persona"` to `_SKIP_TOP_LEVEL` in BOTH files. The content agent does not need the persona at all — Instagram post voice is controlled by the existing `social_content` section.

**Critical second code path to migrate (caught by reviewer round 1):** `bluemarlin/dashboard/api.py` around line 1002 has its own inline draft-email prompt template (`persona = csk.get("marina_persona", "")` → `PERSONA: {persona}`). This is the dashboard's "draft an email" feature. Not touching it means the dashboard stays on the legacy single-line persona while Marina's real reply path uses the new structured block — two sources of truth drifting. Fix: migrate `dashboard/api.py` to import and call `_build_agent_persona_block()` from `marina_agent`, using the assembled multi-section block.

---

## Source Material

### Current `marina_agent._build_system_prompt()` line 222-226

```python
return f"""You are {business.get('agent_name', 'Marina')}, the booking agent for {business.get('name', 'the business')}.
{relay_mode_section}{fully_escalated_section}
PERSONA: {csk.get('marina_persona', '')}

{writing_style_block}
```

The `csk.get('marina_persona', '')` call is the single point of injection that Brief 149 replaces.

### BlueFinn's current persona text (`bluemarlin/config/client.json:105`)

```
Marina is warm, calm, practical, and guest-aware. She mirrors the sender's tone. She is human, clear, and never overexplains. She never guesses facts. If she does not know, she says so and offers to check.
```

Lives inside the `common_sense_knowledge` section alongside `curacao_timezone`, `currency`, `weather_season`, `dress_code`. The structured `agent_persona` will be a NEW top-level section. The legacy key stays where it is.

### Adamus's current persona text (`clients/adamus/config/client.json:116`)

```
Warm, casual, beachy. You work at a chill beach restaurant on Jan Thiel Beach. Keep it relaxed and welcoming. Your name is Sofia. Your business is Restaurant Adamus. You handle reservations for lunch and dinner seatings only — nothing else.
```

### Current `features.booking_flow` reads

Grep confirms `features.booking_flow` is read by: email_poller.py, marina_agent.py, social_agent.py, dm_agent.py, webhook_server.py. The new `business.operating_mode` alias will NOT be read by any of these — it's read-only documentation. The existing `features.booking_flow` boolean stays the source of truth.

### BlueFinn's current mode (derived)

`features.booking_flow: true` + `payment.timing: "upfront"` → full booking with payment link → maps to `operating_mode: "full_booking"`.

### Adamus's current mode (derived)

`features.booking_flow: true` + `payment.timing: "none"` → full booking, pay at venue → also maps to `operating_mode: "full_booking"`. The `payment.timing` distinguishes upfront vs at-venue within the same operating mode.

### What the 9 persona fields should look like for BlueFinn

Target values the brief will write into `bluemarlin/config/client.json`:

```json
"agent_persona": {
  "tone": "warm, calm, practical, guest-aware",
  "language_register": "professional but approachable; match the sender's formality and language",
  "greeting_style": "On the first message only, a brief warm hello. Don't announce yourself or over-introduce. On follow-ups in the same thread, skip the greeting entirely and just answer.",
  "closing_style": "Brief and confident. No 'let me know if you need anything else' on every message. Use an agent signature only on email.",
  "brand_voice_rules": [
    "Never use em-dashes or en-dashes",
    "Avoid 'I'd be happy to', 'Absolutely', 'Amazing', 'Great choice', 'Shall I'",
    "No decorative bold or bullet-heavy formatting",
    "No forced enthusiasm or exclamation marks beyond one per message",
    "Never reason out loud ('that means...', 'so that would be...')",
    "No name-dropping the customer at the end of sentences",
    "Emojis: only in booking confirmations, or if the customer used them first"
  ],
  "topics_allowed": [
    "Charter trip booking (availability, slots, party size, pricing)",
    "Trip details, inclusions, duration, what to bring",
    "Location, pickup, parking, directions",
    "Children, accessibility, dietary accommodations",
    "Weather, seasickness, safety",
    "Payment, cancellation, rescheduling"
  ],
  "topics_refused": [
    "Medical or legal advice",
    "Competitor recommendations or comparisons",
    "Discounts or price negotiation",
    "Anything unrelated to BlueFinn or Curaçao charter operations"
  ],
  "small_talk": "Polite and brief. Mirror the customer's energy — warm if they're warm, efficient if they're transactional. Don't force chatter if they want a direct answer.",
  "escalation_tone": "When escalating to the human team, be calm and factual. State what happened, what the customer needs, and that the team will follow up. No over-apologizing, no performative concern.",
  "freeform_notes": "You know Curaçao. You know the difference between Jan Thiel, Spanish Water, and Caracasbaai. You know Klein Curaçao takes 1h45 by catamaran. You speak or understand English, Dutch, German, Spanish, and Portuguese enough to respond in kind. You never guess facts — if you don't know, you say so and offer to check."
}
```

### What the 9 persona fields should look like for Adamus

Target values for `clients/adamus/config/client.json`:

```json
"agent_persona": {
  "tone": "warm, casual, beachy",
  "language_register": "informal and friendly; use first names, contractions are fine",
  "greeting_style": "Simple hello on the first message only. Don't announce yourself, don't over-introduce. On follow-ups in the same thread, skip the greeting and just answer.",
  "closing_style": "Brief and relaxed. No 'let me know if you need anything else' on every message. Sign off as Sofia only on email.",
  "brand_voice_rules": [
    "Never use em-dashes or en-dashes",
    "Avoid 'I'd be happy to', 'Absolutely', 'Great choice'",
    "One exclamation mark per message maximum",
    "No decorative bold or bullet-heavy formatting",
    "No forced enthusiasm",
    "Emojis sparingly — only in reservation confirmations or if the customer used them first"
  ],
  "topics_allowed": [
    "Reservations for lunch and dinner",
    "Menu details, dietary accommodations",
    "Location, parking, dress code",
    "Live music schedule",
    "Private events (qualify then escalate to owner)"
  ],
  "topics_refused": [
    "Medical or legal advice",
    "Competitor recommendations",
    "Price negotiation or discounts",
    "Anything unrelated to Restaurant Adamus"
  ],
  "small_talk": "Polite and brief. Match the customer's energy. A quick 'pleasure to hear from you' is fine for warm customers, skip it for transactional ones.",
  "escalation_tone": "When handing off to the owner, be calm and factual. Don't apologize excessively. Say the team will reach out shortly rather than over-performing concern.",
  "freeform_notes": "You work at a beach restaurant on Jan Thiel Beach in Curaçao. You speak English, Dutch, Spanish, and understand Papiamentu. Lunch is on the Main Terrace, dinner is on the Beach Deck. Fridays have live music starting 19:00. You never guess facts — if you don't know something, say so and offer to check with the team."
}
```

### The assembled prompt block (pseudocode for the new builder)

```python
def _build_agent_persona_block(persona: dict) -> str:
    lines = []
    if persona.get('tone'):
        lines.append(f"Tone: {persona['tone']}")
    if persona.get('language_register'):
        lines.append(f"Language register: {persona['language_register']}")
    if persona.get('greeting_style'):
        lines.append(f"\nGreeting style:\n{persona['greeting_style']}")
    if persona.get('closing_style'):
        lines.append(f"\nClosing style:\n{persona['closing_style']}")
    if persona.get('brand_voice_rules'):
        lines.append("\nBrand voice rules (MUST follow):")
        for rule in persona['brand_voice_rules']:
            lines.append(f"- {rule}")
    if persona.get('topics_allowed'):
        lines.append("\nTopics you handle:")
        for t in persona['topics_allowed']:
            lines.append(f"- {t}")
    if persona.get('topics_refused'):
        lines.append("\nTopics you refuse (politely redirect):")
        for t in persona['topics_refused']:
            lines.append(f"- {t}")
    if persona.get('small_talk'):
        lines.append(f"\nSmall talk:\n{persona['small_talk']}")
    if persona.get('escalation_tone'):
        lines.append(f"\nEscalation tone:\n{persona['escalation_tone']}")
    if persona.get('freeform_notes'):
        lines.append(f"\nAdditional context:\n{persona['freeform_notes']}")
    return "\n".join(lines)
```

The function returns an empty string if `persona` is empty. The caller falls back to the legacy `common_sense_knowledge.marina_persona` only if the assembled block is empty.

---

## Instructions

### Step 1 — Add persona assembly helper to `marina_agent.py`

In `bluemarlin/agents/marina/marina_agent.py`, near the top of the file but after imports, add a new module-level helper function:

```python
def _build_agent_persona_block() -> str:
    """Build the AGENT PERSONA prompt block from the structured agent_persona
    section in client.json. Falls back to the legacy common_sense_knowledge.marina_persona
    free-text string if the structured section is missing or empty.

    Brief 149.
    """
    persona = config_loader.get_raw().get("agent_persona", {})
    lines = []

    if persona.get("tone"):
        lines.append(f"Tone: {persona['tone']}")
    if persona.get("language_register"):
        lines.append(f"Language register: {persona['language_register']}")

    if persona.get("greeting_style"):
        lines.append(f"\nGreeting style:\n{persona['greeting_style']}")

    if persona.get("closing_style"):
        lines.append(f"\nClosing style:\n{persona['closing_style']}")

    rules = persona.get("brand_voice_rules") or []
    if rules:
        lines.append("\nBrand voice rules (MUST follow):")
        for rule in rules:
            lines.append(f"- {rule}")

    allowed = persona.get("topics_allowed") or []
    if allowed:
        lines.append("\nTopics you handle:")
        for t in allowed:
            lines.append(f"- {t}")

    refused = persona.get("topics_refused") or []
    if refused:
        lines.append("\nTopics you refuse (politely redirect without apology):")
        for t in refused:
            lines.append(f"- {t}")

    if persona.get("small_talk"):
        lines.append(f"\nSmall talk:\n{persona['small_talk']}")

    if persona.get("escalation_tone"):
        lines.append(f"\nEscalation tone:\n{persona['escalation_tone']}")

    if persona.get("freeform_notes"):
        lines.append(f"\nAdditional context:\n{persona['freeform_notes']}")

    if lines:
        return "\n".join(lines)

    # Legacy fallback — brief 149 backward compat
    legacy = config_loader.get_common_sense_knowledge().get("marina_persona", "")
    return legacy
```

Place this helper AFTER existing `_build_*` helpers but BEFORE `_build_system_prompt` (so it's defined when the system prompt builder calls it).

### Step 2 — Update `_build_system_prompt` to use the new helper

In `bluemarlin/agents/marina/marina_agent.py`, replace line 224:

```python
PERSONA: {csk.get('marina_persona', '')}
```

with:

```python
AGENT PERSONA:
{_build_agent_persona_block()}
```

No other changes to `_build_system_prompt`. The `csk = config_loader.get_common_sense_knowledge()` line at line 95 stays (other code reads other keys from that section). Only the persona-specific injection changes.

### Step 2b — Prevent double-injection in `marina_agent._build_client_context()`

In `bluemarlin/agents/marina/marina_agent.py` at line 31:

```python
_SKIP_TOP_LEVEL = {"service_aliases"}  # Already in system prompt via _build_service_alias_text()
```

Change to:

```python
_SKIP_TOP_LEVEL = {
    "service_aliases",      # Already in system prompt via _build_service_alias_text()
    "agent_persona",        # Already in system prompt via _build_agent_persona_block() — Brief 149
}
```

Why: without this, `_build_client_context()` auto-iterates top-level client.json keys and emits a `=== AGENT PERSONA ===` JSON dump inside the CLIENT DATA block, in addition to the structured text block produced by the helper. That's double injection — wastes tokens, risks contradictory phrasing.

### Step 2c — (REMOVED after reviewer round 2)

Originally this step added `agent_persona` to `content_agent._SKIP_TOP_LEVEL` to prevent booking-agent voice rules from leaking into social post generation. Removed because `dashboard/api.py:394` exposes `content_agent._build_client_context()` via a `/config` GET endpoint that operators use to inspect "what data does the agent see." Adding `agent_persona` to the skip list would silently hide the new persona section from that dashboard view.

Decision: leave `content_agent._SKIP_TOP_LEVEL` unchanged. The marginal cost is that social content generation will include the structured persona in its CLIENT DATA block — brand voice rules like "never use em-dashes" transfer cleanly to social posts, topic rules are mostly neutral, and the small token cost is acceptable. If this ever causes a real problem, add a dedicated skip list inside content_agent's Claude-call path (separate from the dashboard-exposed helper).

No code changes in this step.

### Step 2d — Migrate `dashboard/api.py` draft-email endpoint to use the helper

In `bluemarlin/dashboard/api.py`, the draft-email endpoint around line 992-1024 currently reads `persona = csk.get("marina_persona", "")` and builds its own system prompt with `PERSONA: {persona}`. Migrate it to use the new helper.

Find the line (~1002):

```python
persona = csk.get("marina_persona", "")
```

Replace with:

```python
persona_block = marina_agent._build_agent_persona_block()
```

(`dashboard/api.py` already imports `marina_agent` at line ~22; use that. Don't add a new import.)

Then find the system prompt template (~1006):

```python
PERSONA: {persona}
```

Replace with:

```python
AGENT PERSONA:
{persona_block}
```

**Also delete the dead `csk` binding.** After the above change, the variable `csk` (bound at line ~972 via `csk = config_loader.get_common_sense_knowledge()`) is no longer used inside this function. Find that line and delete it. Verify no other line in the function still references `csk` before deletion.

The semantic is: dashboard's draft-email feature now produces drafts using the same structured persona as Marina's live email replies. One source of truth.

### Step 3 — Migrate BlueFinn's `client.json`

In `bluemarlin/config/client.json`, add a new top-level section `agent_persona` BEFORE the existing `common_sense_knowledge` section. Use the exact content from the Source Material section above. Also add `operating_mode` to the `business` section.

The `business` section currently ends with:

```json
"support_email": "butlerbensonagent@gmail.com",
"demo_support_email": "butlerbensonagent@gmail.com"
```

Add before the closing brace:

```json
"operating_mode": "full_booking"
```

Do NOT remove or modify the existing `common_sense_knowledge.marina_persona` field. It stays as the legacy fallback.

Do NOT modify any other fields in BlueFinn's client.json.

### Step 4 — Migrate Adamus's `client.json`

In `clients/adamus/config/client.json`, add a new top-level section `agent_persona` BEFORE the existing `common_sense_knowledge` section. Use the exact Adamus content from the Source Material section above. Also add `operating_mode` to the `business` section.

Adamus's `business` section currently ends with:

```json
"spreadsheet_id": "1OYtPI5Fn7btaPROsJgtpXnoWR025cbjHWudHx2a8ggc",
"support_email": "butlerbensonagent@gmail.com"
```

Add before the closing brace:

```json
"operating_mode": "full_booking"
```

Do NOT remove the existing `common_sense_knowledge.marina_persona` field in Adamus. It stays as legacy fallback.

### Step 5 — Write the tests

Create `bluemarlin/tests/marina/test_149_agent_persona.py` with the following tests. Use the same pattern as Brief 148 — read files from disk, parse JSON, assert content.

1. `test_bluefinn_client_json_has_agent_persona_section` — load BlueFinn's client.json, assert top-level `agent_persona` key exists and is a dict.

2. `test_adamus_client_json_has_agent_persona_section` — same for Adamus.

3. `test_bluefinn_agent_persona_has_all_10_fields` — assert all of `tone`, `language_register`, `greeting_style`, `closing_style`, `brand_voice_rules`, `topics_allowed`, `topics_refused`, `small_talk`, `escalation_tone`, `freeform_notes` exist and are non-empty.

4. `test_adamus_agent_persona_has_all_10_fields` — same for Adamus.

5. `test_bluefinn_persona_mentions_charter_vocabulary` — assert BlueFinn's `freeform_notes` or `topics_allowed` contain at least one of: `charter`, `catamaran`, `Klein Curaçao`, `trip` (case-insensitive). Guards against copy-paste of Adamus's persona.

6. `test_adamus_persona_mentions_restaurant_vocabulary` — assert Adamus's `freeform_notes` or `topics_allowed` contain at least one of: `restaurant`, `lunch`, `dinner`, `reservation`, `terrace`, `beach` (case-insensitive).

7. `test_adamus_persona_has_no_bluemarlin_references` — load Adamus as text, assert `BlueFinn`, `bluefinn`, `charter`, `Charter`, `BlueMarlin`, `bluemarlin` do NOT appear anywhere in the file (with the single carve-out that `marina_persona` as a key name is still allowed inside `common_sense_knowledge`). Uses the same stripping pattern as Brief 146 test 11.

8. `test_bluefinn_operating_mode_is_full_booking` — assert `business.operating_mode == "full_booking"` AND assert it matches `features.booking_flow == true` (consistency check).

9. `test_adamus_operating_mode_is_full_booking` — same pattern.

10. `test_build_agent_persona_block_assembles_bluefinn` — import `marina_agent`, call `_build_agent_persona_block()` (BlueFinn is the default-loaded config), assert the returned string contains `Tone:`, `Language register:`, `Greeting style:`, `Brand voice rules`, `Topics you handle:`, `Topics you refuse`, `Small talk:`, `Escalation tone:`, `Additional context:`, AND at least one of BlueFinn's brand voice rules (e.g. "Never use em-dashes"), AND at least one allowed topic (e.g. "Charter trip booking").

11. `test_build_agent_persona_block_contains_all_brand_rules` — assert the assembled block contains every string in BlueFinn's `brand_voice_rules` array. Catches a future refactor that silently drops one.

12. `test_build_agent_persona_block_contains_all_allowed_topics` — same for `topics_allowed`.

13. `test_build_agent_persona_block_contains_all_refused_topics` — same for `topics_refused`.

14. `test_build_agent_persona_block_fallback_to_legacy` — monkeypatch `config_loader.get_raw` to return `{}` (no agent_persona), monkeypatch `config_loader.get_common_sense_knowledge` to return `{"marina_persona": "LEGACY SENTINEL VALUE"}`. Call `_build_agent_persona_block()`. Assert the return value equals `"LEGACY SENTINEL VALUE"` (the legacy fallback path fires).

15. `test_build_agent_persona_block_skips_empty_fields` — monkeypatch `config_loader.get_raw` to return `{"agent_persona": {"tone": "warm", "topics_allowed": ["one", "two"]}}`. Call `_build_agent_persona_block()`. Assert the result contains `Tone: warm` and `one` and `two` but does NOT contain `Language register:` or `Greeting style:` (empty fields are skipped, no empty-section headers).

16. `test_system_prompt_contains_agent_persona_section` — call `marina_agent._build_system_prompt({}, channel="email")`. Assert the returned prompt contains `AGENT PERSONA:` AND contains the string `Tone: warm, calm, practical` (BlueFinn's tone). Verifies the system prompt actually injects the structured block.

17. `test_marina_agent_skips_agent_persona_in_client_context` — import `marina_agent`, assert `"agent_persona" in marina_agent._SKIP_TOP_LEVEL`. Catches a future refactor that silently drops the skip entry and re-introduces the double-injection bug at the constant level.

18. `test_marina_build_client_context_does_not_contain_agent_persona` — call `marina_agent._build_client_context()` directly. Assert the returned string does NOT contain `=== AGENT PERSONA ===`. This exercises the actual loop body (not just the constant) so a future refactor that drops the `if key in _SKIP_TOP_LEVEL` check inside the loop would still fail this test. `_build_client_context()` takes no arguments, reads `config_loader.get_raw()` directly — should return the full auto-iterated CLIENT DATA block WITHOUT the persona section.

19. `test_dashboard_draft_email_uses_structured_persona` — read `bluemarlin/dashboard/api.py` as text. Assert it contains `_build_agent_persona_block` (the function call). Assert it does NOT contain `persona = csk.get("marina_persona"` as a substring (the old pattern). Simple regression guard — doesn't actually invoke the draft-email endpoint since it would require FastAPI test setup.

Tests 14 and 15 must use `monkeypatch` + `importlib.reload(marina_agent)` OR directly monkeypatch the module-level `config_loader` import. Use whichever pattern is cleaner. Teardown should restore the real config so later tests don't see sentinel values.

### Step 6 — Run tests locally

```bash
cd /Users/benson/Projects/bluemarlin-agent/bluemarlin
python3 -m pytest tests/marina/test_149_agent_persona.py -v
```

All 16 must pass. Then run full regression:

```bash
python3 -m pytest tests/ -q --tb=no
```

Expected: 681 + 19 = 700 total passed. Same 7 pre-existing failures unchanged.

### Step 7 — Commit

```bash
git add -A
git commit -m "Brief 149 — Structured agent_persona config + operating_mode alias"
# Push manually due to security hook
```

### Step 8 — Deploy to VPS

```bash
ssh root@108.61.192.52 "cd /root && git pull && docker compose down && docker compose build && docker compose up -d"
ssh root@108.61.192.52 "sleep 10 && docker compose ps && curl -s http://localhost:8001/health"
```

### Step 9 — Verify new persona is active in BlueFinn container

```bash
ssh root@108.61.192.52 "docker exec bluemarlin-default python3 -c '
import sys
sys.path.insert(0, \"/app\")
from agents.marina import marina_agent
block = marina_agent._build_agent_persona_block()
print(block[:500])
'"
```

Expected: output begins with `Tone: warm, calm, practical, guest-aware` followed by subsequent sections. If the output is the legacy single-line string (`Marina is warm, calm, practical, and guest-aware...`) then the migration didn't take effect in the running container.

### Step 10 — Restart Adamus and verify its persona

```bash
ssh root@108.61.192.52 "cd /root/clients/adamus && docker compose down && docker compose up -d && sleep 8 && curl -s http://localhost:8002/health"
ssh root@108.61.192.52 "docker exec bluemarlin-adamus python3 -c '
import sys
sys.path.insert(0, \"/app\")
from agents.marina import marina_agent
block = marina_agent._build_agent_persona_block()
print(block[:500])
'"
```

Expected: output begins with `Tone: warm, casual, beachy` (NOT BlueFinn's tone).

### Step 11 — Final health check

```bash
ssh root@108.61.192.52 "curl -s http://localhost:8001/health && echo && curl -s http://localhost:8002/health"
```

Both must return `{"status":"ok"}`.

---

## Tests

See Step 5. Nineteen tests covering: persona section presence, all 10 fields populated in both clients, vocabulary consistency, no BlueMarlin references, operating_mode consistency, prompt block assembly, all array elements preserved, legacy fallback, empty-field skipping, system prompt integration, marina_agent `_SKIP_TOP_LEVEL` guard at both constant level and loop-body level, and dashboard migration.

---

## Success Condition

Both client.jsons contain a valid `agent_persona` section with all 10 fields. `marina_agent._build_agent_persona_block()` assembles a structured multi-section prompt block from those fields. `_build_system_prompt()` injects that block under the `AGENT PERSONA:` heading exactly once (no double injection from `_build_client_context()`'s auto-iterator in marina_agent). `dashboard/api.py` draft-email endpoint uses `_build_agent_persona_block()` instead of the legacy string. BlueFinn and Adamus running in production both have their container-side `_build_agent_persona_block()` return the new structured block (not the legacy fallback). Both client.jsons have `business.operating_mode: "full_booking"`. All 19 new tests pass, full regression clean, 700 total passed.

---

## Rollback

**If the prompt builder breaks marina_agent on the live container:**

```bash
ssh root@108.61.192.52 "cd /root && git revert HEAD && docker compose down && docker compose build && docker compose up -d"
```

Reverts `marina_agent.py`, both `client.json` files, and the test file in one commit. Marina and Sofia return to the legacy single-line persona string.

**If only the config migration is broken (JSON parse error):**

The `config_loader._load()` function catches exceptions and returns `{}`. So a malformed client.json would silently empty the config, leaving every prompt with no persona and no business data. This would be visible within 30 seconds (email poller heartbeat). Revert immediately.

**If tests fail locally:**

Don't deploy. Fix tests/code, re-run until green.
