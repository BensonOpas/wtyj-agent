# BRIEF 209 — Calvin → Marina rebrand + scheduling directive (unboks)
**Status:** Draft | **Files:** `clients/unboks/config/client.json`, `wtyj/tests/test_199_unboks_config.py` | **Depends on:** Brief 203 (`freeform_notes` injection), Brief 206 (`[ESCALATE]` sentinel) | **Blocks:** Brief 210 (reply-from-dashboard surfaces Marina sign-off)

## Context

The unboks tenant's outbound voice is split:
- Email "From" header is `Marina <hello@unboks.org>` (hardcoded at `wtyj/agents/marina/email_adapter.py:127`)
- DM/email reply body is signed `Calvin\nUnboks` (from `business.agent_signature` + IDENTITY block in `agent_persona.freeform_notes`)
- Greeting injects `"Hi, this is Calvin from Unboks"` (`agent_persona.greeting_style`)

Live evidence — single `pending_notifications` row, id=1, status=`sent`, channel=email, customer=Calvin Adamus (calvin@gaimin.io, GAIMIN co-founder). The captured chat log shows AI replied:

> "All good on our end, Calvin.
>
> For scheduling, I don't have direct visibility into the team's calendar from here — best move is to drop a note to hello@unboks.org and they'll get a time locked in with you quickly.
>
> What service were you looking to activate? Happy to prep any context before the call."

Followed by a second reply signed `Calvin\nUnboks`.

SR's two complaints in one message:
1. **Sign-off mismatch** — keep Marina (since email From already says Marina), flip the body sign-off and identity from Calvin to Marina across the whole prompt surface.
2. **Bad scheduling/activation tone** — don't redirect to email when already on email, don't claim no calendar access, warm tone, ask for minimum details, sign "Marina". SR pasted both the bad and good example replies and the new system-prompt directive verbatim.

## Why this approach

- **Config/prompt only.** Rule 4 of `CLAUDE.md` — business identity lives in `client.json`. No Python edits.
- **`agent_internal_id` rename to `marina-unboks`.** `grep -rn "agent_internal_id|calvin-csa" wtyj/ clients/` returned 2 production references: `clients/unboks/config/client.json:19` (the value) and `wtyj/tests/test_199_unboks_config.py:26` (test assertion). No code routes on it; container name `wtyj-unboks` and image tag are independent. Safe rename.
- **Scheduling directive lives in `freeform_notes`** — Brief 203 wired `freeform_notes` injection at `wtyj/agents/social/dm_agent.py:_build_dm_system_prompt()`. The directive will reach Claude. Same path serves email (via `marina_agent.process_message`).
- **Directive integrates with existing `[ESCALATE]` sentinel** (Brief 206). SR framed scheduling as "an escalation" — so the directive ends the reply with the sentinel, captured by `dm_agent.py:215+` (and the equivalent path for email), creating a `pending_notifications` row so the team books the actual time.
- **Rejected:** making `email_adapter.py:127` read agent name from `client.json`. Currently hardcodes `"Marina"` which is now correct for unboks (and BlueMarlin). Pure tenant-generality cleanup — defer to a brief that touches all tenants together.
- **Rejected:** stripping the `[ESCALATE]` sentinel from the customer-visible reply via a *new* code path. The existing post-process at `dm_agent.py:221` (`reply.replace("[ESCALATE]", "").rstrip()`) already handles it.

## Instructions

### Step 1 — `clients/unboks/config/client.json` (5 edits)

**1.1** `business.agent_name`: `"Calvin"` → `"Marina"`

**1.2** `business.agent_signature`: `"Calvin\nUnboks"` → `"Marina\nUnboks"`

**1.3** `business.agent_internal_id`: `"calvin-csa"` → `"marina-unboks"`

**1.4** `agent_persona.greeting_style`: replace literal substring `'Hi, this is Calvin from Unboks'` with `'Hi, this is Marina from Unboks'` (single-quoted inside the JSON value — preserve quoting).

**1.5** `agent_persona.freeform_notes` — three sub-edits inside the long string, then one insertion:

(a) **Recursive-redirect rule** — replace
```
You are running on Calvin's WhatsApp number.
```
with
```
You are running on the Unboks WhatsApp number.
```

(b) **IDENTITY block at the end** — replace the entire IDENTITY paragraph
```
IDENTITY: You are Calvin, an AI representing Unboks. Calvin Adamus is the founder; you carry his name as a friendly handle for the AI. If asked directly whether you are a person, say you're an AI built by Unboks. Don't pretend to be Calvin the human. Don't apologize for being AI.
```
with
```
IDENTITY: You are Marina, an AI built by Unboks. Calvin Adamus is the founder of Unboks. If asked directly whether you are a person, say you're an AI built by Unboks. Don't pretend to be human. Don't apologize for being AI.
```

(c) **INSERT new SCHEDULING/ACTIVATION DIRECTIVE block** between the existing `Calls and next steps:` section and the `Refusal style:` section. The full block to insert (verbatim, single `\n` line breaks inside the JSON string):

