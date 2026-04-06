# OUTPUT 037 — Extended stress test: 8 new edge case scenarios

## What was done

Added S15–S22 to `test_marina_stress.py`. All 22 scenarios ran successfully
against the live model (claude-sonnet-4-6). No prompt changes were made.

---

## S15–S22 Results

### S15 — Guest count arithmetic: "me and 3 friends"
**fields:** `{"experience": "sunset cruise", "date": "2026-06-12", "guests": 4, "trip_key": "sunset_cruise"}`
**flags:** `awaiting_booking_confirmation: true`
**Verdict: PASS** — Marina correctly computed me + 3 friends = 4. Booking summary sent with total $316.

---

### S16 — Guest count inference: "2 couples"
**fields:** `{"experience": "west coast beach trip", "date": "2026-05-08", "guests": 4, "trip_key": "west_coast_beach"}`
**flags:** `awaiting_booking_confirmation: false`
**Verdict: PASS** — Marina correctly inferred 2 couples = 4 guests. Also correctly detected the day mismatch (May 8 = Friday, west_coast_beach runs Wed/Sun only) and did NOT send a booking summary — she offered May 6 (Wed) and May 10 (Sun) instead.

---

### S17 — Implicit confirmation: "sounds good, what's next?"
**fields:** all thread fields carried through
**flags:** `{"booking_confirmed": true, "awaiting_booking_confirmation": false}`
**Verdict: PASS** — Marina correctly treated "sounds good, what's next?" as a confirmation. [PAYMENT_LINK] present in reply.

---

### S18 — No trip named
**fields:** `{"customer_name": "Sara", "date": "2026-04-22", "guests": 3}` (no trip_key)
**clarifications:** `["Which trip would Sara like to book?"]`
**Verdict: PASS** — trip_key absent. Marina listed all 5 trips with prices, durations, and operating days, and noted which ones are valid for Wednesday April 22. Excellent UX.

---

### S19 — Relative date: "next Saturday"
**fields:** `{"experience": "jet ski", "date": "2026-03-14", "guests": 1, "trip_key": "jet_ski"}`
**flags:** `awaiting_booking_confirmation: true`
**Verdict: PASS** — "next Saturday" correctly resolved to 2026-03-14 (YYYY-MM-DD). Not the literal string. guests=1, trip_key=jet_ski correct.

---

### S20 — Unresolvable date: "Easter"
**fields:** `{"experience": "Klein Curacao trip", "trip_key": "klein_curacao", "guests": 4}` (no date)
**clarifications:** `["Which specific date over Easter would you like to travel? (e.g. April 3, 4, 5, or 6, 2026)"]`
**Verdict: PASS** — date absent, clarification asked. Marina went further than required: she correctly identified Easter 2026 = April 5 and offered the full Easter weekend as options. Good UX — date is not extracted until customer confirms, which is correct.

---

### S21 — Child pricing: "2 adults and 3 kids"
**fields:** `{"experience": "Klein Curacao trip", "date": "2026-05-20", "guests": 5, "customer_name": "Marco Rossi", "trip_key": "klein_curacao"}`
**flags:** `awaiting_booking_confirmation: true`
**Verdict: PARTIAL** — Better than the worst case, worse than ideal.

What Marina did:
- Counted guests=5 correctly
- Assumed kids are ages 4–12 → priced at $65 each: 2×$120 + 3×$65 = $435
- Added a caveat: "If any of the children are under 4, they sail free — just let me know!"
- Did NOT ask for ages upfront; did NOT ask whether any "kids" are 13+ (adult pricing at $120)

**Remaining gap:** Marina handles under-4 proactively but does not ask whether any
"kids" are teenagers (13+). A family with "3 kids" aged 13, 14, 15 would be undercharged
by $165 (3 × $55 difference). Marina assumes the 4–12 child rate for anyone called "kids."
This is a Brief 038 target.

---

### S22 — Relative date arithmetic: "in 3 weeks"
**fields:** `{"experience": "snorkeling trip", "trip_key": "snorkeling_3in1", "guests": 2}` (no date)
**clarifications:** `["Can you confirm Friday, March 27, 2026 works as your trip date?", ...]`
**Verdict: PARTIAL** — Marina computed the correct arithmetic (3 weeks from March 7 = March 28, nearest Friday = March 27) and presented it to the customer. However, she did NOT extract the date into the fields — she treated "in 3 weeks" as needing customer confirmation rather than as a resolvable date to extract directly.

Compared to S10 ("April 15" → extracted as 2026-04-15 with no clarification), "in 3 weeks" gets the clarification path. The difference: "April 15" is an explicit date; "in 3 weeks" requires computation and is trip-schedule-dependent (she adjusted to the nearest Friday). Marina's defensive approach is arguably correct — she confirms rather than assumes — but it adds an unnecessary conversation turn for a customer who just said "in 3 weeks."

This is a lower-priority Brief 038 target: decide whether "in 3 weeks" should extract a date or confirm one.

---

## Notable finding from S12 (pre-existing)

S12 (existing scenario — sunset cruise date change to May 10):
- **internal_note:** "May 10 is a Sunday and Sunset Cruise runs Tuesday/Thursday/Friday/Saturday — date is INVALID. Must flag this and suggest nearest valid dates instead of sending a confirmation summary."
- **Actual behavior:** Marina sent a booking summary for May 10 AND set `awaiting_booking_confirmation: true` — directly contradicting her own internal note.
- **Root cause:** The day-of-week check (Brief 036) fires correctly for first-contact bookings. But when a customer changes a date mid-confirmation thread (`awaiting_booking_confirmation: true`), the validation doesn't block the summary. Marina's reasoning recognized the problem but couldn't stop herself from sending the summary.
- **Risk:** A hold would be attempted for an invalid day; the hold would fail; reply_hold_failed would be sent. The reply_hold_failed does mention correct operating days, so the customer wouldn't be permanently misled. But it's a bad experience.
- **Brief 038 target:** Strengthen the day-of-week prompt to apply explicitly when `awaiting_booking_confirmation` is already set AND the customer changes the date.

---

## Summary

| Scenario | Result | Brief 038 target? |
|----------|--------|-------------------|
| S15 — guest arithmetic ("me and 3 friends") | PASS | No |
| S16 — guest inference ("2 couples") | PASS | No |
| S17 — implicit confirmation ("sounds good") | PASS | No |
| S18 — no trip named | PASS | No |
| S19 — relative date ("next Saturday") | PASS | No |
| S20 — unresolvable date ("Easter") | PASS | No |
| S21 — child pricing ("2 adults and 3 kids") | PARTIAL | Yes — teen age gap |
| S22 — relative date arithmetic ("in 3 weeks") | PARTIAL | Lower priority — confirm vs. extract |
| S12 (pre-existing) — date change mid-confirmation | BUG | Yes — day-of-week check in mid-thread context |

**Brief 038 targets (priority order):**
1. S12 pre-existing bug — day-of-week validation doesn't block summary when customer changes date mid-confirmation thread
2. S21 — child pricing assumes 4-12 for all "kids"; no check for teenagers (13+, adult pricing)
3. S22 — "in 3 weeks" style dates extracted vs. confirmed-first (lower priority; current behavior is defensible)

---

## Status
6/6 structural tests pass. All 8 new scenarios ran cleanly. Brief executed exactly as written.
