# BRIEF 160 — Fix Brief 157/158 regressions + add Papiamentu language support

**Status:** Draft
**Files:**
- `wtyj/agents/marina/marina_agent.py` — make ESCALATION BEHAVIOUR wording prescriptive (Brief 157 regression) + rewrite LANGUAGE RULE (Dutch regression + Papiamentu add)
- `clients/bluemarlin/config/client.json` — add `"Papiamentu"` to `business.languages`
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Escalations.tsx` — fix phone regex to exclude trailing `)` (Brief 158 regression)

**Depends on:** Briefs 157, 158 (their regressions), live E2E test run that surfaced the bugs
**Blocks:** Demo-ready Phase 1 completion

---

## Context

The E2E test run I just completed (10 synthetic Zernio webhook scenarios) surfaced three regressions and one missing feature:

### Bug 1 — Brief 157 wording fix didn't actually work at runtime

Brief 157 updated the ESCALATION BEHAVIOUR prompt to tell Marina to say "expect an email from {business.get('email', '')}" instead of "follow up at their email". **I verified the rendered prompt inside the live container contains the correct text** (`expect an email from butlerbensonagent@gmail.com`). But Claude IGNORED the instruction.

Test 6 complaint scenario: customer says "I want a refund for my Klein Curacao trip" + "my email is benson_test_e2e@icloud.com". Marina's reply:

> "I've flagged this for the team and they'll follow up at **benson_test_e2e@icloud.com** shortly. Keep an eye on your inbox in case it lands in spam."

That's the CUSTOMER's email, not the business email. Claude is substituting the most contextually-prominent email address (from the COLLECTED FIELDS section of the prompt) instead of the literal `butlerbensonagent@gmail.com` in the instruction.

**Root cause:** the instruction is positive-only ("tell them to expect an email from X"). When Claude sees the customer's email in context, it pattern-matches "the email" with the customer's email and writes that. The prompt never says "do NOT use the customer's email here" — and Claude needs that negative constraint.

### Bug 2 — Brief 158 phone regex captures trailing `)`

Brief 158 changed the `parseEscalationBody` regex from `(\d+)` to `(\S+)` so it could capture Zernio's hex conversation_ids. But relay bodies use the format `(WhatsApp: 69d41ae...)` with parentheses, so the regex captures the closing paren too:

```
input: "Customer: E2E Test Customer (WhatsApp: e2e005eeeeeeeeeeeeeeeeee)\n"
regex: /WhatsApp:\s*(\S+)/
match: "e2e005eeeeeeeeeeeeeeeeee)"  ← trailing ) included
```

Dashboard would render `PHONE: e2e005eeeeeeeeeeeeeeeeee)` — cosmetic but ugly. Full escalations (`WhatsApp: id\n` without parens) are fine.

### Bug 3 — Language matching fails for Dutch

Test 9: customer wrote "Hallo, ik wil graag een sunset cruise boeken voor 2 personen vrijdag" (Dutch). Marina extracted the fields correctly (`sunset_cruise, 2026-04-10, 2 guests, hold created`) but the reply was in **English**:

> "Just to confirm: Sunset Cruise on Friday, 10 April 2026, 17:30 from Village Marina/Mood pier on Kailani. 4 guests, $316 total..."

The current LANGUAGE RULE (`marina_agent.py:287`) ends with "When in doubt, default to English." Claude is defaulting to English even though the Dutch is unambiguous. The rule's negative framing ("if the body is English, reply in English, otherwise use non-English if clearly written") is structured around defending against name-based language guessing but undershoots on "customer wrote in Dutch → reply in Dutch".

### Feature — Add Papiamentu support

User request: "add papiamientu, if thers not in claude, then get it somewhere". **Claude Sonnet 4.6 has excellent built-in Papiamentu.** I verified with a live test inside the container — 3 Papiamentu test messages (`Bon dia, mi ke bai Klein Curacao...`, `Kuantu e Sunset Cruise ta kosta?`, `Nan ta sirbi kumiendo na bordo...`). Claude produced fluent, natural Papiamentu replies with correct intent + field extraction for all three. Sample:

> Input: `Bon dia, mi ke bai Klein Curacao djadumingu pa 2 hende`
> Output: `Bon dia! Mi ke yudabo cu esei. E trip ta 8 oras, ku BBQ, bar habri, i snorkel gear inkluid. Sali 08:00 (BlueMarlin 2) of 08:30 (BlueMarlin 1) for di Jan Thiel Beach. Ki djadumingu bo tin na mente, i ki ora bo preferé sali?`

No external pack / glossary / phrasebook needed. Just:
1. Add `"Papiamentu"` to BlueMarlin's `business.languages` array in client.json
2. Update the LANGUAGE RULE to name Papiamentu explicitly so Claude knows it's a supported language AND give it a few recognition hints (common Papiamentu words like `bon dia`, `mi ke`, `djadumingu`, `kiko`, `pa`, `ku`)

---

## Why This Approach

### Bug 1 — prescriptive instruction with explicit negative guidance

The current instruction says only what Claude SHOULD do. I'll add what Claude MUST NOT do:
- Explicit "CRITICAL" callout
- Negative statement: "It is WRONG to write the customer's own email address in this sentence"
- Reaffirmation: "Even if the customer's email is in the COLLECTED FIELDS section of this prompt, it must NOT appear in your reply's 'expect an email from' sentence"

This is a known technique for overriding LLM pattern-matching: give Claude both the positive instruction AND the negative constraint. In my experience with Claude prompt engineering, simple positive instructions get overridden when context contains competing signals; negative constraints are more sticky.

**Why not rewrite the reply path to inject the address post-generation?** That violates Rule 2 (Python never reads/rewrites Claude's reply content). Prompt-based fix is the right pattern.

### Bug 2 — exclude `)` from the phone regex

One character change: `(\S+)` → `([^\s)]+)`. Matches any non-whitespace, non-close-paren character. Still captures Zernio hex IDs, still captures phone numbers, stops cleanly at both spaces and close parens.

**Why not `([a-zA-Z0-9+_-]+)`?** The negated character class is more permissive — future conversation ID formats (longer hex, UUIDs with hyphens, base64) would still work. The whitelist approach would need updates for any format change.

### Bug 3 — rewrite LANGUAGE RULE without the "default to English" escape hatch

Current rule has these problems:
1. "When in doubt, default to English" lets Claude bail to English for any non-trivial case
2. Doesn't list supported languages in a way Claude can recognize them
3. No positive framing — all the language is around "only use non-English if..."

New rule:
1. Positive framing first: "MATCH the customer's language"
2. Explicit list of supported languages
3. Recognition hints for the low-resource language (Papiamentu) so Claude doesn't misdetect it as Spanish or Portuguese
4. Only fall back to English when the body is ACTUALLY English, not as a default

### Feature — Papiamentu

Two changes:
- `client.json`: add `"Papiamentu"` between Portuguese and the closing bracket
- LANGUAGE RULE: add Papiamentu to the explicit list + a few recognition-hint words (since it's a low-resource language Claude might otherwise misclassify as Spanish)

### Out of scope

- **Proactive day-of-week rejection** (Test 2 incomplete) — deferred to Brief 161 per user instruction
- **Adamus client.json** — already has Papiamentu in its languages list, no change needed
- **Tests for the prompt changes** — prompt changes are tested by the E2E harness I built today. No pytest-level tests needed.
- **Adding Papiamentu to content_agent.py or dm_agent.py prompts** — not requested, and Papiamentu is primarily a customer-facing inbound language. Marina handles it; content generation stays in English.

---

## Source Material

### Current ESCALATION BEHAVIOUR section (marina_agent.py:317-339)

```
ESCALATION BEHAVIOUR:
When the intent is complaint, refund request, or cancellation:

EMAIL CHANNEL: Set requires_human to true. Your reply MUST:
- Acknowledge what the customer said warmly and with genuine empathy
- Tell them to expect an email from {business.get('email', '')} shortly — keep an eye on their inbox so it doesn't go to spam
- Ask for their booking reference if not already known — it helps the team look into it faster, but do not block the escalation on it
- Sign off warmly.

WHATSAPP CHANNEL: Check if an email address is in the collected fields.
- IF email IS in fields: set requires_human to true. Acknowledge warmly
  and tell them to expect an email from {business.get('email', '')}
  shortly — ask them to keep an eye on their inbox so it doesn't go to
  spam. If no booking_ref is in fields, also ask "Could you share your
  booking reference if you have one? It helps us look into this faster."
  but do NOT block the escalation on it.
- IF email is NOT in fields: do NOT set requires_human yet. Instead:
  - Acknowledge warmly
  - Ask for their email so the team can follow up
  - Also ask for their booking reference if they have one
  - Set needs_escalation_email to true in flags
  - Do NOT promise an email will come yet

In both cases: do NOT attempt to resolve the issue yourself.
```

### Current LANGUAGE RULE (marina_agent.py:287)

```
LANGUAGE RULE: Identify the reply language by reading the body text of the inbound message only. If the body is written in English, your reply MUST be in English — even if the sender has a German, Dutch, or other non-English name. Only use a non-English language if the body text itself is clearly written in that language. Supported languages: {', '.join(business.get('languages', []))}. When in doubt, default to English.
```

### Current phone regex (Escalations.tsx:124)

```ts
const phoneMatch = body.match(/WhatsApp:\s*(\S+)/);
```

### Current BlueMarlin languages (clients/bluemarlin/config/client.json)

```json
"languages": [
  "English",
  "Dutch",
  "German",
  "Spanish",
  "Portuguese"
],
```

### Live Papiamentu capability test (3 prompts) — all PASS

Test ran inside the container via `marina_agent.process_message(...)`:
1. `Bon dia, mi ke bai Klein Curacao djadumingu pa 2 hende` → fluent Papiamentu reply, intent=booking, fields extracted (klein_curacao, 2 guests)
2. `Kuantu e Sunset Cruise ta kosta?` → fluent Papiamentu reply with price ($79) and trip details
3. `Nan ta sirbi kumiendo na bordo di e boto?` → fluent Papiamentu reply detailing each trip's food/drinks

No external pack needed. Claude Sonnet 4.6's Papiamentu is production-quality for Marina's use cases.

---

## Instructions

### Step 1 — Read the files

- `wtyj/agents/marina/marina_agent.py` (lines 280-345 — covers both the LANGUAGE RULE at ~287 and the ESCALATION BEHAVIOUR at ~317)
- `clients/bluemarlin/config/client.json` (lines 1-25 — business block)
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Escalations.tsx` (lines 120-135 — `parseEscalationBody`)

