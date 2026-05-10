# BRIEF 244 — Stop internal email leakage + strip em-dashes from Marina customer replies

**Status:** Draft (round 2) | **Files:** clients/unboks/config/client.json, wtyj/agents/marina/marina_agent.py, wtyj/tests/marina/test_224_strip_internal_tokens.py | **Depends on:** Brief 243 (`a6e9883`) | **Blocks:** none

## Context

Issue #8 (TASK-080) — calvin835 reported that customer-facing Marina replies for the `unboks` tenant contain two surface-level defects:

1. **Internal SMTP sender mailbox leaks into customer body text.** Real reply observed:
   > "The team will be in touch from butlerbensonagent@gmail.com shortly — please keep an eye on your inbox so it doesn't land in spam."

   `butlerbensonagent@gmail.com` is the SMTP authentication mailbox for unboks (per `clients/unboks/config/platform.env` `EMAIL_ADDRESS`). Customers should see `hello@unboks.org` (the new public Google Workspace mailbox).

2. **Em-dashes (`—`) appear in customer replies despite `agent_persona.brand_voice_rules` saying "Never use em-dashes or en-dashes".** Calvin explicitly prohibits the character.

Root cause for #1, traced via grep + read of `marina_agent.py` (verified anchors):
- `clients/unboks/config/client.json:4` — `business.email = "butlerbensonagent@gmail.com"`.
- `wtyj/agents/marina/marina_agent.py:719` — escalation prompt branch hard-instructs Marina: `"Tell them to expect an email from {business.get('email', '')} shortly — keep an eye on their inbox..."`. The interpolation pulls `business.email` directly into the customer-facing instruction.

Same `business.get('email', '')` interpolation appears at lines 719, 720, 726, 729, 744, 764. All currently inject `butlerbensonagent@gmail.com` into the unboks tenant's prompt.

`business.support_email` (`clients/unboks/config/client.json:21`) is **NOT used in customer-facing text**. Verified usage: `wtyj/agents/marina/email_poller.py:96/415-417/567` — it's the internal routing key for "incoming team-relay reply" detection (when the team operator replies to an escalation thread, the poller checks if `from_email == support_email` to route the message as a relay rather than a customer message). Changing `support_email` without also changing the actual mailbox operators reply-from would break team-relay detection. **Out of scope for this brief.**

Same parallel leak exists in BlueMarlin (`clients/bluemarlin/config/client.json:4` `business.email`, `:21` `support_email`, `:22` `demo_support_email`, `:104` `contact_for_booking`, `:120` knowledge text) and Adamus (`clients/adamus/config/client.json:19` `support_email` only — `business.email` is correctly `sophia@wetakeyourjob.com`). **Out of scope:** BlueMarlin is deprecated per CTO directive (no live customers; documented in Brief 240 canary skip + Brief 238 credential strip), so its leak is technical-only with no customer impact. Adamus's `support_email` leak is internal-routing-only (same reasoning as unboks above) and the field is unused in customer-facing text. If/when BlueMarlin reactivates or Adamus operators want their team-relay routing rewired, separate brief.

Root cause for #2:
- 63 em-dash characters live in `wtyj/agents/marina/marina_agent.py`'s prompt string (verified: `grep -c "—" wtyj/agents/marina/marina_agent.py` → 63). Claude pattern-matches the prompt's writing style despite the explicit "Never use em-dashes" rule.
- `wtyj/agents/social/dm_agent.py:253` already runs `reply = reply.replace("—", ",")` post-LLM (Brief 201). `marina_agent.py` has no such strip — its post-LLM cleanup is `_strip_internal_tokens` only (Brief 224), which targets `[ESCALATE_HARD]` / `[RELAY]` markers, not em-dashes.

Channel coverage for the strip side:
- `marina_agent.process_message` handles **email** (via `wtyj/agents/marina/email_poller.py:759/1029/1053/1350` etc.) and **WhatsApp** (via `wtyj/agents/social/webhook_server.py` for unboks tenant per Brief 232).
- `wtyj/agents/social/dm_agent.process_message` handles **Instagram / Facebook / Messenger** DMs via Zernio. Already has the strip (line 253).
- Telegram is not implemented (per Benson 2026-04-28).

Adding a strip at `marina_agent.py:1115-1117` (right after `_strip_internal_tokens` calls on `reply` + `reply_hold_failed`) gives full customer-facing channel coverage for em-dashes when combined with the existing `dm_agent.py:253` strip.

## Why This Approach

**Considered:** removing all 63 em-dashes from Marina's prompt template (the source of the style-mirroring) instead of post-LLM stripping. **Rejected:** mass prompt edits risk semantic drift in 60+ unrelated instructions; Claude can still emit em-dashes from its pretrained tendencies even with a clean prompt; the strip is the proven defense (`dm_agent.py:253` has worked since Brief 201). The post-LLM strip is the single belt-and-suspenders line that defeats the failure mode regardless of prompt content.

