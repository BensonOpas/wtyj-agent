# BRIEF 157 — Marina full-escalation reply: point customer at business owner's email

**Status:** Draft
**Files:** `wtyj/agents/marina/marina_agent.py` (ESCALATION BEHAVIOUR prompt section, lines 317-345)
**Depends on:** Brief 141 (booking_email field), Brief 156 (per-platform caption)
**Blocks:** Nothing — purely a wording fix

---

## Context

User reported the actual reply Marina sent to a real customer who escalated:

> "Thank you, Calvin. The team will follow up at **benson_agent@icloud.com**.
>
> If you have a booking reference handy, feel free to share it — it'll help them pull up the details faster."

`benson_agent@icloud.com` is the customer's own email address. Marina is literally telling the customer their own address back at them. This is technically accurate but useless — what the customer actually needs to know is **which address WE will email them FROM** so they:
1. Know to expect a real reply
2. Don't mark it as spam
3. Can search their inbox for it

This is a prompt bug, not a code bug. Lines 322 and 328-329 of `marina_agent.py` literally say:
- (EMAIL CHANNEL) `Tell them the team will follow up via email`
- (WHATSAPP CHANNEL with email present) `tell them the team will reach out at their email`

Claude correctly interprets "their email" as "the customer's address" and writes that into the reply.

The fix is to change the prompt to direct Marina to tell the customer they'll receive an email **from** the business owner's address (`business.email` from client.json), and to inject the actual address into the prompt at template build time so Claude sees the literal value, not a placeholder.

User confirmed which field to use:

> "it should point to the original business owners email, so marina acts basically as a filter, and real important stuff get to the original email filtered"

→ pull from `business.email`. (For BlueMarlin demo this resolves to `butlerbensonagent@gmail.com`.)

## Why This Approach

**Single edit, single file, single concern.** The prompt already template-substitutes `business.get('email', '')` at line 341 (the CONTACT INFO RULE) — same mechanism applies cleanly to the escalation instructions. No new code, no schema changes, no frontend work, no test changes.

**Why not just edit `marina_agent` post-process to rewrite "at their email" → "from <business.email>"?** Reframing in Python after Claude generates the reply violates Rule 2 (Python routes on structured values, never reads or rewrites reply content). Fix the prompt, let Claude generate the right text.

**Why not also add the business phone number / address?** Out of scope. User asked for the email pointer specifically. Don't add extra contact info unless asked.

**Why not also fix the EMAIL CHANNEL branch the same way?** It IS being fixed. The current EMAIL CHANNEL line says "Tell them the team will follow up via email" — vague enough that Claude already produces something like "we'll email you back". But for consistency and to lock in the correct address, the EMAIL CHANNEL branch gets the same explicit `from {email}` substitution.

### Out of scope (for follow-up briefs)

- **Display bugs on the dashboard escalations page** — Brief 158 (next): `PHONE: 69` truncation, semi escalation missing body, REASON field showing customer name
- **Relay flow not closing** — Brief 159: operator answer → Marina → customer relay path is broken
- **Adding business phone or other contact info to the reply** — not requested

---

## Source Material

### Current escalation prompt section (`marina_agent.py:317-345`)

```
ESCALATION BEHAVIOUR:
When the intent is complaint, refund request, or cancellation:

EMAIL CHANNEL: Set requires_human to true. Your reply MUST:
- Acknowledge what the customer said warmly and with genuine empathy
- Tell them the team will follow up via email
- Ask for their booking reference if not already known — it helps the team look into it faster, but do not block the escalation on it
- Sign off warmly.

WHATSAPP CHANNEL: Check if an email address is in the collected fields.
- IF email IS in fields: set requires_human to true. Acknowledge warmly
  and tell them the team will reach out at their email. If no booking_ref
  is in fields, also ask "Could you share your booking reference if you
  have one? It helps us look into this faster." but do NOT block the
  escalation on it.
- IF email is NOT in fields: do NOT set requires_human yet. Instead:
  - Acknowledge warmly
  - Ask for their email so the team can follow up
  - Also ask for their booking reference if they have one
  - Set needs_escalation_email to true in flags
  - Do NOT promise an email will come yet

In both cases: do NOT attempt to resolve the issue yourself.

CONTACT INFO RULE: {business.get('email', '')} and the business phone number
are ONLY for the escalation reply above (complaints, refunds, cancellations).
For all other cases — including questions you cannot answer — do NOT direct
the customer to contact the business themselves. Use semi_escalation instead.
```

### Existing template substitution pattern

`marina_agent.py:152` binds `business = config_loader.get_business()` inside `_build_system_prompt`. The prompt is an f-string, so `{business.get('email', '')}` substitutes the literal value at build time. Line 341 already does this for the CONTACT INFO RULE — proven pattern, reuse.

### Live proof Claude is following the prompt literally

User-quoted reply: `"Thank you, Calvin. The team will follow up at benson_agent@icloud.com."` — `benson_agent@icloud.com` was the customer's own email (`from_email` in the inbound message). Claude interpreted "at their email" → "at the customer's address". Fix the prompt phrasing, problem goes away.

---

## Instructions

### Step 1 — Read the file before editing

`wtyj/agents/marina/marina_agent.py` lines 150-345 (covers the function signature, business/terminology binding, the prompt template, and the escalation section).

### Step 2 — Replace the ESCALATION BEHAVIOUR section

Find the block starting at line 317 (`ESCALATION BEHAVIOUR:`) and ending at line 339 (`In both cases: do NOT attempt to resolve the issue yourself.`). Replace with:

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