### Step 2 — Rewrite the LANGUAGE RULE (marina_agent.py:287) — config-driven

**Critical constraint (caught by reviewer round 1):** Adamus's client.json has `["English", "Dutch", "Spanish", "Papiamentu"]` — no German, no Portuguese. Hardcoding all 6 languages in the prompt would have Sofia advertising German/Portuguese support to her customers, which is wrong. The language list AND the per-language recognition hints MUST be dynamically rendered from `business.get('languages', [])`.

**Approach:**
1. Define a module-level `_LANGUAGE_HINTS` dict in `marina_agent.py` (above `_build_system_prompt`) that maps language name → recognition hint string. This is prompt engineering data that lives in the source code (not per-client), same as the escalation instructions.
2. In `_build_system_prompt`, render the LANGUAGE RULE as a dynamic block that iterates over `business.get('languages', [])` and pulls the matching hint from `_LANGUAGE_HINTS`.
3. Only languages present in both `business.languages` AND `_LANGUAGE_HINTS` get rendered.

**Step 2a — Add `_LANGUAGE_HINTS` constant**

Add this near the top of `marina_agent.py`, after the existing imports and before `_build_client_context()` (around line 30-45, wherever module-level constants live):

```python
# Language recognition hints for the LANGUAGE RULE — Brief 160.
# Maps language name (matching client.json business.languages entries) to
# a short description of sample words Claude can use to detect the language
# from an inbound message body. Per-client language selection happens in
# _build_system_prompt by iterating over business.get('languages', []).
_LANGUAGE_HINTS = {
    "English": 'If the body is in English ("Hi", "I want", "please", "thanks"), reply in English.',
    "Dutch": 'If the body is in Dutch ("Hallo", "ik wil", "alstublieft", "graag", "bedankt", "morgen", "zondag"), reply in Dutch.',
    "German": 'If the body is in German ("Hallo", "ich möchte", "bitte", "danke"), reply in German.',
    "Spanish": 'If the body is in Spanish ("Hola", "quiero", "por favor", "mañana", "domingo"), reply in Spanish.',
    "Portuguese": 'If the body is in Portuguese ("Olá", "eu quero", "por favor", "obrigado"), reply in Portuguese.',
    "Papiamentu": 'If the body is in Papiamentu ("Bon dia", "Bon tardi", "mi ke", "mi por", "djadumingu", "djaluna", "kiko", "kuantu", "pa", "ku", "ta"), reply in Papiamentu. Papiamentu is the Creole spoken on Curaçao — it sounds similar to Spanish and Portuguese but has its own vocabulary and grammar. Do NOT misidentify it as Spanish.',
}
```

