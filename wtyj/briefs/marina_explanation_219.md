# EXPLANATION 219 — Marina actually USES the approved learnings

## In one sentence

When the team coaches Marina by answering an escalation, the next customer who asks a similar question now gets a Marina who has actually read those prior answers as authoritative context — the system finally learns from operator actions instead of just storing them.

## What's changing and why

A week ago we shipped the storage half of this feature: every time an operator answered a customer question inside a soft or hard escalation, the system saved that question-and-answer pair as an "approved learning" row in the database, marked as something Marina is allowed to use automatically. The frontend grew a Learning Entries panel where the team can list, approve, save, and delete those rows.

The catch: Marina herself never opened that table. The rows piled up. When an operator wrote "tell dietary-restriction customers we accommodate gluten-free with 24 hours notice," that answer sat in storage and the next customer who asked the same dietary question got a fresh, possibly-different Marina answer. The coaching wasn't sticking.

This change closes that loop. When Marina builds the instructions she sends to Claude for a customer message, she now pulls the most recent operator-approved answers for that channel (capped at 20) and drops them into her prompt as an "APPROVED ANSWERS" block. She is told these are authoritative — the way the human team wants this kind of question handled going forward — and she is told to match the spirit, not copy word-for-word. The factual context informs her reply; her voice and writing style still come from her persona.

The feature is gated behind a per-tenant flag in client.json (default off). Unboks gets it turned on first; BlueMarlin, Adamus, and Consulta Despertares stay off until we eyeball-validate it in production for a few days. This is the safer rollout because the prompt builder is the most sensitive code in the project, and tenants like BlueMarlin may have older or noisier rows in their learnings table.

## Step by step — what the code does now

FETCH RECENT APPROVED LEARNINGS FOR A CHANNEL

A new database helper takes a channel name (like "whatsapp" or "email") and a row cap, opens the database, and pulls the most recent learning rows that match three filters at once: the row's channel matches, its status is either "approved" or "saved" (not draft suggestions, not deleted), and the operator did not flip its "AI may use automatically" toggle off. Results come back newest-first as a simple list of question-and-answer pairs. If the channel name is empty or the cap is zero or negative, the helper returns an empty list without touching the database.

BUILD THE APPROVED ANSWERS PROMPT BLOCK

A new helper inside Marina's prompt builder is responsible for turning those learning rows into the text that gets injected into Marina's instructions. It first checks the tenant's client.json for the feature flag — if the tenant hasn't opted in, it returns an empty string immediately and Marina's prompt looks identical to before. If the flag is on, it calls the database helper. If anything goes wrong fetching rows (any error at all), it quietly returns empty and Marina's prompt is unaffected. If the database returns no rows, it returns empty.

When there are real rows to inject, the helper formats each one as a "Q: ... / A: ..." pair (or just "A: ..." if the original customer question was missing) and skips any row whose answer is blank. It then wraps the whole list with a header that tells Marina these are operator-curated answers, the team has handled similar customer questions this way before, she should treat them as authoritative context for how the team wants these situations handled going forward, and she should match the spirit without copying verbatim if the customer phrasing differs. The returned text begins with two newlines so that when it's injected into the larger prompt, there's a clean blank-line break above it.

INJECT THE BLOCK INTO MARINA'S SYSTEM PROMPT

Marina's main prompt builder now calls the new block helper once and stitches the result into the larger prompt template — placed deliberately between the customer file block (everything we know about this specific customer) and the writing style block (Marina's voice and tone rules). That position sits in what the brief calls the "factual context zone," not the "voice zone," so the operator-approved answers inform what Marina says without overriding how she says it.

When the block helper returns empty (flag off, or no rows match), the spacing in the prompt collapses cleanly back to exactly what it was before this change — no dangling header, no extra whitespace, no token waste. When the block helper returns content, there's exactly one blank line above and below the new block.

The injection happens in one place but covers both Marina's email path and her WhatsApp path, because both call into the same prompt builder. The channel argument flows through, so an email conversation pulls email-channel learnings and a WhatsApp conversation pulls WhatsApp-channel learnings.

## Edge cases

- If the tenant's client.json has no "features" key at all, the helper treats it as flag-off and skips injection. Pre-Brief-219 behavior preserved.
- If the database is unreachable or the query throws for any reason, the helper swallows the error and returns empty. Marina's prompt falls back to its pre-Brief-219 shape. The customer still gets a reply; the operator-coached context is just missing for that one message.
- If a row's answer field is blank, that row is skipped. A row with a missing customer question but a non-empty answer is still included as just "A: ..." text.
- If 50 approved learnings exist for a channel, only the 20 most recent are pulled. The older ones are silently ignored. This is deliberate cost-and-token discipline — operators answer dozens of escalations per week, and unbounded growth would eventually blow Claude's context window.
- An operator's approved answer in an email conversation does NOT teach Marina how to answer the same question on WhatsApp. The channel filter is strict. A long email-style answer would read wrong as a WhatsApp reply, so cross-channel sharing is left as a future enhancement.
- If an operator changes their mind and sets a learning's "AI may use automatically" toggle to off, that row stops appearing in Marina's prompt on the next message. There is no caching layer; every prompt build re-queries.
- If a learning row has status "suggested" (operator hasn't yet approved it) or "deleted," it is excluded. Marina only sees operator-vetted rows.
- Marina is instructed to match the spirit, not copy verbatim. She may still phrase the answer differently than the operator did, especially if the customer's question is worded differently. This is intentional — the coaching is meant to be guidance, not a script.
- The feature ships for Marina (email + WhatsApp) only. The DM agent that handles Instagram and Facebook DMs does not yet read approved learnings; that's a follow-up brief. The reasoning: Marina is the higher-stakes path (booking flow, customer-facing money decisions), so it ships first and gets validated before the DM path inherits the same logic.

## What did NOT change

Brief 215's storage path is untouched — escalation answers continue to be saved as approved learnings exactly as before. Marina's persona, writing style block, language rules, booking behavior rules, escalation behavior rules, and JSON output schema are all unchanged. The customer file block (what Marina knows about a specific repeat customer) is unchanged. The DM agent's prompt builder is not modified. No customer-facing reply text is hardcoded anywhere; Marina still generates every reply herself, now informed by operator-approved context when the tenant has opted in. For tenants that haven't opted in (BlueMarlin, Adamus, Consulta Despertares as of this commit), the rendered prompt is byte-identical to what it was before Brief 219.
