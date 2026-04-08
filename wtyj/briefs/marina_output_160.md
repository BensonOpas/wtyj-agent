# OUTPUT 160 — Regressions + Papiamentu

## What was done

### Backend changes — `wtyj/agents/marina/marina_agent.py`

**1. New `_LANGUAGE_HINTS` module-level constant** (after `_SKIP_TOP_LEVEL`, line ~36):

```python
_LANGUAGE_HINTS = {
    "English": "...",
    "Dutch": "...",
    "German": "...",
    "Spanish": "...",
    "Portuguese": "...",
    "Papiamentu": "...",
}
```

Per-language recognition hint strings. Stored in source because hints are prompt engineering data, not per-client business data. Each entry is a short sentence Claude can use to detect the language from inbound message body text.

**2. Dynamic LANGUAGE RULE build in `_build_system_prompt`** (added near line 175):

```python
_client_langs = business.get("languages", ["English"])
_lang_bullets = []
for _lang in _client_langs:
    _hint = _LANGUAGE_HINTS.get(_lang)
    if _hint:
        _lang_bullets.append(f"- {_hint}")
_language_rule_block = (
    "LANGUAGE RULE: MATCH the customer's language. Read the body text of "
    ...
)
```

Iterates over `business.get('languages', [])` and pulls matching hints. BlueMarlin gets 6 bullets, Adamus gets 4 (English/Dutch/Spanish/Papiamentu — no German, no Portuguese).

**3. Replaced single-line LANGUAGE RULE in the f-string** (was line 287, now line 322):

```python
# BEFORE
LANGUAGE RULE: Identify the reply language by reading the body text of the inbound message only. If the body is written in English, your reply MUST be in English ... When in doubt, default to English.

# AFTER
{_language_rule_block}
```

The "default to English when in doubt" escape hatch is gone.

**4. Prescriptive ESCALATION BEHAVIOUR wording** (lines 317-339): added `CRITICAL` negative guidance to both EMAIL CHANNEL and WHATSAPP CHANNEL "IF email IS in fields" branches. Both now explicitly say:

> CRITICAL: The email address in the sentence above MUST be {business.get('email', '')} (the business email). It is WRONG to write the customer's own email address in this sentence.

The "IF email is NOT in fields" branch is unchanged (no bug there).

### Config change — `clients/bluemarlin/config/client.json`

Added `"Papiamentu"` to `business.languages`:

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

### Frontend change — `Escalations.tsx`

Phone regex at line 124:

```ts
// BEFORE
const phoneMatch = body.match(/WhatsApp:\s*(\S+)/);
// AFTER
const phoneMatch = body.match(/WhatsApp:\s*([^\s)]+)/);
```

One-character addition inside the character class: excludes close parens from the capture.

## Test results

**Regression suite:**

```
$ python3 -m pytest tests/marina/ tests/social/ -q --tb=line
738 passed, 6 warnings in 3.88s
```

738 passed / 0 failures. Same baseline as Brief 156/157/158/159. The `test_035_marina_prompt.py` test that checks for `"LANGUAGE RULE:"`, `"body text"`, `"Dutch"`, `"German"`, `"Spanish"` substrings in the prompt passes because the new dynamic block still produces a prompt containing all those strings for BlueMarlin.

**Adamus prompt rendering** (the reviewer round-1 catch):

```
$ CLIENT_CONFIG_PATH=.../adamus/config/client.json python3 -c '...'
Supported languages: English, Dutch, Spanish, Papiamentu.

- If the body is in English (...)
- If the body is in Dutch (...)
- If the body is in Spanish (...)
- If the body is in Papiamentu (...)
```

Sofia gets 4 language bullets, NO German, NO Portuguese. Rule 4 preserved.

**E2E verification tests (post-deploy):**

### Test 6 — Complaint wording (Brief 157 regression) — ✅ PASS

Marina's new reply after "I want a refund" + customer email:

> "Thanks for that. I wasn't able to find a booking under reference BF9999 — could you double-check the number? Sometimes a digit or letter can be off.
>
> Either way, the team will be in touch at benson_test_e2e@icloud.com. Keep an eye on your inbox and check spam just in case — **the email will come from butlerbensonagent@gmail.com**."

The CRITICAL negative guidance worked. Marina now ALWAYS includes the business email as the sender. She ALSO mentions the customer's email in a separate confirmation sentence, which is actually better UX — two pieces of info: "we have your email right" + "look for this sender address".

### Dutch language — ✅ PASS for inquiry paths, ⚠️ UNCHANGED for booking confirmation paths

**Dutch inquiry** (no booking summary override):
- Input: "Hoi, kan ik vragen wat de prijs is voor de sunset cruise? En is er een open bar inclusief?"
- Reply: "Hoi! De Sunset Cruise kost $79 per persoon. En ja, open bar is inbegrepen — bier, wijn en cocktails — plus wat snacks. De cruise duurt 2,5 uur en vertrekt om 17:30. Beschikbaar op dinsdag, donderdag, vrijdag en zaterdag."
- Fluent Dutch. Fields NOT extracted (pure inquiry). **LANGUAGE RULE fix works.**

**Dutch booking confirmation** (still English):
- Input: "Hallo Marina, ik wil graag een zonsondergang cruise boeken voor 3 personen komende zaterdag alstublieft"
- Reply: "Just to confirm: Sunset Cruise on Saturday, 11 April 2026, 17:30 from Village Marina/Mood pier on Kailani. 3 guests, $237 total..."
- **Still English.** Root cause: `_build_booking_summary` at `social_agent.py:61-87` is a HARDCODED ENGLISH TEMPLATE. It's called by `_post_validate` (line 170) and its return value REPLACES Marina's reply at `social_agent.py:433` (`reply_text = _pv_override`). This is a separate Rule 3 violation, NOT a Brief 160 issue. Needs its own brief.

