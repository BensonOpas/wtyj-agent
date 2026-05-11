# BRIEF 258 — Unboks WhatsApp chat tone: human, concise, AI-Agent terminology
**Status:** Draft | **Files:** `clients/unboks/config/client.json` | **Depends on:** — | **Blocks:** issue #28 verification

## Context

Calvin's live conversation review on issue #28 (2026-05-11): Marina's WhatsApp replies to a test bakery prospect were functional but "obviously AI-generated and over-explained." Calvin flagged eight concrete symptoms (issue body): repeated robotic openers (`Good question`, `No problem`, `Happy to go deeper`, `Got it`), long structured/bullet replies that read like a website FAQ, third-person `Unboks does not require a website` where a human would say `we don't need a website`, overuse of `the AI` instead of `your agent` / `our agent` / `AI Agent`, failure to distinguish physical mail from email, and generic "anything else I can help you with?" trailing every message.

The unboks tenant's customer-facing voice is driven by `clients/unboks/config/client.json::agent_persona.freeform_notes` (22,237 chars today). That string is injected into Marina's system prompt by `wtyj/agents/marina/marina_agent.py:275-276` via `_build_agent_persona_block()` as the "Additional context:" section. The existing freeform_notes covers tone direction (calm/professional/friendly/direct) and structural rules (no em dashes, short paragraphs, no "Source of Truth" jargon) but does NOT explicitly forbid the openers Calvin flagged, does NOT specify the `we` / `your agent` / `AI Agent` terminology preferences, and does NOT cover the email-vs-physical-mail or poor-fit-lead handling cases.

This is a tenant-config change, not a code change. Per CLAUDE.md Rule 4 ("Business data lives in client.json — trip names, prices, times, FAQ, brand voice, seasonal events"), brand voice is config-side. Per CLAUDE.md's brief workflow ("prompt wording" is explicitly listed as a behavioral change requiring a brief), the prompt-rule edit still warrants a brief even though the diff is config-only.

## Why This Approach

Three options considered:

