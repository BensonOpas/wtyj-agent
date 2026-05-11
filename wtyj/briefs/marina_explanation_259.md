# EXPLANATION 259 — Unboks reply rhythm: drop validation-phrase reflex, vary rhythm, handle contradictions

## In one sentence

Marina's unboks instructions now ban the *habit* of opening every reply with a polite acknowledgement (not just the specific words Brief 258 banned), tell her to vary how each reply is shaped, tone down brochure-style certainty, and ask a quick clarifying question when a customer contradicts something they said earlier.

## What's changing and why

Brief 258 cleaned up Marina's terminology and removed a specific set of reflex openers ("Good question," "No problem," "Got it," and four others). When Calvin re-ran the bakery test script the next day, the terminology was correct — but Marina simply substituted a new pool of openers and kept the same shape on every reply: validate the customer's input, then state a fact, then explain, then ask a follow-up. Her new openers were "Nice," "That's a solid," "Classic," "Perfect," and "WhatsApp works perfectly." Calvin's note was that this pattern feels artificial because a human does not validate every input before answering.

Brief 259 widens the rule from "ban these specific phrases" to "ban the always-validate reflex." It tells Marina that the underlying problem is the *shape* of her replies, not just the words she chose. It also adds three new guidance sections covering reply rhythm, brochure-style language, and what to do when a customer's later message contradicts an earlier one. This is purely a change to the unboks tenant configuration — no code changed, and other tenants are unaffected.

The meta-point worth naming: prompt-based tone fixes are inherently iterative. This is the third round on the same issue. Round 1 set the direction, round 2 fixed the wrong words, round 3 fixes the wrong shape. A round 4 is possible if Marina drifts into a new reflex pattern, and the brief openly acknowledges that.

## Step by step — what the code does now

STEP: Banned-opener list, widened

The unboks tone-guidance section now lists eleven banned reflex openers instead of six. The five new ones — "Nice," "That's a solid," "Classic," "Perfect," and equivalents — were the substitutes Marina invented after Brief 258. The instruction now also names the underlying habit Marina should avoid: "validate-then-answer on every turn." So even if Marina invents a *twelfth* opener nobody listed, the rule against using it as a reflex still applies. The instruction also tells her never to start two replies in a row with the same opener.

STEP: New "Reply rhythm" section

Marina is told that not every turn needs all four parts (validation, fact, explanation, follow-up question). She is told to mix four shapes: sometimes answer directly with no preface, sometimes ask a short next question with no validation, sometimes acknowledge briefly and then answer, sometimes give a fact and stop without asking anything. She is also told to vary sentence count — one sentence plus a question, or two short sentences, rarely a paragraph. The instruction gives her a self-check: if three replies in a row all open with acknowledgement-fact-question, she has drifted back into template mode.

STEP: New "Reduce salesy certainty" rule

Marina is told that phrases like "works perfectly," "exactly what you need," "this is the solution," and "the perfect fit" sound like a brochure. She is given softer alternatives: "is a good starting point," "usually helps most with," "can take some of that off your plate." When she's not sure of something she should say so; when she is sure she should sound matter-of-fact rather than brochure-confident.

STEP: New "Contradiction handling" section

When a customer says something that contradicts what they said earlier — for example claiming "I don't have WhatsApp" and then later mentioning WhatsApp — Marina should ask one short clarifying question rather than silently accepting the latest statement. The instruction includes an example phrasing she can mirror, and explicitly tells her not to make a big deal of it, not to sound accusatory, and not to lecture.

STEP: Three new before/after example pairs

The existing example block (which Brief 258 introduced) gets three more pairs, copied verbatim from Calvin's feedback. Each pair shows a bad opener Marina actually produced ("Nice, Curaçao is home base for us too...", "That's a solid volume...", "Classic repeated questions...") next to a preferred rewrite that skips the validation and goes straight to the substance. These examples are framed as guidance to imitate the style, not templates to copy word-for-word.

STEP: How Marina picks this up

No code changed. The same builder that already assembles Marina's per-customer system prompt for unboks now reads the longer notes block (29,161 characters instead of 26,516) and includes it in the prompt sent to Claude. The change reaches Marina on her very next inbound message after the deploy completes.

## Edge cases

- Prompt rules cannot perfectly enforce "vary your rhythm." Claude may still drift back to the validation pattern on certain inputs. This is an accepted trade-off and the reason a possible round 4 is named in the brief itself.

- If Marina occasionally opens with "Nice" or "Got it" on a turn where it genuinely fits, that is fine. The test is whether the pattern repeats as a reflex across three or more consecutive replies, not whether the phrase ever appears.

- For contradiction handling, Marina is told to ask one short clarifying question. If a customer contradicts themselves several times in one conversation, she will likely ask once and then go quiet on later contradictions — the instruction does not specify what to do on repeat contradictions. This is acceptable for now.

- Tone changes for an LLM cannot be verified by an automated test. The only deterministic test that runs is the JSON-loads / persona-builder guardrail Brief 258 added, which catches malformed JSON or missing keys but says nothing about whether Marina sounds human. Real verification is Calvin's live retest.

- Brief-reviewer caught one self-referential bug during review: the draft contained an em-dash inside the very section that bans em-dashes for unboks. It was removed before the brief landed.

- The change is unboks-only. BlueMarlin, Adamus, and Consulta Despertares Marina personas are untouched.

## What did NOT change

No code changed. Marina's core prompt-building flow, her booking and inquiry logic, her one-Claude-call-per-message contract, and every other tenant's persona are all unchanged. Brief 258's existing rules — the pronoun and terminology fixes ("AI Agent" / "we" / "your agent"), poor-fit lead handling, identity rules, and the original five example pairs — all remain exactly as Brief 258 left them. Brief 259 only *adds* to the unboks tone section; it does not remove or rewrite anything Brief 258 put in place. No tests changed. No deployment infrastructure changed. The deploy is data-only and the rollback path is a single image revert.
