# EXPLANATION 250 — Fix wa_get_full_history to return newest N + anchor escalation summary on latest customer message

## In one sentence
The dashboard escalation summary box now reflects what the customer just said instead of what they were saying 20 messages ago, because a long-buried bug that was feeding the AI only the oldest part of long conversations is now fixed.

## What's changing and why

For any WhatsApp conversation longer than about 20 messages, the system had been quietly handing the AI only the OLDEST chunk of the conversation when it built the escalation summary that operators read in the dashboard. Calvin's live test caught it: his customer's thread was 44 messages long, the AI only ever saw the first 20, and the customer's most recent message — "my dog is sick, can we make it 10 o'clock?" — was completely invisible. The summary box told Calvin to confirm an 11:00 appointment that the customer had already asked to move. An operator following the summary would have made the wrong call.

Two things change with this fix. First, the part of the system that pulls conversation history out of the database now grabs the most recent messages instead of the oldest ones — so the AI sees what's actually happening right now, not what was happening at the start of the thread. Second, the AI's instructions for writing the summary now explicitly say: when the customer's latest message changes the request (asks to reschedule, proposes a new time, introduces a new reason), the "what the customer wants" and "what you need to decide" sections must reflect that NEW request, not whatever was on the table earlier in the thread.

## Step by step — what the code does now

PULLING WHATSAPP CONVERSATION HISTORY

When any part of the system asks for a customer's WhatsApp history with a cap (for example, "give me up to 20 messages"), the database now picks the 20 MOST RECENT messages. It still hands them back in oldest-first order, so every existing piece of code that walks the list forward in time keeps working unchanged. Before this fix, the same request would have returned the 20 OLDEST messages from the entire thread — meaning that on a 44-message conversation, messages 21 through 44 were silently dropped and never seen by anything downstream.

This single change quietly fixes five places in the system that were all silently affected:
- the part that builds escalation summaries for the dashboard (the place where Calvin's bug showed up)
- the part that decides whether a re-escalation should happen for social DMs
- an internal helper that finds the most recent customer message for learning saves
- the dashboard endpoint that shows the full conversation thread in the detail view
- the dashboard endpoint that builds context for "suggest a reply"

All five wanted the most-recent messages all along. None of them were actually getting them on long conversations.

WRITING THE ESCALATION SUMMARY

When the AI generates the summary box that appears at the top of an escalation in the dashboard, it now follows an additional instruction: if the customer's LATEST message changes what's being asked for — a reschedule request, a new proposed time, a new reason like "my dog is sick" — the summary's "what the customer wants," "what the operator needs to decide," and "recommended options" sections must reflect that newest request. Older proposed times that the customer hasn't actively kept on the table either move into the "previously proposed" bucket (if they were explicitly withdrawn) or simply drop out of the current proposals list. The intent of the rule is plain: tell the operator what to decide RIGHT NOW based on the latest message, not what was being decided earlier in the thread.

## Edge cases

- If a conversation has fewer messages than the cap (for example, an 8-message thread with a cap of 20), behavior is identical to before — all 8 messages come back, oldest first. The bug only ever manifested when total messages exceeded the cap.
- If the AI sees the latest message but the customer's wording is genuinely ambiguous about whether they're proposing a new time or just asking a question, the AI is allowed to keep older proposals in the list. The new rule says older times "may be omitted" — it doesn't force their removal. This is intentional: stripping context too aggressively could lose information the operator wants. A stricter rule was considered and deferred.
- Existing escalation summaries that were generated BEFORE this fix landed still contain stale information — they were written from the truncated history. They will auto-correct the next time a new customer message arrives and triggers a fresh summary. Backfilling old summaries was considered and explicitly left out of scope.
- The "Ill be there" message being mis-captured as a confirmed time (a separate quirk Calvin flagged) is a different problem in a different part of the prompt. This fix doesn't touch it; it's deferred to a future small change.
- The conversation-history caps at the five call sites (20, 30, 200, etc.) were left as they were. The fix at the database layer makes those caps work the way they were always intended. Whether 20 messages of context is enough for the AI is a separate decision.

## What did NOT change

The AI's main personality and reply logic were not touched. The booking flow, the customer-facing reply path, and the way Marina decides what to say to a customer all behave identically. The escalation summary's data structure (the list of fields the dashboard reads) is unchanged — no new fields, no removed fields, just better-quality content in the existing fields. The five callers of the conversation-history function received no signature change, no return-shape change, and no order-of-results change; they simply now receive the data they were supposed to be receiving all along.
