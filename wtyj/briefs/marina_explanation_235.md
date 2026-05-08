# EXPLANATION 235 — Fix Brief 227 escalation summary in production

## In one sentence
The Decision-First escalation briefing now actually shows up on the dashboard for every channel — including email — instead of falling back to the generic "Agent needs help" placeholder.

## What's changing and why

When a conversation gets escalated to a human, the dashboard is supposed to show a structured AI-written briefing: why it was escalated, what the customer wants, what the operator needs to decide, and recommended next steps. SR reported the dashboard was instead showing the generic frontend fallback ("Calvin sent a message your Agent is unsure how to answer"). Two separate bugs were causing this in production.

The first bug was a status mismatch. The system stored the briefing on a row tagged "pending," but a different feature (the alert dispatcher from Brief 217) flips that tag to "sent" the instant the alert email goes out — usually before any code ever reads the row back. So the lookup for "the active escalation briefing for this customer" was matching zero rows in production, every time. The second bug was a missing registration. The code that generates the briefing only got hooked up inside the dashboard's web process. The email-checking process is a separate program that never loaded the dashboard module, so when an email escalation was created there, the briefing generator simply wasn't connected and the briefing column was left empty. This change fixes both: the lookup now treats anything that isn't "operator already replied" as an active escalation, and the briefing generator is now wired up in both processes.

## Step by step — what the code does now

STEP: Looking up the active briefing for a customer

When the dashboard asks "what is the current escalation briefing for this customer's conversation," the system now finds rows whose status is either "pending" or "sent" and returns the most recent one. Previously it only looked for "pending" rows, which in production never existed because the alert dispatcher flips them to "sent" almost immediately. Rows where the operator has already replied are still excluded — those are considered done.

STEP: Preventing duplicate escalations on the same conversation

When a new escalation is about to be created, the system checks whether the same customer already has an unresolved escalation open. That check now also recognizes both "pending" and "sent" as unresolved states. Before, it only looked for "pending," which meant duplicate escalation rows could pile up on the same conversation because the dedup query never matched anything in production. Now the rule "one open escalation per conversation" actually fires.

STEP: Generating the briefing — moved into a shared module

The briefing generator (the wrapper that gathers conversation history, calls Claude, and persists the resulting briefing) used to live inside the dashboard's web module. It has been moved into a small shared module dedicated to one job: registering the briefing generator with the central status tracker. Importing this shared module is itself the registration — loading it installs the generator as the system's official briefing producer for that running process. Nothing else lives in this module.

STEP: The dashboard web process registers the generator

The dashboard's web module no longer defines the briefing generator inline. Instead it imports the new shared module at startup, which causes the registration to happen. Behavior is identical to before for WhatsApp, Instagram, Facebook, and Messenger escalations — those go through the web process and get a briefing. About 70 lines of dispatcher code were removed from the dashboard module and replaced with a single import.

STEP: The email poller process registers the generator

The email-checking program (a separate background process that reads incoming email and creates escalations when needed) now also imports the shared registration module at startup. That means when the email poller creates an escalation, the briefing generator is available and produces a real briefing — gathering the email thread's messages, asking Claude to summarize the situation, and saving the result on the escalation row. Before this change, the email poller had no generator hooked up, so every email-channel escalation row had an empty briefing field and the dashboard showed the generic placeholder for those.

STEP: Briefing content itself

The briefing logic is unchanged. For an email escalation, the system still pulls up to 20 messages from that email thread. For Instagram, Facebook, or Messenger, it pulls up to 20 messages from that channel's conversation history. For WhatsApp (and anything else), it pulls up to 20 messages from the WhatsApp history. It also reads the active escalation mode if one is set. All of that gets handed to the Claude-powered summarizer, which returns a structured briefing. If the briefing indicates the customer is trying to schedule something, the system also writes a row to the appointments table — same behavior as before. Failures in the appointment write never block the briefing from being saved.

## Edge cases

- If an old escalation row from before the briefing feature shipped is loaded, its briefing field is empty (the column didn't exist when the row was written). The dashboard will fall back to the generic placeholder for those old rows. This is intentional — those conversations will resolve naturally as operators reply, and regenerating briefings for stale conversations was judged not worth the Claude API cost.
- If a process imports the central status tracker but never imports the new shared registration module, the briefing generator stays unregistered in that process and any escalation created there will save with an empty briefing. This matches the pre-fix behavior. Tests that need the generator must import the shared module explicitly.
- If the briefing generator throws an error mid-call, the escalation row still gets written with an empty briefing field — the failure is swallowed and the escalation alert still goes out. The dashboard then falls back to the generic placeholder for that single row. The operator still gets the alert; they just don't get the AI summary on that one.
- If two messages from the same customer arrive nearly simultaneously and both try to create an escalation, the dedup check now correctly treats both "pending" and "sent" as already-open, so the second one will skip creation. Before, this dedup was effectively disabled in production.
- The "scheduling intent" appointment row write is best-effort. If it fails (database error, malformed proposed time, etc.), the failure is silently swallowed and the briefing is still saved successfully.

## What did NOT change

Marina's prompt, the booking flow, customer data handling, the alert email content, the escalation reply path, and the briefing generator's actual logic (history loading, Claude prompt, structured fields it returns) are all untouched. The Claude summarizer module wasn't modified. The status tracker's other functions weren't modified. The only behavioral changes are: the two SQL filters now accept "sent" in addition to "pending," and the email poller process now registers the briefing generator at startup. Pre-existing escalation rows are not backfilled.
