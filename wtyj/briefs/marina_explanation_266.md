# EXPLANATION 266 — Wire Brief 264's `createPendingLearningFromOperatorReplies` toggle into the operator reply paths

## In one sentence

The "create pending learning from operator replies" toggle in tenant settings now actually does something — when you turn it on, the AI no longer silently treats every operator reply as a pre-approved answer it can reuse forever; instead each reply lands in a review queue waiting for an operator to explicitly approve it.

## What's changing and why

Brief 264 shipped a toggle in the tenant settings screen called "Create pending learning from operator replies." The toggle saved its on/off value to the database, but nothing on the AI side read that value, so flipping the switch had no effect. Calvin turned it on during live testing, saw no pending learnings appear, and filed issue #36. Brief 266 finishes the wire-up.

After this change, when an operator types a reply or piece of coaching into the dashboard and sends it through one of the passive paths (the normal WhatsApp reply box, the soft-mode WhatsApp relay box, the email reply box, the WhatsApp guidance box, or the email guidance box), the system now checks the tenant's toggle:

- If the toggle is ON, the operator's reply is filed as a suggested learning. The AI cannot use it until a human opens the learning review screen and approves it. This is the new behavior Calvin asked for.
- If the toggle is OFF (the default), the operator's reply is filed as an approved learning that the AI can immediately reuse on future similar questions. This is exactly the behavior the system has had since Brief 215, preserved unchanged so existing tenants are not surprised.

The Send & Resolve button on the escalation screen is deliberately not affected by the toggle. That button is the operator explicitly saying "save this with these specific settings" — it has its own checkboxes ("auto-use next time?" and a category dropdown) and those choices must always be honored exactly as the operator set them, even if the global toggle is on.

## Step by step — what the code does now

NEW HELPER: a single shared "save this reply as a learning" function

A new helper function was added that all five passive reply paths now call. When invoked, it does the following in order:

1. Looks at the reply text. If it is empty or only spaces and line breaks, the helper stops and saves nothing.
2. Looks up whether any existing learning row already exists for the same conversation with the exact same reply text (in any state other than "deleted"). If a match is found, the helper stops and saves nothing — this prevents the same reply being saved twice when an operator re-sends a reply or the page is reloaded.
3. Reads the tenant's "create pending learning from operator replies" toggle from settings.
4. Looks up the most recent customer message in that conversation so the saved learning has the original customer question attached as context.
5. If the toggle is the string "true," the helper writes the reply into the learnings table with status "suggested" and the "AI may use this automatically" flag turned off. These rows are invisible to the AI's prompt builder by construction — they sit in the pending list waiting for human approval.
6. If the toggle is anything else (off, empty, never set), the helper writes the reply into the learnings table with status "approved" and the "AI may use this automatically" flag turned on. This is the historical behavior preserved verbatim.
7. Logs a single event noting which path was taken ("pending" or "approved") and the new row's identifier.
8. If any error occurs anywhere in steps 1 through 7, the helper catches it, logs a write-failure event, and returns nothing. It never raises, and it never blocks the operator's reply from being sent to the customer.

REPLY PATH 1: hard-mode WhatsApp reply

When the operator sends a normal reply to a WhatsApp escalation, the system now sends the message to the customer, marks the notification as replied, and then calls the new helper with the reply text. The previous inline try/except block that wrote an approved learning is gone — the helper handles all of that.

REPLY PATH 2: soft-mode WhatsApp relay reply

Same shape as above for the soft-mode relay flow (where the operator's message is relayed to the customer through Marina's wrapper). The reply is sent, the escalation is marked replied, and the helper is called.

REPLY PATH 3: email reply

Same shape, for replies sent over email. The reply is sent, the escalation is marked replied, and the helper is called with the email channel.

REPLY PATH 4: WhatsApp guidance

When the operator provides coaching/guidance for the AI to use on a WhatsApp conversation (rather than a direct reply), the guidance text is now also routed through the helper.

REPLY PATH 5: email guidance

Same shape as the WhatsApp guidance path, for email coaching.

WHAT THE RESOLVE BUTTON DOES — UNCHANGED

The Send & Resolve button on the escalation screen still works exactly as before. When the operator checks "save this as a learning" on that button's form, the system reads the operator's "auto-use next time" checkbox and the operator's chosen category from the request and writes a learning row using those exact values. The global toggle is not consulted here. This was a deliberate decision, and Test 6 is the regression guard that keeps it that way.

## Edge cases

- If the operator sends an empty reply or a reply that is nothing but whitespace, no learning is created in either toggle state. The reply itself still goes to the customer if the upstream code lets it through; only the learning save is skipped.
- If the operator sends the same reply text twice on the same conversation (for example by clicking send twice, or by re-replying after a page reload), only the first one creates a learning. The second one is silently dropped by the duplicate guard.
- The duplicate guard intentionally ignores learnings that have been dismissed (status "deleted"). So if the operator dismissed a suggested learning, then later types the same answer again as a fresh reply, a new pending row will be created so the operator gets a chance to re-review. This is a known and accepted trade-off — if a tenant later wants "once dismissed, never re-suggest," that is a follow-up product change.
- If the toggle value in settings is anything other than the exact string "true" (including blank, "false", "1", "yes", or never set at all), the helper falls back to the legacy "create approved learning" behavior. The toggle is strict-true-only on purpose.
- If the learning-save call itself blows up for any reason (database lock, schema mismatch, helper-not-found), the operator's reply still goes to the customer. The error is logged as `learning_write_failed` and otherwise ignored.
- If a tenant has been silently relying on every operator reply auto-becoming an approved learning and then flips the toggle on without telling anyone, the AI will appear to stop "learning" until somebody opens the pending list and approves entries. The default value is off, so this only affects tenants who actively turn it on.
- A round-1 reviewer catch worth noting: an earlier draft of this brief proposed routing the Send & Resolve path through the same helper. That would have silently dropped the operator's "auto-use next time" checkbox and the operator's chosen category, because the helper has no slots for those two fields. The brief was corrected to leave the resolve path alone, and a sixth test was added that proves the resolve path still honors both operator-supplied fields even when the global toggle is on.

## What did NOT change

The AI's reply prompt was not changed. The booking flow was not touched. The customer messages stored in the database are unchanged. The Send & Resolve button's behavior is preserved exactly — its "auto-use next time" checkbox and category dropdown still control the resulting learning row regardless of the new toggle. The Brief 263 endpoint that lets an operator explicitly suggest a learning ("Suggest as learning" button) was also not touched; it always creates a pending row and ignores the toggle, by design. No database schema changes were made; this is purely a routing change inside the dashboard's reply endpoints.