If a new client ever needs a language that isn't in `_LANGUAGE_HINTS`, the render silently skips that language's bullet. That's acceptable — the prompt will still mention "Supported languages: <list from config>" even if one is missing a hint.

**Step 2b — Build the LANGUAGE RULE dynamically in `_build_system_prompt`**

Find the section near line 287 that currently contains the `LANGUAGE RULE:` string inside the f-string. Replace the single-line rule with a dynamically-built multi-line block. BEFORE the f-string is assembled (at the top of `_build_system_prompt` where `business` and `terminology` are bound), add:

```python
    # Build the LANGUAGE RULE block from per-client supported languages
    _client_langs = business.get("languages", ["English"])
    _lang_bullets = []
    for _lang in _client_langs:
        _hint = _LANGUAGE_HINTS.get(_lang)
        if _hint:
            _lang_bullets.append(f"- {_hint}")
    _language_rule_block = (
        "LANGUAGE RULE: MATCH the customer's language. Read the body text of "
        "the inbound message (NOT the sender's name) and reply in whatever "
        f"language they used. Supported languages: {', '.join(_client_langs)}.\n\n"
        + "\n".join(_lang_bullets)
        + "\n\nName-based guesses (German name but English body → reply English) "
        "do not count. Read the body text only. Only fall back to English if "
        "the body is actually in English or is too short to identify (e.g. just "
        '"ok" or "yes" — use the language from the previous turn).'
    )
```

Then in the f-string where the current `LANGUAGE RULE:` line lives, replace the entire single line with `{_language_rule_block}`:

```python
# BEFORE (line 287, inside the f-string):
LANGUAGE RULE: Identify the reply language by reading the body text of the inbound message only. If the body is written in English, your reply MUST be in English — even if the sender has a German, Dutch, or other non-English name. Only use a non-English language if the body text itself is clearly written in that language. Supported languages: {', '.join(business.get('languages', []))}. When in doubt, default to English.

# AFTER:
{_language_rule_block}
```