**Key changes:**
1. EMAIL CHANNEL bullet 2: `Tell them the team will follow up via email` → `Tell them to expect an email from {business.get('email', '')} shortly — keep an eye on their inbox so it doesn't go to spam`
2. WHATSAPP CHANNEL "IF email IS in fields" bullet: `tell them the team will reach out at their email` → `tell them to expect an email from {business.get('email', '')} shortly — ask them to keep an eye on their inbox so it doesn't go to spam`
3. Everything else stays IDENTICAL — same booking ref ask, same NOT promising, same warm sign-off.

The "IF email is NOT in fields" branch does NOT change — Marina is asking for the email at that point and shouldn't preemptively name the business email until the customer has provided their own.

### Step 3 — Verify the prompt builds without errors

```bash
cd /Users/benson/Projects/bluemarlin-agent/wtyj
python3 -c "
import os
os.environ.setdefault('ANTHROPIC_API_KEY', 'test')
os.environ.setdefault('CLIENT_CONFIG_PATH', '../clients/bluemarlin/config/client.json')
import sys
sys.path.insert(0, '.')
from agents.marina import marina_agent
prompt = marina_agent._build_system_prompt({}, channel='email')
# Sanity: the literal business.email value should appear in the prompt
assert 'butlerbensonagent@gmail.com' in prompt, 'business email not substituted'
# And the phrase should be present in the new wording
assert 'expect an email from' in prompt, 'new wording not present'
# And the OLD bad phrasing should be GONE
assert 'reach out at their email' not in prompt, 'old wording still present'
assert 'follow up via email' not in prompt, 'old EMAIL channel wording still present'
print('OK: prompt builds, new wording present, old wording gone')
"
```

Expected output: `OK: prompt builds, new wording present, old wording gone`.

### Step 4 — Run the marina test suite to make sure no test asserts the old wording

```bash
python3 -m pytest tests/marina/ -q --tb=line
```

If any test asserts `"follow up via email"` or `"reach out at their email"` literally, it will fail. Inspect and either update the assertion to match the new wording or fix the test fixture. Most marina tests assert STRUCTURED output (intents, fields, flags) not literal reply text, so this is unlikely to break things — but verify.

**Note (verified by reviewer):** `wtyj/tests/social/test_100_email_collection.py` and `wtyj/tests/social/test_128_escalation_subject.py` contain the phrases "follow up" and "reach out at" inside MOCKED Claude reply fixtures (stub inputs simulating Claude's output to test downstream Python routing). These are NOT assertions about the production prompt — they do not need updating. Skip them during the inspection.

### Step 5 — Run the social regression suite (changes to marina_agent affect both channels)

```bash
python3 -m pytest tests/social/ -q --tb=line
```

Expected: same pass count as Brief 156 (351 social tests). If `test_073_whatsapp_hardening::test_change_detection_cancels_hold` fails on stale data, clean it via the same one-liner from Brief 156 and re-run.

### Step 6 — Commit + push

```bash
cd /Users/benson/Projects/bluemarlin-agent
git add wtyj/agents/marina/marina_agent.py wtyj/briefs/marina_brief_157_escalation_reply_wording.md
git commit -m "Brief 157 — Marina full-escalation reply points to business.email"
git push
```

### Step 7 — Deploy backend to VPS

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

### Step 8 — Live verification (user-driven)

The user triggers an escalation via WhatsApp by sending a complaint to BlueMarlin (e.g. "I want a refund, my trip was bad"). Confirm:
1. Marina asks for the customer's email if not already known
2. Once the email is provided, Marina's reply includes the literal phrase "expect an email from butlerbensonagent@gmail.com" (or whatever `business.email` is in client.json) — NOT the customer's own email address
3. The escalation row appears in the dashboard
4. (Out of scope for this brief — Brief 158 will fix the dashboard display bugs separately)

Same drill for email channel: send a complaint email to BlueMarlin's polled inbox, confirm the auto-reply mentions the business email as the source of follow-up, not the sender's own address.

---

## Tests

No new automated tests. The verification is the inline prompt-build assertion in Step 3 + the manual live test in Step 8.

Reasoning: this is a pure prompt wording change with no structural behavior change. There's no schema, no new code path, no integration to test. Adding a test that asserts the literal wording in the prompt string would just re-state the change in test form (the brief itself already does that via the Step 3 assertions). Adding a test that mocks Claude and asserts the reply contains the business email would be brittle (LLM output is non-deterministic).

The marina + social regression suites will catch any unintended structural breakage.

---

## Success Condition

**One sentence:** When a customer escalates a complaint via WhatsApp or email, Marina's reply explicitly tells them to expect an email from `business.email` (the business owner's address) and NOT from their own email address.

---

## Rollback

```bash
cd /Users/benson/Projects/bluemarlin-agent
git revert <commit-sha>
ssh root@108.61.192.52 "cd /root && git pull && cd /root/clients/bluemarlin && docker compose down && docker compose build && docker compose up -d && cd /root/clients/adamus && docker compose down && docker compose up -d"
```

The change is text-only inside an f-string in a single function. Revert is fully clean.

---

## Risks I want flagged before execution

1. **`business.email` could be empty for some clients.** If a client's `client.json` has `business.email = ""`, Claude will see the literal phrase `"expect an email from  shortly"` (double space). Ugly. Acceptable for now because both demo clients (BlueMarlin + Adamus) have the field populated. If we ever onboard a client without `business.email`, we add a fallback in a follow-up brief — out of scope for Brief 157.
2. **Existing marina test fixtures might assert the old wording.** Step 4 catches this. If a test breaks, the test fixture is wrong (asserting outdated wording), not the new prompt — update the fixture to match.
3. **Claude might over-paraphrase and drop the address from the reply.** Possible but unlikely — putting the literal email in the prompt context generally produces literal usage in the reply. If we see Claude omitting the address consistently, the prompt needs to be tightened with "MUST include the literal address `<email>`" instead of "Tell them to expect an email from `<email>`".
