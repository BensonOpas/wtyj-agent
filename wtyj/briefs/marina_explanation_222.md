# EXPLANATION 222 — Conversation detail extras: humanTakeoverAt + learningStatus

## In one sentence
When the operator dashboard pulls a single conversation, the response now carries two new pieces of real information — when (if ever) a human took over, and whether that conversation has a saved/approved/suggested learning attached — plus three named-but-empty slots that future work will fill in.

## What's changing and why

The dashboard frontend that SR built has, for a while now, been written to display things like a "Human took over at 19:42" banner, or a small badge that says "this conversation has an approved learning saved." The frontend's contract said those fields were optional — meaning if the backend sent nothing, the UI quietly hid them. That is exactly what was happening: our backend was returning nothing for any of those slots, so none of those affordances ever appeared in the operator's view.

Two of those slots could be filled today because we already store the underlying data. When an operator clicks "Take over" on an escalation, our system has been stamping the moment in time on the conversation since an earlier brief — we just weren't surfacing it. And we have a table of escalation learnings that records, per conversation, whether someone has merely drafted a learning, approved it, or promoted it to a permanent saved learning — also unsurfaced. This change wires both into the conversation detail response, so the dashboard can finally light up those UI elements. Three other slots — what guidance the operator typed, which operator did the action, and when they did it — stay empty for now, because right now every operator logs in with one shared password and the system genuinely cannot tell them apart. Rather than guess, the response sends explicit empty values so the frontend can handle them cleanly and so it's obvious in the API response that those features are pending, not broken.

## Step by step — what the code does now

LOOK UP WHEN A HUMAN TOOK OVER

A new helper takes a conversation identifier and looks in the conversation status records for a stored takeover timestamp. If the conversation was never escalated to a human, or if the human handed control back to the AI (which clears the timestamp), the helper returns nothing. Otherwise it returns the moment the takeover happened, as a date-and-time string the dashboard can format however it wants.

LOOK UP THE CONVERSATION'S LEARNING STATUS

A second new helper takes a conversation identifier and asks the learnings table whether anything has been recorded for that conversation. There can be more than one learning row per conversation, so the helper picks the most "important" one using a fixed order: a saved learning (an operator deliberately promoted it to permanent knowledge) outranks an approved learning (auto-created when the operator answered), which outranks a suggested learning (still a draft). Deleted rows are ignored entirely. If nothing qualifies, the helper returns the word "none." This single word is what the dashboard uses to decide which badge — if any — to show next to the conversation.

EXTEND THE CONVERSATION DETAIL RESPONSE

The piece of code that builds the per-conversation status block now adds five extra entries on top of what it already returned. Two of them call the new helpers above and return real values. The other three — the operator's typed guidance, who that operator was, and when they responded — are returned as deliberately empty values, with a code comment naming them as placeholders waiting for operator-identity work. Both places that already use this status block (the email side and the WhatsApp/DM side of the conversation lookup) automatically inherit the new fields with no extra plumbing, because they merge in whatever the helper produces.

## Edge cases

- If a conversation never had a human takeover, the takeover timestamp comes back empty. That is the expected signal for "no takeover happened" and the dashboard treats it as such.
- If a human took over and then handed control back to the AI, the stored timestamp is cleared, so this response goes back to empty. Once a takeover ends, the dashboard stops showing the "human is here" affordance — which is the correct behavior.
- If a conversation has multiple learning rows in different states, only the highest-ranking one drives the displayed status. A conversation with both a "suggested" draft and an "approved" learning will show as "approved." A conversation where the operator later promotes that approved learning to "saved" will show as "saved." This is intentional — we only want one badge.
- If every learning row for a conversation is deleted, the status comes back as "none," same as if the conversation had never produced any learnings.
- If the conversation identifier is missing or empty, both helpers short-circuit safely: the takeover lookup returns empty, the learning lookup returns "none." No crash, no spurious data.
- The three placeholder fields — guidance text, responder name, response timestamp — will always be empty in this version. The operator dashboard already handles that case because the contract marks them optional. They will only start carrying real values once a future change introduces per-operator identity.
- Because every operator currently shares one password, even after this change we cannot tell which person did what. That limitation is the entire reason three of the five fields are empty, and it is the explicit follow-up planned next.

## What did NOT change

Marina's prompt, the booking flow, the way replies are generated, and how customer messages are routed are untouched. No new database columns or tables were added — both new helpers read from storage that already exists. The dashboard's existing four status fields (whether a conversation is escalated, whether it's resolved, what mode it is in, and whether the AI is muted) keep returning exactly the same values they did before. The operator's "Take over," "Hand back," and "Resolve" actions are unchanged; this brief only exposes the timestamp those actions were already recording.