**Why dynamic:** BlueMarlin gets English/Dutch/German/Spanish/Portuguese/Papiamentu bullets; Adamus gets English/Dutch/Spanish/Papiamentu bullets. Each client only sees the hints for their supported languages. Adding a new client language requires ONLY a client.json update (if the hint is already in `_LANGUAGE_HINTS`) or a one-line source addition (if it's a brand new language).

**What it produces for BlueMarlin:**
```
LANGUAGE RULE: MATCH the customer's language. Read the body text of the inbound message (NOT the sender's name) and reply in whatever language they used. Supported languages: English, Dutch, German, Spanish, Portuguese, Papiamentu.

- If the body is in English ("Hi", "I want", "please", "thanks"), reply in English.
- If the body is in Dutch ("Hallo", "ik wil", "alstublieft", "graag", "bedankt", "morgen", "zondag"), reply in Dutch.
- If the body is in German ("Hallo", "ich möchte", "bitte", "danke"), reply in German.
- If the body is in Spanish ("Hola", "quiero", "por favor", "mañana", "domingo"), reply in Spanish.
- If the body is in Portuguese ("Olá", "eu quero", "por favor", "obrigado"), reply in Portuguese.
- If the body is in Papiamentu ("Bon dia", "Bon tardi", "mi ke", "mi por", "djadumingu", "djaluna", "kiko", "kuantu", "pa", "ku", "ta"), reply in Papiamentu. Papiamentu is the Creole spoken on Curaçao — it sounds similar to Spanish and Portuguese but has its own vocabulary and grammar. Do NOT misidentify it as Spanish.

Name-based guesses (German name but English body → reply English) do not count. Read the body text only. Only fall back to English if the body is actually in English or is too short to identify (e.g. just "ok" or "yes" — use the language from the previous turn).
```

**What it produces for Adamus** (client.json `["English", "Dutch", "Spanish", "Papiamentu"]`):
```
LANGUAGE RULE: MATCH the customer's language. [...] Supported languages: English, Dutch, Spanish, Papiamentu.

- If the body is in English (...)...
- If the body is in Dutch (...)...
- If the body is in Spanish (...)...
- If the body is in Papiamentu (...)...

[footer]
```

Note: Adamus gets NO German or Portuguese bullet. That's the correctness fix the reviewer caught.

### Step 3 — Rewrite ESCALATION BEHAVIOUR (marina_agent.py:317-339)

Replace the current section with:

```
ESCALATION BEHAVIOUR:
When the intent is complaint, refund request, or cancellation:

EMAIL CHANNEL: Set requires_human to true. Your reply MUST:
- Acknowledge what the customer said warmly and with genuine empathy
- Tell them to expect an email from {business.get('email', '')} shortly — keep an eye on their inbox so it doesn't go to spam.
  CRITICAL: The address in the sentence above MUST be {business.get('email', '')} (the business email). It is WRONG to write the customer's own email address in this sentence. Even if the customer's email is in the COLLECTED FIELDS section of this prompt, it must NOT appear in your reply's "expect an email from" sentence — that sentence is about where OUR reply comes from, not where the customer is.
- Ask for their booking reference if not already known — it helps the team look into it faster, but do not block the escalation on it
- Sign off warmly.

WHATSAPP CHANNEL: Check if an email address is in the collected fields.
- IF email IS in fields: set requires_human to true. Acknowledge warmly
  and tell them to expect an email from {business.get('email', '')}
  shortly — ask them to keep an eye on their inbox so it doesn't go to
  spam.
  CRITICAL: The address in the sentence above MUST be {business.get('email', '')} (the business email). It is WRONG to write the customer's own email address in this sentence. The customer's email is in the COLLECTED FIELDS so the team knows where to send the reply — it should NOT appear in your "expect an email from" sentence, which is about OUR sending address.
  If no booking_ref is in fields, also ask "Could you share your
  booking reference if you have one? It helps us look into this faster."
  but do NOT block the escalation on it.
- IF email is NOT in fields: do NOT set requires_human yet. Instead:
  - Acknowledge warmly
  - Ask for their email so the team can follow up
  - Also ask for their booking reference if they have one
  - Set needs_escalation_email to true in flags
  - Do NOT promise an email will come yet

In both cases: do NOT attempt to resolve the issue yourself.
```

**Key changes:**
1. Added explicit `CRITICAL:` negative guidance to both EMAIL CHANNEL and WHATSAPP CHANNEL "IF email IS in fields" branches
2. Explained WHY using the customer's email is wrong (it's about sender, not recipient)
3. Preserved the existing positive instruction (template substitution of business.email unchanged)
4. "IF email is NOT in fields" branch unchanged — no bug there