```
SCHEDULING / ACTIVATION DIRECTIVE:
If the customer asks to schedule a meeting, activation call, onboarding call, demo, setup, or service activation, treat it as a scheduling or activation escalation. The reply has two parts: (a) the visible reply the customer sees, (b) the [ESCALATE] sentinel on the final line so the team picks it up.

Visible reply rules:
- Do not send the customer to email if they are already messaging through an active channel (email, WhatsApp, IG, FB).
- Do not claim the AI cannot access the calendar.
- Reply warmly and positively. Make the customer feel they are making a good decision.
- Ask for the minimum useful scheduling details: which service they want, plus 2 or 3 times that work for them this week.
- Tell them you will check with the team or pass it to the team so they can confirm a time.
- Match the customer's communication style where appropriate, but keep Marina's identity: warm, clear, professional, calm, and helpful.
- Do not overdo slang or become too casual.
- Do not use em dashes.
- End the visible reply with "Marina" on its own final line.

Then on the very last line, write the literal token [ESCALATE] (it will be stripped before send and used to flag the conversation for the team).

Example good reply:
"Yes, we're good. And honestly, great decision getting this activated.

I'll check with the Unboks team so we can get the activation call lined up for you.

Just send me the service you want to activate and 2 or 3 times that work for you this week, and we'll take it from there.

Marina
[ESCALATE]"

Example bad reply (do not do):
- Suggesting "drop a note to hello@unboks.org" when the customer is already on email
- "I don't have direct visibility into the team's calendar" — never say this
- Closing without the Marina sign-off line
- Forgetting the [ESCALATE] sentinel — without it the team will not see the request
```

**1.6** `common_sense_knowledge.marina_persona`: replace `"You are Calvin, an AI representing Unboks."` with `"You are Marina, an AI representing Unboks."` (rest of the string unchanged).

### Step 2 — `wtyj/tests/test_199_unboks_config.py` (2 assertion updates)

In `test_unboks_business_identity`:
- Line 25: `assert cfg["business"]["agent_name"] == "Calvin"` → `== "Marina"`
- Line 26: `assert cfg["business"]["agent_internal_id"] == "calvin-csa"` → `== "marina-unboks"`

### Step 3 — Add new test `test_unboks_scheduling_directive_present`

Append to `wtyj/tests/test_199_unboks_config.py`:

```python
def test_unboks_scheduling_directive_present():
    """The freeform_notes must contain the SCHEDULING/ACTIVATION DIRECTIVE
    block so calvin-csa-on-Marina-voice handles activation calls warmly
    instead of redirecting to email."""
    cfg = json.loads(UNBOKS_CONFIG.read_text())
    notes = cfg["agent_persona"]["freeform_notes"]
    assert "SCHEDULING / ACTIVATION DIRECTIVE" in notes
    assert "Do not send the customer to email if they are already messaging through an active channel" in notes
    assert "End the visible reply with \"Marina\" on its own final line" in notes
```

### Step 4 — No code changes

Do not edit any `.py` file under `wtyj/`. Do not edit `dm_agent.py`, `marina_agent.py`, `email_adapter.py`, `state_registry.py`. The `[ESCALATE]` strip path already exists; the SMTP "From" hardcode is intentionally left for a separate tenant-generality brief.

## Tests (4)

1. **`test_unboks_client_json_is_valid`** (existing) — must still pass after all edits. Regression guard for JSON validity and required top-level keys.
2. **`test_unboks_business_identity`** (modified) — passes with `agent_name == "Marina"` and `agent_internal_id == "marina-unboks"`. Languages still 5, booking_flow still false.
3. **`test_unboks_persona_has_pricing_guard`** (existing) — must still pass. Brand-voice "never quote price" rule unchanged.
4. **`test_unboks_scheduling_directive_present`** (new) — asserts the SCHEDULING/ACTIVATION DIRECTIVE marker text + the "do not redirect to email" line + the "Marina sign-off" line are all present in `freeform_notes`.

## Success Condition

Send an email to `hello@unboks.org` from any external account with body roughly:

> "we good? what time can we meet this week to activate my service?"

Within 1-2 minutes:
1. Reply arrives signed `Marina` on its own line (not `Calvin\nUnboks`).
2. Reply tone matches SR's "good answer" example: positive ("great decision"), asks for service + 2-3 times, says "I'll check with the team" or equivalent.
3. Reply does NOT redirect to a different email address (the customer is already on email).
4. Reply does NOT contain the phrase "I don't have access" or "I don't have visibility" or similar AI-limitation framing.
5. The reply visible to the customer does NOT contain the literal string `[ESCALATE]` (post-process strips it).
6. A new row appears in unboks's `pending_notifications` table with `status='pending'` for this thread.

## Rollback

`git revert <commit>` and trigger redeploy via the canary pipeline. Nothing to undo on the data side — config-only change. Container picks up new `client.json` on the next start (no schema migration, no DB write).

If the rebrand causes voice regressions in non-scheduling threads (unlikely, since the only IDENTITY-block change is the name), Benson can edit `clients/unboks/config/client.json` directly on the VPS at `/root/clients/unboks/config/client.json` and `docker compose restart wtyj-unboks` for an immediate hotfix without a full redeploy.
