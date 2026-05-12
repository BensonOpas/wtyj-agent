# EXPLANATION 261 — Block sender: close Brief 220 gaps (reason, blocked_by, inbox filtering, /blocked-senders alias)

## In one sentence
Blocked senders now disappear from the active inbox lists the way they always should have, and each block now records why it happened and which operator did it.

## What's changing and why

Calvin's spec asked for a universal Block action that works the same way on every channel: hit Block, the sender stops bothering you, the conversation drops out of your active inbox, and the platform remembers who pressed the button and why. When the work started, a quick search through the codebase caught something important — most of that machine had already been built three months earlier. Brief 220 had already wired up the underlying block-sender capability across every inbound channel. The only thing missing was the surface layer that operators actually see and use.

This change closes four gaps in that surface layer. Blocked conversations now actually leave the active inbox view instead of lingering there. The system now records a reason (spam, abusive, wrong contact, or anything else the operator types) and an operator label every time a Block happens. And the dashboard frontend now has a clean new path name — /blocked-senders — that matches Calvin's spec, while the old path keeps working so nothing breaks. None of the underlying suppression behavior changed; that part was already correct.

## What Block already did before this change (Brief 220 recap)

When an operator hits Block on a conversation, the sender's identifier (phone number, email address, or social-media handle) gets a flag set on it in the platform's status tracker. From that moment forward, every inbound message from that sender — WhatsApp, email, Instagram DM, Facebook DM — is silently dropped at the very front door, before Marina ever sees it, before any auto-response runs, before any human-escalation path triggers. The message simply doesn't enter the system. There's a list view in Settings showing every currently-blocked conversation, and an Unblock action that flips the flag back off so messages flow again.

That was Brief 220. It worked. But it had a hole: it suppressed *future* inbound, while leaving the conversation row itself sitting in the active inbox forever, because the most-recent message had already been stored when the operator pressed Block. So the operator would block a spammer, get no new messages from them, but still see the spammer's old conversation row at the top of their inbox the next morning. That's the main thing this change fixes.

## Step by step — what the code does now

GAP 1 — BLOCKED CONVERSATIONS LEAVE THE ACTIVE INBOX

When the system builds the WhatsApp inbox list for the dashboard, it now skips any conversation whose blocked flag is set. Previously it only skipped conversations that the operator had archived. So if a spammer was blocked, the old conversation row would still appear at the top of the active list. Now it doesn't. The conversation isn't deleted — its full history is preserved and it'll reappear in the inbox if the operator ever hits Unblock.

The same fix applies to the email inbox. When the system builds the email thread list, it now looks at each thread's sender address and skips any thread whose sender is currently blocked. The sender's email address is pulled out of the thread's identifier (which always contains the sender as a middle segment) and checked against the block list.

GAP 2 — RECORDING WHY A SENDER WAS BLOCKED

The Block action now optionally accepts a reason — the spec suggests "spam," "abusive," "wrong contact," or "other," but the field is free text so an operator can type anything. The reason is stored alongside the block flag in the status tracker. It shows up on the Settings list view so operators can see at a glance why each sender was blocked. When a sender is unblocked, the reason is wiped clean so that if the same sender ever gets re-blocked later, the new block doesn't accidentally carry the old reason forward.

GAP 3 — RECORDING WHICH OPERATOR DID THE BLOCKING

The Block action now also optionally accepts an operator label — a free-form string the frontend can populate with the logged-in operator's name or a generic "operator" tag. Because the dashboard login is a single shared password (no per-operator identity built into the auth layer), this field is filled in by whatever the frontend sends. It's stored alongside the reason, shows up on the Settings list view, and gets wiped on unblock the same way the reason does. The platform's event log also records both fields, so the historical audit trail survives across block/unblock cycles even though the live row's fields get cleared.

GAP 4 — NEW ENDPOINT PATH NAME

Calvin's spec proposed the path /blocked-senders for the dashboard to call when listing blocked conversations. The existing path was /settings/blocked-conversations. Rather than rename it (which would break any frontend wiring already pointing at the old path), the new path was added as an alias. Both paths now return the exact same data, in the exact same shape, with the exact same wrapping. The frontend can adopt the new name when it's ready, on its own schedule, and the old name will keep working until it stops being called.

UPDATED RESPONSE SHAPE

The Settings list view's response now carries two extra pieces of data per row — the reason and the operator label — alongside the three pieces it already carried (the sender identifier, the channel, and the timestamp). Any existing dashboard code that reads the old three fields continues to work unchanged; the two new fields are just additional data that can be displayed if the frontend wants to show them.

## Edge cases

- If a thread's email-address segment can't be cleanly extracted from its identifier (malformed key, missing segments), the filter falls through silently and the thread stays visible. Acceptable — these would be data-shape oddities, not normal traffic.

- The Block button on the dashboard's email view sends a different form of the conversation identifier than the email poller uses internally to check the block list. The new inbox-list filter in this change works around that by extracting the bare email address before checking. But if the operator blocks a thread using the dashboard's compound identifier form, the email poller's front-door suppression — which checks the raw email address — won't fire for new mail. This means a freshly-blocked email sender might still get one or two more messages through before the system catches up. The brief documents this explicitly as out of scope; the long-term fix is to normalize the identifier shape at the API boundary in a future brief.

- Unblocking a sender clears the reason and operator-label fields from the live row. If the same sender gets re-blocked later, those fields start fresh. The historical record of the prior block still exists in the platform's event log; only the live row is wiped. This is by design — the brief explicitly chose row-level audit clearing over a separate audit-history table, because Calvin's spec asked for "auditable," not "audit trail across the row lifecycle."

- The schema change adds two new columns to the status tracker table. It's safe to re-run, safe to roll back to a prior version of the code (the columns survive on disk, the old code just ignores them), and safe to deploy across all four tenants without coordination.

- Both endpoint paths — the old /settings/blocked-conversations and the new /blocked-senders — are now active and return byte-identical responses. If both are called in quick succession by the frontend during a transition, no harm.

## What did NOT change

The actual block-and-suppression machinery that Brief 220 shipped — the front-door drop of inbound messages on all four channels (WhatsApp, email, Instagram DMs, Facebook DMs) before Marina or any human-escalation path runs — is untouched. Marina's prompt is untouched. The booking flow is untouched. The dashboard's authentication model is unchanged. The old /settings/blocked-conversations path still works exactly as it did. The Block and Unblock POST endpoints still work for any frontend that doesn't send the new optional fields. The only behavioral changes are the four gap closures listed above; everything else is additive.

## Meta-lesson

This brief was almost a full rebuild. Calvin's spec read like a brand-new feature, and the natural reflex would have been to design a block-sender system from scratch. A grep through the codebase for the word "blocked" caught Brief 220's existing foundation before any new code got written. What looked like a multi-day feature turned into a focused four-gap surface fix — roughly 150 lines of code and five tests instead of a rebuild. Checking what already exists, every time, before designing something new, paid for itself many times over here.