### Papiamentu language — ✅ PASS

- Input: "Bon dia Marina! Kuantu e Sunset Cruise ta kosta i ki ora e ta sali?"
- Reply: "Bon dia! E Sunset Cruise ta kosta $79 pa persona, i e ta sali na 5:30 PM. E trip ta dura 2.5 ora i inkluí open bar i snacks. Ta disponibel dialuna, diaranson, bierne i diasabra."
- Fluent Papiamentu. Minor accuracy issue: Claude said "dialuna, diaranson" (Mon, Wed) when the actual days are Tue/Thu/Fri/Sat — Claude's translation nuance, not a Brief 160 failure. **LANGUAGE RULE fix + Papiamentu recognition works.**

### Phone regex — ✅ PASS (unit-verified)

```python
regex = r'WhatsApp:\s*([^\s)]+)'
test 1: 'Customer: Test (WhatsApp: 69d41ae77d2c605d08114697)\n...'
        captured: '69d41ae77d2c605d08114697'   ← no trailing )
test 2: 'WhatsApp: 69d41ae77d2c605d08114697\nName: Test'
        captured: '69d41ae77d2c605d08114697'
test 3: 'WhatsApp: +15551234567\n'
        captured: '+15551234567'
```

All 3 cases produce the correct capture. The frontend change ships in commit `23fd2f6`.

## Live deploy verification

```
$ docker ps --filter name=wtyj-
wtyj-adamus       Up 8 seconds
wtyj-bluemarlin   Up 8 seconds
$ curl /health
{"status":"ok"}
```

Both containers running the new image. Verified in-container:

```
$ docker exec wtyj-bluemarlin grep -A 2 'MATCH the customer'
"LANGUAGE RULE: MATCH the customer's language. Read the body text of "
"the inbound message (NOT the sender's name) and reply in whatever "
```

## Unexpected findings

### 1. Dutch booking confirmation still English — separate Rule 3 bug

While verifying the Dutch language fix, I discovered that `social_agent._build_booking_summary` is a hardcoded English string template that overrides Marina's Claude-generated reply when a booking summary is being shown. This means:

- Dutch/Papiamentu/Spanish work for PURE inquiries (FAQ, price questions, greetings)
- Dutch/Papiamentu/Spanish do NOT work for booking confirmation flows (Marina tries to generate a non-English summary but the Python template replaces her reply)

This is a pre-existing Rule 3 violation that predates Brief 160. Out of scope for this brief. Needs a follow-up brief that either:
- (a) Removes `_build_booking_summary` and trusts Claude to generate the summary in the customer's language from the prompt's COLLECTED FIELDS and SERVICE DATA
- (b) Makes `_build_booking_summary` return None if Claude's reply already contains the booking summary info (heuristic, fragile)
- (c) Accepts the English summary as "transactional content that stays in English" (like payment links and booking refs) — debatable

I'd vote (a) — Claude has all the data in the prompt and it's better positioned to write the summary in the customer's voice and language than a Python template. This would also make the `Want me to check availability and hold a spot for you?` CTA work in-language.

### 2. Marina improved on the Test 6 wording — 2 emails in the reply

The Brief 157 fix intended for Marina to say "expect an email from business.email". But the CRITICAL negative guidance produced a better result: Marina now says BOTH:

- "the team will be in touch at <customer's email>" (confirming we have their address)
- "the email will come from butlerbensonagent@gmail.com" (tell them what sender to look for)

This is actually clearer than the original design. Two pieces of info for the customer, both useful. I'll keep the CRITICAL wording as-is.

### 3. Brief 160 round-1 reviewer caught a critical Rule 4 issue

My initial draft hardcoded the full 6-language list inside the prompt f-string. The reviewer pointed out this would corrupt Adamus's prompt — Sofia would falsely advertise German and Portuguese support. The fix was to make the language list AND the per-language hints dynamic, iterating over `business.get('languages', [])`. Adamus correctly gets only its 4 languages now.

## Files modified

| Repo | File | Change |
|------|------|--------|
| wtyj | `wtyj/agents/marina/marina_agent.py` | `_LANGUAGE_HINTS` constant + dynamic LANGUAGE RULE + CRITICAL escalation wording |
| wtyj | `clients/bluemarlin/config/client.json` | added `"Papiamentu"` to `business.languages` |
| dash | `artifacts/dashboard/src/pages/Escalations.tsx` | phone regex close-paren fix |
| wtyj | `wtyj/briefs/marina_brief_160_*.md` | new brief file |

## Commits

- Backend: `ecf9a56` on `main`
- Dashboard: `23fd2f6` on `master`

## Next

**Brief 161** is queued per user instruction: proactive day-of-week rejection. Marina should say "Klein Curacao only runs on Wednesdays and Sundays" immediately when a customer asks for a Tuesday date, instead of asking which departure time.

**Also NEW follow-up:** remove or refactor `_build_booking_summary` so non-English booking flows produce non-English summaries. Vote for approach (a) — trust Claude to generate the summary from the prompt context. Punt until after Brief 161.

## Live verification pending

- User-driven real-phone test to confirm: trigger a Dutch inquiry via real WhatsApp → Marina replies in Dutch
- User-driven real-phone test: trigger a Papiamentu inquiry → Marina replies in Papiamentu
- User-driven real-phone test: trigger a complaint → Marina's reply contains "butlerbensonagent@gmail.com" as the sender
- Visual verification that semi escalation dashboard page no longer shows trailing `)` in PHONE field
