# OUTPUT 041 — Semi-escalation prompt fix: prohibit contact-info fallback

## What was done

**Step 2 (executed first):** Added a `CONTACT INFO RULE` block between the
ESCALATION BEHAVIOUR section and the SEMI-ESCALATION header in
`src/marina_agent.py`. The block explicitly restricts `info@bluefinncharters.com`
and the business phone number to complaint/refund/cancellation escalation replies
only, and directs Marina to use `semi_escalation` instead for all other
unanswerable questions.

**Step 1 (executed second):** Replaced the SEMI-ESCALATION body with a stronger
version that:
- Uses "you MUST set semi_escalation to true" (was advisory)
- Lists four explicit trigger categories (equipment specs, dietary/allergy,
  accessibility, yes/no operational questions)
- Explicitly prohibits giving out the contact email or phone as a substitute
- Prohibits partial answers

**Step 3:** Updated file header from `Brief 040` to `Brief 041`.

## Test results

All 4 tests passed on first run.

```
T1 PASS: weight limit question → semi_escalation=True, no contact info in reply
         relay_question: 'What is the maximum weight limit per person for the jet ski excursion?'

T2 PASS: latex allergy question → semi_escalation=True, no contact info in reply
         relay_question: "A guest's daughter has a severe latex allergy. Do the life jackets and
         snorkel gear (masks, pipes) used on your trips contain any latex materials? ..."

T3 PASS: complaint → requires_human=True, contact email present in reply (correct)

T4 PASS: normal FAQ-answerable inquiry → no escalation, direct answer returned
```

## Unexpected

Nothing unexpected. The model responded correctly to all four cases on the first
attempt, including suppressing the contact email in T1 and T2 without prompting
beyond the new CONTACT INFO RULE and SEMI-ESCALATION prohibitions.