**Considered:** extracting a shared `strip_em_dashes(text)` helper into `wtyj/shared/text_sanitizer.py` and refactoring `dm_agent.py:253` to use it. **Rejected:** only 2 callers today; adding shared abstraction now is premature. Two `text.replace("—", ",")` lines is fine. If/when a third agent needs the strip, that brief extracts.

**Considered:** also adding a `business.public_contact_email` field separate from `business.email` and re-routing the prompt's `expect an email from` line to the new field. **Rejected for this brief, deferred to a future brief if needed:** the simpler fix is to make `business.email` the public-customer-facing address (since 6 prompt sites already reference it that way). The two were always supposed to be different concerns and the conflation only mattered when they happened to be the same string. Issue #8's primary ask is "stop the leak"; both approaches achieve that. The architectural cleanup (separate sender vs public-contact field) waits until a tenant has a different public email than internal sender (none today have that; all 4 use `business.email` as the customer-displayed address — and unboks's `EMAIL_ADDRESS` env var stays `butlerbensonagent@gmail.com` as the actual SMTP authentication mailbox; only the customer-displayed address changes).

**Considered:** stripping en-dashes (`–`) too, since `agent_persona.brand_voice_rules` mentions both. **Rejected:** issue #8 acceptance #4 specifies "no em dash characters" only; en-dashes legitimately appear in number ranges ("5–10 guests"); widening scope risks breaking content. Em-dash only, matching `dm_agent.py:253`.

**Tradeoff:** the post-LLM strip replaces every em-dash with a comma `,` (no space) to match `dm_agent.py:253` exactly. This produces text like "shortly,please" (no space) when the original was "shortly — please". Issue #8 explicitly accepts comma as a replacement. Cleaning to ", " (with space) would be marginally better readability but introduces divergence with `dm_agent.py:253`'s existing behavior; symmetric simple is better than asymmetric clever. If readability becomes a complaint, follow-up brief widens both call sites consistently.

## Instructions

### Step 1 — Fix the unboks customer-facing email leak at the config source

Edit `clients/unboks/config/client.json`:
- Line 4: change `"email": "butlerbensonagent@gmail.com",` → `"email": "hello@unboks.org",`

Leave all other fields untouched. Specifically **do NOT change**:
- `business.support_email` (line 21) — internal routing key for team-relay detection in `email_poller.py:96/415-417/567`. Changing it without also changing the operator reply-from mailbox would break team-relay routing. Out of scope per Context.
- `clients/unboks/config/platform.env` `EMAIL_ADDRESS=butlerbensonagent@gmail.com` — actual SMTP authentication mailbox; out of scope.

Other tenants (`bluemarlin`, `adamus`, `consultadespertares`) are explicitly out of scope per Context — do NOT touch their client.json files in this brief.

### Step 2 — Add em-dash strip to marina_agent's process_message return path

In `wtyj/agents/marina/marina_agent.py`, the current code at lines 1114-1117 reads:

```python
        # Brief 224: sanitize customer-facing text fields before returning.
        result["reply"] = _strip_internal_tokens(result.get("reply", ""))
        if result.get("reply_hold_failed"):
            result["reply_hold_failed"] = _strip_internal_tokens(result["reply_hold_failed"])
```

Replace with:

```python
        # Brief 224: sanitize customer-facing text fields before returning.
        # Brief 244: also strip em-dashes per agent_persona.brand_voice_rules
        # (Claude ignores the prompt-side rule; mirrors dm_agent.py:253).
        result["reply"] = _strip_internal_tokens(
            result.get("reply", "")).replace("—", ",")
        if result.get("reply_hold_failed"):
            result["reply_hold_failed"] = _strip_internal_tokens(
                result["reply_hold_failed"]).replace("—", ",")
```

**Why these two fields only:** they are the customer-facing string fields in the tool-use schema (`marina_agent.py:105` `reply` + `:109` `reply_hold_failed`). `internal_note`, `human_relay_question`, `escalation_summary` are operator-facing and may legitimately contain em-dashes for operator readability — those go to the dashboard, not the customer.

**Why not extend `_strip_internal_tokens` instead:** keeping the em-dash strip visible at the call site documents the intent at the failure point. Extending the helper would hide the post-LLM cleanup behind one function name with two unrelated jobs (token stripping + character replacement).

### Step 3 — Add 3 new tests to `wtyj/tests/marina/test_224_strip_internal_tokens.py`

Append the following at the end of the file (after current line 96). Tests reuse the existing `_call_process_message(reply_text, reply_hold_failed)` helper at line 31 — same mock pattern (`patch("agents.marina.marina_agent.anthropic.Anthropic")`) and same `process_message` signature (`from_email`, `subject`, `body`, `thread_fields`, `thread_flags`, `action_context`, `channel`, `messages`).

```python


# ── Brief 244: em-dash strip from customer-facing reply fields ─

def test_em_dash_stripped_from_reply():
    """Brief 244: process_message strips em-dashes from result['reply']
    before returning. Mirrors dm_agent.py:253 strip behavior — em-dash
    becomes comma (no space) to match dm_agent's existing pattern."""
    text_with_dash = (
        "The team will contact you shortly — keep an eye on your inbox.")
    result = _call_process_message(text_with_dash)
    assert "—" not in result["reply"]
    assert result["reply"] == (
        "The team will contact you shortly, keep an eye on your inbox.")


def test_em_dash_stripped_from_reply_hold_failed():
    """Brief 244: same strip applies to reply_hold_failed (apologetic
    message when slot unavailable, also customer-facing per
    marina_agent.py:109 schema)."""
    plain = "OK"
    apology_with_dash = "Sorry — that slot just got taken."
    result = _call_process_message(
        plain, reply_hold_failed=apology_with_dash)
    assert "—" not in result["reply_hold_failed"]
    assert result["reply_hold_failed"] == "Sorry, that slot just got taken."


def test_em_dash_strip_runs_after_internal_token_strip():
    """Brief 244 + Brief 224: both sanitizers compose. A reply containing
    BOTH an internal escalation token AND an em-dash gets cleaned of both
    before reaching the customer. Proves the em-dash strip is sequenced
    AFTER _strip_internal_tokens (so trailing-whitespace cleanup from
    token strip happens first, then em-dash replacement runs)."""
    dirty = "I'll escalate that — the team handles refunds. [ESCALATE]"
    result = _call_process_message(dirty)
    assert "[ESCALATE]" not in result["reply"]
    assert "—" not in result["reply"]
    assert "I'll escalate that, the team handles refunds." in result["reply"]
```

**Test design notes:**
- All 3 tests reuse `_call_process_message` from line 31 — same boundary mock pattern (`patch("agents.marina.marina_agent.anthropic.Anthropic")`) as the existing 6 tests in this file. Round-1 reviewer caught a fabricated-helper / wrong-mock-target draft; this revision reuses the verified pattern.
- Each test asserts both the negative ("`—` not in reply") AND the exact resulting substring — proves the strip ran AND that it produced the expected substitution shape. Avoids the "I removed the assertion when it failed" anti-pattern.
- Test 3 uses `[ESCALATE]` (one of `_INTERNAL_TOKENS` from line 30 of marina_agent.py) so it composes correctly with `_strip_internal_tokens`.

### Step 4 — Out of scope (documented for future briefs)

These were considered and explicitly NOT addressed in this brief:

- **Cleaning the 63 em-dashes from `marina_agent.py`'s prompt template.** Post-LLM strip catches them anyway. Future brief if prompt clarity becomes a maintenance issue.
- **En-dash (`–`) strip.** Issue #8 specifies em-dash only; en-dashes legitimately appear in number ranges. Add only if reported.
- **Separate `business.public_contact_email` vs `business.smtp_sender_email` field architecture.** Today both are conflated; that's fine. Refactor when a tenant needs different values.
- **Changing `EMAIL_ADDRESS` env var on VPS for unboks.** That's the SMTP authentication mailbox; out of scope.
- **Fixing the parallel leak in BlueMarlin / Adamus client.json.** BlueMarlin is deprecated; Adamus's leak is internal-routing-only. Both deferred per Context.
- **Changing `business.support_email` for unboks.** Internal routing key, not customer-facing; per Step 1 reasoning.

## Tests

3 new tests in `wtyj/tests/marina/test_224_strip_internal_tokens.py`. Total file goes from 96 lines to ~135 lines.

Expected after-test count: **1050 passing / 0 failures** (1047 baseline + 3 new = 1050).

## Success Condition

After Marina processes a customer message:
1. `result["reply"]` contains zero `—` characters regardless of what Claude generated.
2. `result["reply_hold_failed"]` (when present) contains zero `—` characters.
3. For unboks tenant: `business.email` resolves to `hello@unboks.org` everywhere (verified by reading `clients/unboks/config/client.json:4`). Customer-facing prompt interpolations at `marina_agent.py:719/720/726/729/744/764` produce `hello@unboks.org` instead of `butlerbensonagent@gmail.com`.
4. Other tenants (`bluemarlin`, `adamus`, `consultadespertares`) are unchanged.
5. Operator-facing fields (`internal_note`, `human_relay_question`, `escalation_summary`, alert email subject/body) are unaffected — em-dashes preserved there for operator readability.
6. `dm_agent.py:253`'s existing strip is unchanged; full customer-facing channel coverage now (email + WhatsApp via marina_agent + IG/FB/Messenger via dm_agent).
7. Internal team-relay routing (`email_poller.py:567`) still works because `business.support_email` is unchanged.

## Rollback

Revert the brief commit:
```
git revert <brief-244-commit-sha>
git push origin main
```

This restores `business.email` to `butlerbensonagent@gmail.com` and removes the em-dash strip. CI will re-deploy the previous behavior in ~90s. No data migration needed.
