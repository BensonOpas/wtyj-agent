# OUTPUT 058 — Fix: Booking Ref Missing from Confirmation Reply

## What was done

### Step 1 — marina_agent.py: Prompt updated
Replaced the BOOKING REFERENCE section (lines 164–168). Old instruction told Marina
to include booking_ref "when present in thread_flags" — which is impossible at call
time since booking_ref is generated after the Claude call. New instruction tells Marina
to write the literal `[BOOKING_REF]` placeholder when setting booking_confirmed: true.

### Step 2 — email_poller.py: Placeholder replaced after hold success
Added `reply_text = reply_text.replace("[BOOKING_REF]", booking_ref)` immediately
after the existing `reply_text = reply_text.replace("[PAYMENT_LINK]", pay_link)` at
line 954. Python swaps the placeholder with the real BF-YYYY-XXXXX ref after the
manifest is confirmed.

### Step 3 — File headers updated
- `marina_agent.py`: Brief 055 → Brief 058
- `email_poller.py`: Brief 055 → Brief 058

## Files changed
- `src/marina_agent.py` — prompt BOOKING REFERENCE section
- `src/email_poller.py` — one line added at the [PAYMENT_LINK] replace site

## Test results
```
PASS: test_booking_ref_placeholder_replaced
PASS: test_payment_link_and_booking_ref_both_replaced
PASS: test_reply_without_placeholder_unaffected
PASS: test_prompt_contains_booking_ref_placeholder_instruction
PASS: test_prompt_no_longer_references_thread_flags_for_booking_ref
PASS: test_booking_ref_format_matches_expected_pattern

6/6 tests passed.
```

## Patch applied after output-reviewer
Output-reviewer flagged that `test_prompt_contains_booking_ref_instruction` in
`tests/test_booking_ref.py` (Brief 054 test file) was not updated — it still used a
weak assertion (`"booking_ref" in prompt.lower() or "BF-" in prompt`). Updated to
assert `"[BOOKING_REF]"` is present in the BOOKING REFERENCE section and `"thread_flags"`
is absent from that section. All 12/12 Brief 054 tests still pass.

## Anything unexpected
Root cause was a sequencing bug in Brief 054's design — the prompt instruction assumed
booking_ref was available at Claude call time, but it is generated after. The
[PAYMENT_LINK] pattern was already the correct model; this brief applies it to booking_ref.
