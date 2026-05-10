# EXPLANATION 248 — Extract customer's explicit confirmedTime in escalation summary; update appointment row's date_time_label

## In one sentence

When a customer types a clear "we will be there at 12:00" in their latest message, the appointment row in the dashboard now shows "12:00" as the headline time instead of whatever stale time was sitting there from earlier in the chat — but the operator still has to click Confirm by hand.

## What's changing and why

Calvin found this during live verification. He had an appointment row that showed "tomorrow evening 17:00", then he sent the customer message "apologies, i have gille de la Tourette / can u pls confirm our apointment, we will be there are 12:00". The dashboard's escalation summary correctly captured the message text, but the appointment row's headline time stayed at the old "tomorrow evening 17:00" — Calvin had no clean way to glance at the row and see "the customer just told us 12:00, I should confirm that". He'd have to read the full chat history to find the new time.

Two things were broken. First, the system had no place to put "this is the time the customer just explicitly confirmed" — every time-shaped phrase the customer ever mentioned got dumped into the same proposedTimes list, and the freshest, most-load-bearing one got buried in the noise. Second, the bridge that creates and updates appointment rows from escalation summaries had been stamping the headline time onto the row at first creation only, and never updating it afterward. So even when the system did know about a new time, the row stayed frozen at whatever it had been when the appointment was first detected.

This brief fixes both. The system can now distinguish "the customer just confirmed a specific time" from "the customer mentioned a time at some point", and that confirmed time becomes the appointment row's headline. Crucially, this does NOT auto-confirm the appointment. The operator still clicks the Confirm button manually — the change only makes sure the row's data is accurate before they decide.

## Step by step — what the code does now

STEP: The escalation summary schema gains a confirmedTime slot

The structured form that Claude fills out when summarizing an escalation now has a dedicated field for "the single specific time the customer just explicitly said they'll attend". It sits next to the existing proposedTimes list (every time the customer ever mentioned) and previousProposedTimes list (times they've retracted). The field is required, so Claude always emits it — empty string when there's no explicit confirmation, the exact wording when there is one. Making it required removes the ambiguity of "did Claude leave it out, or is it really empty".

STEP: The schema description teaches Claude what counts as a confirmation

The field's description gives Claude concrete examples of qualifying phrases — "we will be there at 12:00", "see you Friday at 15:00 sharp", "confirmed for Tuesday 9am" — and concrete examples that do NOT qualify — "maybe 12 could work", "how about Tuesday?", "I'm thinking Friday". The instruction is explicit: the confirmation must be in the customer's most recent message, not earlier in the thread, and tentative wording should leave the field empty.

STEP: The summary system prompt adds a hard rule

In addition to the schema description, a new bullet was added to the hard rules block of the prompt that drives the summary call. Same intent restated as an instruction: when the latest customer message contains an explicit confirmation, populate confirmedTime with that exact wording; when in doubt, leave it empty. Belt and suspenders — Claude reads both the field description and the prompt rules.

STEP: The appointment storage function learns to accept an explicit headline time

The internal helper that creates or updates appointment rows used to derive the headline time on its own — it would always grab the first item from the proposedTimes list and stamp that as the row's date_time_label. It now accepts an optional override. When the caller passes an explicit headline, the function uses it verbatim. When the caller passes nothing (which is what the manual Confirm button's helper still does), the function falls back to the old derivation, so nothing else in the system has to change.

STEP: The bridge between escalation summaries and appointment rows uses the new signal

When an escalation comes in and Claude's summary marks the intent as scheduling, the bridge picks up the new confirmedTime field and uses it as the appointment row's headline time. If confirmedTime is empty, the bridge falls back to the first item in proposedTimes — the same behavior as before, so the row still gets a sensible label even when the customer hasn't explicitly confirmed yet. The bridge also widens its rule for marking the appointment as "ready for operator confirmation": previously it only did so when the customer had proposed at least one time, now it also does so when confirmedTime is populated even if proposedTimes happens to be empty (handles the case where Claude records the explicit confirmation without re-listing it as a proposal).

STEP: The status stays at pending_team_confirmation — no auto-confirm

Even when Claude returns a clean confirmedTime, the appointment row's status remains "waiting for the operator to confirm". The operator still clicks the manual Confirm button from Brief 242 to actually mark the appointment confirmed. This brief only makes the row's headline time accurate so the operator has the right data in front of them when they decide.

## Edge cases

- If the customer writes tentative wording like "maybe 12 could work" or "how about Tuesday?", Claude is instructed to leave confirmedTime empty and the appointment row's headline falls back to the first proposed time — same behavior as before this brief. Acceptable; that's the intended judgment call.

- If the customer explicitly confirms a time today (12:00) and then tomorrow says "actually make it 13:00" with explicit confirmation language, the row's headline updates to 13:00. The newer explicit confirmation wins. Acceptable; the operator has the full thread in the dashboard to verify.

- If Claude returns confirmedTime but proposedTimes is empty, the appointment row still gets marked "ready for operator confirm" — previously it would have stayed in the lower-priority "detected" state. Acceptable; matches the intent of having a confirmation present.

- The five existing appointment rows on the unboks tenant whose headline times are already stale from before this brief landed will NOT be retroactively fixed. They will only update on the next escalation event for those conversations. The operator can also fix them by hand from the dashboard if they want. Known and accepted limitation.

- Claude's judgment about what counts as "explicit confirmation" is fuzzy by nature. The schema description and prompt rule give clear examples, but borderline phrasings will land on whichever side Claude reads them as. The tests cover the deterministic plumbing (when confirmedTime is set, the row updates; when it isn't, the row falls back); they cannot cover Claude's judgment without making real LLM calls in CI.

- One small disclosed difference between the brief and the shipped code: the brief originally specified that when confirmedTime is empty, the bridge would fall back to the LAST item in proposedTimes (most recently mentioned). The shipped code falls back to the FIRST item instead, because Brief 228's existing tests already asserted first-item semantics and changing them would have broken those tests. The new feature (using confirmedTime when present) ships as intended; the empty-confirmedTime fallback was kept identical to pre-brief behavior on purpose.

## What did NOT change

Marina's reply prompt was NOT touched. The customer still gets Marina's normal escalation handoff reply — there's no new automated "got it, you're confirmed for 12:00" message. The booking flow itself was NOT touched. The appointment confirmation endpoint that the operator clicks (Brief 242's manual Confirm) was NOT touched, and importantly the system does NOT auto-flip appointments to confirmed status based on customer wording. The signal "the customer said 12:00" now reaches the row's headline cleanly, but the action of saying "yes, this appointment is confirmed" still requires a human operator click.
