# EXPLANATION 211 — Dashboard contract fields

Plain-English explanation of commit `380a059` for an operator who doesn't read code.

## What was broken

When you opened `dashboard.unboks.org` and clicked on an escalation (the Calvin Adamus row), the right-hand detail pane showed only the header — no message thread, no reply box, nothing. You couldn't reply to escalations from the dashboard at all.

This wasn't a bug on the frontend. SR built a smart reply composer that decides what to render based on a few flags from the backend. My backend just wasn't sending those flags. So the composer's logic was: "I don't know if this conversation is escalated, I don't know if AI is muted, I don't know what mode it's in — I'll render nothing." And it rendered nothing.

## What changed

Two response shapes got new fields, both computed on the fly from data we already have. No new database columns, no new tables.

**1. The conversation detail response now tells the dashboard about the escalation state.**

When the dashboard asks for a conversation (e.g., to render Calvin Adamus's email thread), the backend now adds four extra fields to the answer:

- `escalated` — yes/no, derived from looking up the conversation in our `conversation_status` table. If status is "open" it's escalated.
- `escalationResolved` — yes/no, true when the operator has clicked "resolve" on a previous escalation.
- `escalationMode` — placeholder, always returns `null` for now. This will be `"soft"` or `"hard"` once Tier 2 lands. Returning `null` makes the dashboard render the existing legacy action buttons, which is a working UX while we wait.
- `aiMuted` — placeholder, always `false`. This becomes meaningful once Tier 2 adds a "human takeover" feature.

The `null` and `false` values are deliberate. They're honest: we haven't built soft/hard mode yet, so we don't pretend we have. The dashboard handles the "we don't know" case by rendering a simpler UI, which is fine.

**2. The escalations list response now tells the dashboard where to find the conversation thread.**

When the dashboard asks for the list of all escalations, each row already contained `customer_id` (the email or phone). But SR's mapper looks for a field called `phone` to know how to fetch the message thread when you click the row. For email rows, my backend now also computes the right routing key — something like `email::subj:calvin@gaimin.io:testing` — by looking at our existing email_thread_state.json file and finding the thread whose key contains the customer's email. For WhatsApp rows, the existing customer_id IS the routing key, so we just pass it through.

Before this change, the dashboard had no `phone` field on email escalation rows, so it built a fake fallback id like `esc:1`. Asking the backend about `esc:1` returned an empty thread. So even if you got the row to show, clicking it gave you nothing.

## What it does now

- The Escalations panel still shows the Calvin Adamus row (fixed earlier today by stringifying the `id` field).
- Clicking that row now loads the actual email conversation in the right pane — the back-and-forth between Calvin and Marina, with timestamps.
- Below the thread, you'll see the legacy action buttons (resolve, delete, reply via the older flow). The fancy new soft/hard composer SR built doesn't render yet because the backend hasn't been told the mode — that's intentional, comes in Tier 2.

## What it doesn't do (still pending Tier 2)

- No "Send to Marina" guidance flow yet (soft mode).
- No "Reply to customer" composer with AI editor yet (hard mode).
- No human-takeover toggle.
- No mode switching.

These all need either new database columns or new endpoints. Brief 211 was the minimum-risk piece — read-only, no schema changes, deployable in seconds. Tier 2 is meatier work and was deliberately scoped to a future brief.

## Files changed

- `wtyj/dashboard/api.py` — added a `_conversation_status_fields()` helper, applied to both branches of `get_conversation()` (email and whatsapp).
- `wtyj/shared/state_registry.py` — extracted a shared `_find_email_thread_key_for()` helper from existing email-reply code, used it in `get_all_escalations()` to set the `phone` routing key per row.
- `wtyj/tests/social/test_211_dashboard_contract_fields.py` — five tests covering each new field's behavior.
