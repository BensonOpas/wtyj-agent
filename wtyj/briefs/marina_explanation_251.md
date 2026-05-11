# EXPLANATION 251 — Upgrade /ai-editor style prompts to per-style distinct instructions

## In one sentence

The dashboard Agent Editor's five style buttons (Professional, Warmer, Shorter, Friendlier, Direct) now produce noticeably different rewrites of the same draft instead of all returning near-identical output.

## What's changing and why

When an operator is composing a reply in the dashboard, they can click one of five style buttons to have the AI rewrite their draft. Calvin tested this live and found that all five buttons returned almost the same text — "Shorter" wasn't reliably shorter, "Direct" didn't feel direct, and the whole feature didn't feel premium. The cause was on the backend: every style button hit the exact same instruction template ("Rewrite the following text in a more X style") with only the style word swapped in. Asking Claude to be "more professional" versus "more friendlier" with no other context isn't enough for it to produce meaningfully different rewrites, especially when the operator's draft is already neutral.

This change replaces that single template with five completely separate, multi-line instructions — one per style. Each instruction explains the actual goal of that style in its own words. "Shorter" now explicitly tells the AI the output must be shorter than the input. "Warmer" tells it to show genuine appreciation and feel like a real person who cares. "Direct" tells it to be crisp and efficient with no filler. All five share a common set of ground rules (preserve the original meaning, do not invent any information, do not use em dashes, return only the rewrite with no preamble or explanation). The exact wording came from Calvin in issue #21 and was used verbatim.

## Step by step — what the code does now

STEP: Operator clicks a style button in the Agent Editor

The frontend sends a request to the editor endpoint with the operator's draft text plus which style button was clicked. The endpoint validator first checks the style is one of the five allowed values; anything else gets rejected with a 400 error before any AI work happens.

STEP: The system picks the right instruction for the chosen style

A new lookup table inside the dashboard code holds five fully-written instructions, one for each style. When a style request comes in, the system looks up the matching instruction. If for some reason a style name slipped past the validator (a future internal caller bypassing the front door), the lookup returns nothing and the system raises a clear "unknown style" error instead of sending a half-built prompt to the AI.

STEP: The system builds the final prompt

The chosen instruction is glued onto the operator's draft text with a simple "Text:" label. That combined prompt is then sent to Claude Sonnet (the same model used before — this change does not switch models or add an API call).

STEP: Claude returns a rewrite, the system returns it to the dashboard

The single AI call returns the rewritten message. The system passes it back unchanged for the operator to review in the composer. The operator can then send, edit, or discard it just as before.

STEP: Five new tests guard against silent regressions

Each of the five styles has a test that builds the prompt for that style and checks two things: the distinctive phrases for that style ARE present, and the distinctive phrases from the four OTHER styles are NOT present. So if a future change accidentally makes "Friendlier" and "Warmer" share wording, or strips the "must be shorter than the input" rule out of "Shorter", a test fails. Every test also confirms the "Do not use em dashes" rule is present in every style's prompt.

## Edge cases

- If the operator's draft is already extremely short, the "Shorter" style still gets told to make it shorter. Claude is trusted to do its best; there is no Python-side length check that rejects or retries the output. If the AI returns something that isn't actually shorter, the operator sees it in the composer and can discard or re-run.
- If Claude ignores the "no em dashes" rule, the operator will see em dashes in the draft. There is a separate safety net on the customer-facing send path (added in an earlier brief) that strips em dashes from messages actually sent to customers — so even if an em dash slips through into the composer and the operator hits send without noticing, the customer never sees one.
- The endpoint already accepts a context block including conversation ID, escalation mode, and channel. The new instructions still do not use those fields. So a rewrite for a WhatsApp draft and a rewrite for an email draft on the same input will get the same prompt. Acceptable for now; if Calvin sees channel-mismatched outputs in production, a follow-up brief can add channel-aware tweaks.
- A future internal caller that builds a request bypassing the endpoint validator and asks for an unknown style will now get a clear "unknown style" error instead of an empty or malformed prompt going to Claude.
- Token cost per style request is slightly higher because the new instructions are longer than the one-line template. The model used (Sonnet) is unchanged, and the cost per click is still tiny.

## What did NOT change

The other two Agent Editor actions — Translate and Fix — are completely untouched. The endpoint validator, the model selection, the response shape, and the way the operator's draft flows from frontend to backend to AI and back are all the same. No customer-facing behavior changed: this is purely about what the operator sees in the composer when they click a style button. The Marina/DM agent prompts that handle real customer messages were not modified, no business data in client.json was touched, and no database schema migration was needed.
