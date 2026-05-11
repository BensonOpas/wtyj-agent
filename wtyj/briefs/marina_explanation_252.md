# EXPLANATION 252 — Tighten escalation summary to extract concrete entities + ban meta-language phrases

## In one sentence
The dashboard's escalation summary box now writes out the actual time, date, service, or reason the customer named in their latest message — instead of vague placeholders like "Customer updated their request" — so the operator can decide without having to open the conversation and read the message themselves.

## What's changing and why

Two weeks ago Brief 250 fixed a bug where the summary engine was reading the wrong slice of the conversation and missing the newest customer message entirely. That fix worked — the newest message is now visible to the summary engine. But Calvin's verification on the dashboard caught a second, related problem: even when the engine could see the latest message, it was describing the change at a meta level instead of repeating what was actually said.

For example, when a customer wrote "Actually, can we make it 10:30 instead? my dog is much better," the dashboard's summary boxes were filling in things like "Calvin updated their request" and "An updated reply based on their latest message." Operationally useless — the operator still had to read the conversation to find out what the customer actually wanted. Brief 252 rewrites the summary engine's instructions so the same input now produces "Move or confirm the appointment at 10:30" in the customer-wants box and "Confirm whether 10:30 is available, or offer the closest alternative" in the operator-needs-to-decide box. The 10:30 — the concrete entity — appears verbatim in the summary. The whole point of the summary box is to spare the operator from reading the conversation; before this change, it was secretly forcing them to read it anyway.

There is no schema change, no new database fields, no new dashboard tabs. The summary engine still produces the same nine fields it always did. The only difference is the wording rules it follows when filling them in.

## Step by step — what the code does now

THE INSTRUCTION SET FOR THE SUMMARY ENGINE was previously assembled inline, mixed in with the rest of the function that calls Claude. It has been pulled out into its own dedicated piece called "build the system prompt." Nothing about what the summary engine is told to do has changed for the older rules — the rules from Brief 248 (about confirmed-attendance phrasing) and Brief 250 (about anchoring on the latest message) still appear, word-for-word, in the same order. The reason for moving the instructions into their own piece is purely so that automated tests can read the instructions back and verify they still contain what they should.

A NEW HARD RULE has been added to the bottom of the instruction list, labeled "Brief 252: EXTRACT THE CONCRETE ENTITY." It tells the summary engine that whenever the customer's latest message contains a specific time, date, place, service, or reason, those exact words must appear in the customer-wants, operator-needs-to-decide, reason, and recommended-options fields. The rule then spells out, in the same paragraph, two kinds of examples.

THE "DO" EXAMPLES use Calvin's exact expected output as a model: customer-wants reads "Move or confirm the appointment at 10:30," operator-needs-to-decide reads "Confirm whether 10:30 is available, or offer the closest alternative," and the reason field reads "Customer asked to move the appointment to 10:30 and says their dog is much better." The summary engine is shown what good output looks like, not just told to produce it.

THE "DO NOT" EXAMPLES quote the actual bad output Calvin saw on the dashboard, so the engine knows exactly which phrases are forbidden. Five meta-phrases are explicitly banned: "updated request," "their latest message," "based on their reply," "new request," and any phrasing that describes a change without naming what the change was about.

THE ENFORCEMENT TRIPLET at the end of the rule reads, in plain instruction form: if the customer named a time, use the time; if they named a service, use the service; if they named a reason, include the reason. The rule closes with an explicit statement of purpose — the summary box exists so the operator does NOT have to read the message themselves, and if the output forces them to read it, the engine has failed.

THREE NEW AUTOMATED CHECKS have been added to the existing test file for the summary engine. The first check confirms the new entity-extraction rule and all five banned meta-phrases are present in the instruction set. The second check confirms the positive examples (Calvin's expected wording, including "Move or confirm the appointment at 10:30" and the use-the-time / use-the-service / include-the-reason triplet) are also present. The third check is a regression guard: it confirms that the older Brief 248 and Brief 250 rules were not accidentally dropped or altered when the instructions were moved out into their own piece.

The total automated check count is now 1081, all passing.

## Edge cases

- If the customer's latest message contains no concrete entity at all (just "ok thanks" or "hmm not sure"), the new rule has nothing to extract. The summary fields fall back to the older rules — the engine summarizes whatever the conversation is actually about. Acceptable.

- If the customer names multiple competing entities in one message ("can we do 10 or maybe 11 or actually 12?"), the engine is still told to extract every proposed time into the proposed-times field, and the customer-wants field will reflect the latest framing. The new rule does not specifically address ambiguous multi-time messages — that case is handled by the existing "extract every proposed time" rule.

- If the customer's wording is unusual or hard to read (typos, abbreviations, non-English), the engine is still told elsewhere in the instructions to use the customer's exact wording for times when possible and never to invent wording that isn't in the transcript. The new rule does not override those guards — it adds to them.

- The banned meta-phrases are an exact-string list. If the engine generates a near-miss like "an updated booking" or "their newest reply," that specific phrase is not literally banned. The hope is that the broader instruction ("any phrase that describes the change without naming what was actually requested") and the strong DO examples push the engine away from all meta-language, not just the five listed phrases. If new meta-phrases show up in production, a follow-up brief adds them to the ban list.

- Existing escalation summaries that were produced before this change still show the old meta-language wording. They are not retroactively rewritten. The next time that conversation triggers a fresh escalation, the new wording takes over. Acceptable, per the brief.

- The brief documents that server-side Python checking of the engine's output (e.g., a guard that rejects the output if it contains a banned phrase) was deliberately not added. The trade-off: trust the instructions to do the work; if non-compliance is observed, a follow-up brief adds the check.

- Calvin still needs to verify in production by sending another customer message that names a specific time, service, or reason and confirming the dashboard summary repeats that entity verbatim. The automated checks confirm the instructions were updated; only a real production message confirms the engine actually obeys them.

## What did NOT change

The summary engine's nine output fields (intent, topic, proposed times, previous proposed times, confirmed time, customer-wants, operator-needs-to-decide, reason, recommended options, latest customer message) are unchanged in shape and meaning. No schema migration. No dashboard frontend change. The function the rest of the system calls to generate a summary still takes the same inputs and returns the same shape of output. The Marina prompt, the booking flow, customer data handling, and every other tenant's behavior are untouched — this brief only edits the operator-facing summary instructions used when an escalation lands in the dashboard.