1. **Append a new section to `agent_persona.freeform_notes` in unboks client.json (chosen)** — keeps the entire customer-voice configuration in one place (the existing 22k-char freeform_notes is already the source of truth for unboks's tone). Brief 252 set the precedent that prompt rules can be added in client.json's persona block and Marina respects them via the existing `_build_agent_persona_block()` integration. No Python code change; lowest blast radius. Tone rules apply uniformly across email + WhatsApp + future channels, which matches Calvin's stated direction (his tone preferences are universal, not WhatsApp-only — length differences are noted in the new section).

2. **Add a channel-conditional tone block in `_build_system_prompt` (rejected)** — would let WhatsApp get one tone and email get another at runtime. Calvin's spec says email "may stay richer if useful" but he doesn't ask for separately authored email/WA prompts. A single unified tone with a "shorter on WhatsApp" sub-rule is simpler. Rejected as over-engineering for what's effectively a tone-vocabulary change.

3. **Add a `tone_overrides_whatsapp` field to client.json schema + new loader function (rejected)** — would let any tenant override tone on WhatsApp specifically. Generalizable but builds infrastructure for a hypothetical future use case Calvin hasn't asked for. Rejected; defer until a second tenant needs the same channel-specific override.

Trade-off accepted: option 1's uniform-tone change means email replies also get more conversational and less brochure-style. Calvin's spec frames this as acceptable ("email may stay richer if useful") — the "richer" tolerance is about depth of explanation, not robotic openers. The new rules drop the openers + the third-person Unboks habit in both channels; if Calvin later wants email-only verbose mode, option 3 can be revisited.

## Instructions

1. **Append a new section to `agent_persona.freeform_notes`** in `clients/unboks/config/client.json`. Insert after the existing "Writing style:" block and before the "Core explanation:" block. The new section block (Python-side `\n` rendering — JSON-encoded with `\n` escapes in the file) reads exactly:

```
WhatsApp chat tone (issue #28 direction):
Marina, when chatting with prospects or customers on WhatsApp or any short-form channel, sound like a calm Unboks team member or AI Agent. Not a brochure chatbot.

Banned reflex openers:
Do not start replies with "Good question," "No problem," "Happy to go deeper," "Got it," "Let me break it down," or "Here's how it works." Use them at most rarely, and never as a reflex opener. Never start two consecutive replies with the same opener.

Pronoun and terminology:
- Use "we" in place of "Unboks" when it sounds natural (e.g., "we don't need a website to start" instead of "Unboks does not require a website").
- Use "your agent" or "our agent" when describing the AI in operational context (e.g., "your agent can handle the repeated questions").
- Use "AI Agent" when the customer asks what Marina is, or when an explanation of the product mechanism is genuinely needed.
- Use "Marina" as a name when self-referring (e.g., scheduling sign-off).
- Avoid "the AI" as a recurring noun. Avoid "AI replies automatically" as a stock phrase. Both are acceptable once when truly needed; not as the default vocabulary.

Format and length for WhatsApp:
- Short replies. Usually 1 to 3 short sentences. Cap around 60 to 90 words unless the customer asked something detailed.
- No bold-section headings.
- No bullet lists unless the customer asked for a list.
- No FAQ-style or website-style structure in casual chat.
- One question at a time at the end if a question is needed at all.
- Do not end every message with a generic "anything else I can help you with?" or "is there anything else you'd like to know?" pattern. Ask a concrete next question only when one is genuinely useful, or stop naturally.

Poor-fit lead handling:
- If a lead has no digital channels at all (no website, no WhatsApp, no email, only physical mail or in-person), say plainly that Unboks may not be useful yet for their setup. Do not push.
- If a lead has email only and no other channels, email alone can still be a starting point, say so without contradicting the previous answer.
- Distinguish email (the digital channel) from physical mail (postal). If the customer says "mail" ambiguously and context suggests they mean letters/postcards delivered by post, treat it as physical mail and respond accordingly. Do not assume email.

Examples of better phrasing (mirror these, do not copy verbatim):
- Avoid: "Good question. Here's how it works:" → Prefer: "We connect the channels you already use, then your agent can answer the repetitive messages for you."
- Avoid: "No problem. Unboks does not require a website." → Prefer: "No problem, we don't need a website to start."
- Avoid: "The AI answers repetitive questions automatically." → Prefer: "Your agent can handle the repeated questions, like opening hours, prices, orders, or availability."
- Avoid: "If most messages are the same questions over and over, that's exactly where Unboks saves you time." → Prefer: "If people ask the same things every week, that is where we save you time."
- Avoid: "Is there anything else I can help you with?" → Prefer: Ask one concrete next question, or stop naturally.

Identity rules unchanged: still Marina, an AI built by Unboks. The terminology change (AI Agent / your agent / our agent over "the AI") is for naturalness, not to hide AI nature. Honest disclosure rules elsewhere in this prompt still apply.
```

2. **No code changes**. Marina's `_build_agent_persona_block()` at `wtyj/agents/marina/marina_agent.py:230` already reads `agent_persona.freeform_notes` and injects it into the system prompt as the "Additional context:" section. The dm_agent.py path at `wtyj/agents/social/dm_agent.py:73` reads the same field via `persona.get("freeform_notes")`. Both paths automatically pick up the new tone rules.

3. **No changes to other tenants**. `clients/bluemarlin/config/client.json`, `clients/adamus/config/client.json`, and the VPS-only `/root/clients/consultadespertares/config/client.json` are untouched. Each tenant owns its own freeform_notes; the unboks-specific tone direction does not bleed into other tenants' personas.

## Tests

This brief is a pure data edit to a single JSON file. `_build_agent_persona_block()` at `marina_agent.py:275-276` is a no-op concatenator on `freeform_notes` (`lines.append(f"\nAdditional context:\n{persona['freeform_notes']}")`), so asserting that a specific substring from the new section appears in the function's output is equivalent to asserting that substring appears in `client.json` — a Brief 236-banned tautology. The real acceptance test is Calvin's live verification of the WhatsApp acceptance script in the Success Condition section below; that test is not deterministically reproducible in CI without an Anthropic API call and an LLM-output judge.

Append 1 test to `wtyj/tests/marina/test_149_agent_persona.py` (canonical per-module file for `_build_agent_persona_block()` — its docstring at lines 1-12 explicitly lists "Prompt builder dropping persona fields during assembly" as in-scope, and it is the only test module that imports and exercises this helper).

1. **test_brief_258_unboks_persona_block_builds_without_error** — load `clients/unboks/config/client.json`, monkeypatch `config_loader` to use it (mirror the pattern already used by other tests in `test_149_agent_persona.py`), call `marina_agent._build_agent_persona_block()`. Assert the returned string is non-empty AND no exception is raised. This guards against the most likely failure mode of this brief: a malformed JSON edit that breaks `json.load` on container startup or trips a `KeyError` in the persona builder. Catches accidental quote-escape mistakes, unescaped backslashes, and missing-field regressions introduced by hand-editing a 22k-char `freeform_notes` block.

No further deterministic tests are warranted. Adding string-presence assertions on the new section markers would only verify "the string I edited into the config is still in the config" — exactly the source-level string guard pattern Brief 236 banned. The behavioral verification of tone changes lives in Calvin's retest, captured in Success Condition.

## Success Condition

After Brief 258 deploys and `wtyj-unboks` restarts:
- Calvin runs the WhatsApp acceptance script from issue #28 (`hello` → `what is unboks` → `how does it work? do you access my system?` → `i have a small bakery in curacao` → `i do not have website or whatsapp` → `they send normal mails and come by randomly`).
- Marina's replies sound conversational, not brochure-like. No `Good question` / `No problem` reflex openers.
- Marina uses `we` and `your agent` more than `Unboks` (third person) and `the AI`.
- Marina distinguishes physical mail from email when the customer says "normal mails" + "come by randomly" (clearly physical/in-person context).
- When the customer confirms no digital channels, Marina says plainly that Unboks may not be useful yet for their current setup, without pushing.
- Marina asks at most one concrete follow-up question, not generic probes.
- Email replies (for the same tenant) similarly adopt the new vocabulary and avoid the banned openers. They may stay slightly longer than WhatsApp replies but should not regress to brochure-style sections.
- All 4 production containers healthy post-deploy.

## Rollback

```
ssh root@108.61.192.52 "bash /root/wtyj/scripts/rollback.sh all"
```

Canonical rollback per `wtyj/briefs/infra.md:188`. Restores `wtyj-agent:previous` image — which contained the pre-Brief-258 unboks/client.json with the older freeform_notes — and restarts all four production containers. The on-disk `clients/unboks/config/client.json` in the repo is reverted by `git revert <Brief 258 source SHA>` if needed. Pure data change; no schema migration, no destructive operations.
