# EXPLANATION 233 — Distinguish operator-typed email replies from Marina-generated ones

## In one sentence
When an operator types an email reply through the dashboard and sends it verbatim to the customer, the system now records that reply as authored by the operator instead of by Marina, so the conversation history can show who actually wrote each message.

## What's changing and why

Until now, every outbound email written from the dashboard — whether Marina drafted it or an operator typed every word themselves — was saved into the conversation log as if Marina wrote it. The customer always saw an email signed by Marina, but inside the dashboard the conversation view also showed the message under Marina's avatar even when an operator had typed the entire reply by hand. SR raised this as a problem: it makes it look like the AI wrote the message when in fact a human did.

This change fixes the underlying data so the dashboard can tell the two cases apart. Two of the three places where the dashboard writes outbound email — the regular operator reply and the hard-escalation reply — now mark the saved message as authored by an operator. The third place, where an operator gives Marina coaching and Marina then rewrites the customer-facing reply herself, keeps marking the saved message as Marina's, because in that path Marina really is the author of what the customer sees. The frontend will need a follow-up change before operators visibly see a different avatar; right now the back end exposes the distinction and the front end falls back to Marina's avatar until SR ships his half.

## Step by step — what the code does now

STEP: Saving an outbound email message

When the system saves an outbound email reply into the conversation log, it now accepts an optional label saying who wrote it. If nothing is passed, the message is labeled as Marina's, which preserves how every existing record in the system already reads. If the caller explicitly passes "operator," the message is labeled as operator-written instead. The body of the email and the timestamp are saved exactly as before.

STEP: Operator types a reply in the dashboard's email reply box

When an operator clicks send on the dashboard's email reply form, the system delivers the email to the customer over SMTP and then saves a record of that reply into the conversation log with the new "operator" label. Before this change, the same record was being saved with Marina's label.

STEP: Operator sends a reply on a hard escalation

When an operator answers a hard-escalation case by typing a reply that the system then sends verbatim to the customer, the saved record is now labeled as operator-written. Before, it was labeled as Marina's.

STEP: Operator gives Marina guidance on an escalation

This path is unchanged. The operator types coaching for Marina, and Marina then writes a fresh customer-facing reply in her own voice. The saved record continues to be labeled as Marina's, because she is genuinely the author of what the customer received.

STEP: Building the conversation detail view for the dashboard

When the dashboard asks for the full message history of an email thread, the system walks each saved message and translates the stored author label into the value the frontend expects. Customer messages still become "user." Marina messages still become "assistant." The new "operator" label is now passed through unchanged, so the frontend can render an operator-typed message under a different avatar once SR wires that up. Until then, the frontend's existing fallback treats anything it doesn't recognize as Marina, so today's view looks identical.

STEP: Building the inbox list of conversations

When the dashboard lists email conversations in its inbox, each row carries a label saying who sent the most recent message. The same translation rules apply: customer becomes "user," Marina becomes "assistant," and "operator" passes through unchanged. This means a conversation whose latest message was typed by an operator can be flagged distinctly in the inbox once the frontend opts in.

STEP: Test suite alignment

Two older tests had been written to assert that operator-typed replies were saved under Marina's label. Those tests were locking in the very behavior this change corrects, so they have been updated to assert the new operator label. A new set of tests covers the default-stays-Marina case, the operator-label-persists case, the conversation-detail mapper passing the operator label through, the inbox list mapper passing it through, and legacy Marina-labeled records continuing to map to "assistant" so historical data renders unchanged.

## Edge cases

- If a customer's email thread has years of older messages where an operator typed the reply but the system saved it as Marina's, those historical records keep their old Marina label. Only messages saved after this deploy carry the new operator label. This is intentional — there is no data migration, and the dashboard renders these older entries the same as before.

- If SR's frontend has not yet shipped a change to recognize the new operator label, operator-typed messages still show up under Marina's avatar in the conversation view. The data is now correct underneath; only the visible rendering is unchanged until the frontend half lands.

- If the system tries to save an outbound email reply for a customer whose thread does not yet exist, the function returns nothing and silently skips the save, exactly as it did before. The email itself was already sent over SMTP upstream, so the customer still receives it; only the conversation log entry is missed. This matches today's behavior and is not made better or worse by this change.

- If a future caller forgets to pass the operator label on a verbatim-send path, that reply will fall back to being labeled as Marina's. This is a code-discipline issue at the call site, not a data integrity one — only the two known verbatim-send paths needed updating, and both were updated in this change.

## What did NOT change

Marina's prompt was not touched. The booking flow was not touched. The customer-visible content of any email — the subject line, the body, the signature — is exactly the same as before; the change is only in how the dashboard's internal conversation log labels the author of an outbound message. The escalation guidance path, where Marina genuinely reformulates an operator's coaching into the customer-facing reply, was deliberately left alone so it continues to be saved as Marina's authorship. No customer data, no thread state files, and no historical messages were migrated or rewritten.