### Step 4 — Add Papiamentu to BlueMarlin client.json

```json
"languages": [
  "English",
  "Dutch",
  "German",
  "Spanish",
  "Portuguese",
  "Papiamentu"
],
```

One-line addition. Adamus's client.json already has Papiamentu in its languages array (verified during Brief 150 and earlier).

### Step 5 — Fix phone regex in Escalations.tsx

Change line 124 from:
```ts
const phoneMatch = body.match(/WhatsApp:\s*(\S+)/);
```
to:
```ts
const phoneMatch = body.match(/WhatsApp:\s*([^\s)]+)/);
```

One-character addition: the character class `[^\s)]` matches any character that is NOT whitespace AND NOT a close paren. Stops cleanly at both.

### Step 6 — Run the marina + social regression suites

```bash
cd /Users/benson/Projects/bluemarlin-agent/wtyj
python3 -m pytest tests/marina/ tests/social/ -q --tb=line
```

Expected: 738 passing / 0 failures. The prompt wording changes don't affect any test because no test asserts the literal escalation reply text (verified in Brief 157 research).

### Step 7 — Commit + push both repos

```bash
# Backend
cd /Users/benson/Projects/bluemarlin-agent
git add wtyj/agents/marina/marina_agent.py clients/bluemarlin/config/client.json wtyj/briefs/marina_brief_160_regressions_and_papiamentu.md
git commit -m "Brief 160 — prescriptive escalation wording + language match + Papiamentu"
git push

# Dashboard
cd ~/Projects/wetakeyourjob-dashboard
git add artifacts/dashboard/src/pages/Escalations.tsx
git commit -m "Brief 160 — exclude close paren from phone regex"
git push
```

### Step 8 — Deploy backend to VPS

```bash
ssh root@108.61.192.52 "
  set -e
  cd /root && git pull
  cd /root/clients/bluemarlin && docker compose down
  cd /root/clients/adamus && docker compose down
  cd /root/clients/bluemarlin && docker compose build && docker compose up -d
  cd /root/clients/adamus && docker compose up -d
  sleep 8
  docker ps --filter name=wtyj- --format 'table {{.Names}}\t{{.Status}}'
"
```

### Step 9 — Re-run the E2E harness to verify fixes

The E2E harness from the earlier run is at `/tmp/e2e_runner.py`. Re-run the regressions + a new Papiamentu test:

**Re-run Test 6 (complaint wording):**
```bash
python3 /tmp/e2e_runner.py 6_complaint
sleep 15
# inspect — expect reply to contain "butlerbensonagent@gmail.com"
ssh root@108.61.192.52 "docker exec wtyj-bluemarlin python3 -c 'import sqlite3; c=sqlite3.connect(\"/app/data/state_registry.db\"); r=c.execute(\"SELECT text FROM whatsapp_threads WHERE phone=? AND role=? ORDER BY created_at DESC LIMIT 1\", (\"e2e006ffffffffffffffffff\",\"assistant\")).fetchone(); print(r[0] if r else \"(no reply)\")'"
```

**Re-run Test 9 (Dutch language):**
```bash
python3 /tmp/e2e_runner.py 9_dutch_language
sleep 15
# inspect — expect reply to contain Dutch words like "bevestig" or "boeking"
```

