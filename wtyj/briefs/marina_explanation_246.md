# EXPLANATION 246 — Hard-takeover WhatsApp /reply: send operator text verbatim, store as role=operator

## In one sentence
When an operator has hard-taken-over a WhatsApp conversation and types a reply in the dashboard, the system now sends that text to the customer exactly as written and labels it as coming from the operator — instead of secretly running it through Marina, who was sometimes refusing the operator's text and sending her own refusal to the customer.

## What's changing and why

This fix exists because of a real test Calvin ran during the unboks live-test verification. Calvin had hard-taken-over a WhatsApp conversation (meaning: Marina is muted, the human is the author of every reply from this point on) and, to stress-test the system, he typed an intentionally abusive line into the dashboard composer to see what would happen. What the customer received back was not Calvin's text — it was a polite Marina refusal: "That's not something I'll engage with. If you need help with your Monday appointment or anything else, I'm here." And in the dashboard's conversation trail, that refusal showed up labeled as "MARINA," as if Marina had spoken in the middle of a hard takeover. Both behaviors were wrong. Hard takeover is supposed to mean exactly that — the operator is in control, the operator's words go out untouched, and the trail shows the operator as the author.

The cause was that the WhatsApp reply path in the dashboard had only ever had one mode: it always handed the operator's typed text to Marina and asked her to "reformulate" it before sending. That made sense for soft mode (the operator is coaching Marina with raw notes and Marina polishes them into a customer-friendly reply), but it had never been split out for hard mode. Email had been split correctly six weeks ago, but WhatsApp had been left behind. After this change, the dashboard checks which mode the escalation is in: if it's hard mode, the operator's text goes straight to the customer with no Marina involvement, and the conversation trail records it as an operator message; if it's soft mode or one of the older escalations that don't have a mode set, behavior is unchanged from before.

## Step by step — what the code does now

OPERATOR CLICKS REPLY ON A WHATSAPP ESCALATION

When the dashboard receives the reply, the system first looks up which escalation this is and what mode it's in. The mode was set earlier — when the operator clicked "Take Over," the system recorded "hard" against this escalation and muted Marina. So by the time the operator types a reply, the system already knows whether this is a hard takeover or a soft coaching session.

HARD-MODE PATH (NEW)

If the escalation is in hard mode, the system takes the operator's text exactly as typed — no edits, no rewrites, no Marina pass — and sends it to the customer through the normal WhatsApp send. If the WhatsApp send fails (for example, the Zernio account is missing), the dashboard returns an error to the operator instead of silently swallowing the failure. Once the send succeeds, the system records the message in the WhatsApp conversation trail with the author labeled as "operator" — not "assistant" — so the dashboard renders it as a human message rather than a Marina message. The system also marks the escalation as "replied" so it disappears from the open-escalations queue, and it logs the event with a tag that distinguishes hard-mode replies from the older relay replies. Finally, the operator's text is saved as an approved learning entry — the same way soft-mode replies have been saved since Brief 215 — so Marina can reuse this answer for similar future questions. If the learning save fails for any reason, the customer reply still goes through; the learning save is wrapped so it can never block the customer-facing send. The response handed back to the dashboard now includes two extra fields — the channel name and the author role — so the frontend knows to render the reply bubble as an operator message rather than a Marina message.

SOFT-MODE PATH (UNCHANGED)

If the escalation is in soft mode, or if it's an older escalation from before the mode field existed, the system runs the exact same code it always has. It loads the WhatsApp conversation history, hands the operator's text to Marina along with the booking flags, and asks Marina to "relay" the text — that is, reformulate it into a customer-facing reply. Marina's reformulation is what gets sent to the customer, and it's stored in the trail as an "assistant" message. The relay flags are cleared after the send. None of this behavior changed; it was kept word-for-word so reviewers could confirm the soft path is bit-for-bit identical to before.

GUIDANCE ENDPOINT

A separate dashboard endpoint called "guidance" — the one operators use during soft-mode coaching — already refused to do anything when an escalation was in hard mode. That gate was added in an earlier brief and was already correct, so no change was needed there. The fix in this brief is only on the reply endpoint.

## Edge cases

- If the escalation has no mode set (older rows from before the mode field was wired up — about six of the ten most-recent unboks rows fit this description), the system falls through to the soft/relay path. That preserves the historical behavior for those rows and is the safe default.

- If the WhatsApp send itself fails in hard mode (Zernio account missing, network blip), the dashboard returns a 500 error. The operator sees the failure immediately and can retry. Nothing gets stored in the conversation trail in that case, so there's no ghost message claiming a failed send went through.

- If the learning-save step fails after a successful customer send, the customer reply still goes out and the dashboard returns success. The failure is logged but does not surface to the operator. This is intentional — the learning entry is a nice-to-have, not a blocker for the operator's reply.

- The fix does not retroactively clean up the message in Calvin's test that was wrongly stored as MARINA. That row is still in the trail labeled as Marina. Cleanup would have been a separate data fix; the brief decided it wasn't worth doing for one test message.

- Soft mode still has a latent quirk: if an operator coaching Marina in soft mode types something abusive, Marina will still refuse and the refusal will still go to the customer as if from Marina. That is a different bug, was not what Calvin observed, and is documented as deferred to a future brief if it ever happens for real.

- Hard mode does not run any safety filter on the operator's text. This is by design: hard mode means the operator takes responsibility for what gets sent. If an operator types something abusive in hard mode, it goes to the customer. There is no AI moderation gate.

- The frontend conversation trail must visually distinguish operator messages from Marina messages for this fix to matter end-to-end. Since the email path has been writing operator-labeled messages for about six weeks already, the frontend should already know how to render them. If it doesn't, WhatsApp hard-mode replies will still look like Marina messages in the trail even though the backend stored them correctly.

## What did NOT change

Marina's prompt was not touched. The booking flow was not touched. The way Marina handles inbound customer messages was not touched. The email reply path was not touched — it has had the verbatim/operator-role behavior since Brief 210 and that code is left exactly as it was. The guidance endpoint was not touched — it already handles hard mode correctly. Soft-mode WhatsApp replies still go through Marina's reformulation step and are still stored as assistant messages, exactly as before. Briefs 238 through 245 were all left intact. The dashboard endpoint URL, request body, and error contract are unchanged — only the response on hard-mode WhatsApp replies gets two extra fields (the channel and the author role) for the frontend to render with.