**New Test: Papiamentu booking** — add to the harness:
```python
"10_papiamentu": (
    "e2e010aaaaaaabbbbbbbccccc",
    ["Bon dia! Mi ke reservá un Sunset Cruise pa 2 hende djabierne"],
),
```
Run:
```bash
python3 /tmp/e2e_runner.py 10_papiamentu
sleep 15
# inspect — expect reply in Papiamentu
```

**Verify phone regex fix:** curl `/dashboard/api/escalations` and check that the `parsed.phone` simulation no longer has the trailing `)`:
```bash
# (re-use /tmp/inspect_escs.py with the regex applied in JS-equivalent Python)
```

For a quick Python verification:
```bash
python3 -c "
import re
body = 'Customer: E2E Test Customer (WhatsApp: e2e005eeeeeeeeeeeeeeeeee)\nTheir question: test'
print(re.search(r'WhatsApp:\s*([^\s)]+)', body).group(1))
"
# Expected output: e2e005eeeeeeeeeeeeeeeeee (NO trailing paren)
```

### Step 10 — Clean up test data

After re-running the E2E tests, wipe the e2e rows from the DB + any Google artifacts, same procedure as the earlier E2E run.

---

## Tests

No new automated tests. The E2E harness from the prior run is the test. Re-running Tests 6, 9, and the new Papiamentu test is the verification.

Existing marina + social regression suites (738 tests) must still pass — run in Step 6.

---

## Success Condition

**One sentence:** After deploy, Test 6 shows Marina's reply containing the literal string `butlerbensonagent@gmail.com` (not the customer's email), Test 9 shows Marina replying in Dutch (contains Dutch words), new Test 10 shows Marina replying in Papiamentu (contains Papiamentu words), the escalation detail page's parsed phone field no longer has a trailing `)` for any escalation type, AND Adamus's rendered LANGUAGE RULE contains ONLY the 4 languages it supports (no German, no Portuguese).

---

## Rollback

Each change is independent and revertible:

```bash
# Backend
cd /Users/benson/Projects/bluemarlin-agent
git revert <commit-sha>
# redeploy to VPS

# Dashboard
cd ~/Projects/wetakeyourjob-dashboard
git revert <commit-sha>
git push
```

The changes are all text-only inside prompts or a single regex character. Fully clean revert.

---

## Risks I want flagged before execution

1. **The prescriptive "CRITICAL" callout might still not be enough.** Claude's instruction-following is non-deterministic. If Test 6 STILL shows the customer's email after this fix, we need an even more aggressive approach (e.g. post-process the reply to replace the customer's email with the business email — but that violates Rule 2). Document the fallback path if the fix doesn't stick.

2. **Papiamentu recognition vs Spanish.** Papiamentu shares vocabulary with Spanish and Portuguese. Claude might misidentify short Papiamentu messages as Spanish. The recognition hints help but aren't bulletproof. If the user reports Marina responding in Spanish to Papiamentu, we'd need to either (a) add more hints or (b) rely on the content_agent/DM channel explicit language flag.

3. **Existing regression tests might cover escalation reply content** — the reviewer should grep for any test that asserts specific escalation reply text beyond the Brief 157 checks. I verified during Brief 157 that no test asserts the old wording; same grep should confirm for the new wording.

4. **The longer LANGUAGE RULE adds ~150 tokens to every prompt.** Prompt cost impact is minimal (~$0.00003 per message at Sonnet pricing). Acceptable.

5. **Claude might still respond in English on SHORT Papiamentu messages** like "Ki ora?" or "Kuantu?" because they're too short to confidently identify. The LANGUAGE RULE has a fallback clause for "too short — use the language from the previous turn" which handles this if there's conversation history. For greenfield "too short" messages, defaulting to English is acceptable.

6. **Adding Papiamentu to business.languages is client-specific** — Adamus already has it, BlueMarlin doesn't. The brief only touches BlueMarlin's client.json. If other future clients need it, that's a per-client config change, not a platform change.
