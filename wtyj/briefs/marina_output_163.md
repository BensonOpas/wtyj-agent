# OUTPUT 163 — Hold-vs-confirmed wording fix

## What was done

Fixed the premature "Booking confirmed" bug Benson flagged in Image #74 at TWO surface areas:

### 1. Backend: conditional system message text (`social_agent.py`)

At `wtyj/agents/social/social_agent.py` lines 716-717 (the `hold_created` success branch), replaced the unconditional `"Booking confirmed: ..."` system message with a conditional block that branches on `_payment_timing`:

- `payment.timing` in `("upfront", "deposit")` → writes `"Hold placed — awaiting payment: {service}, {date}, {guests} guests (Ref: {booking_ref})"`
- `payment.timing == "none"` (restaurant, no payment required) → keeps the original `"Booking confirmed: ..."` wording

`_payment_timing` was already assigned in the same scope at line 703, so no new variable lookup was needed.

### 2. Backend: Marina's prompt wording (`marina_agent.py`)

Three edits to `wtyj/agents/marina/marina_agent.py`:

- **WhatsApp writing style example (line ~262):** replaced `"All set! Ref [BOOKING_REF], here's your payment link: [PAYMENT_LINK] See you Saturday!"` with `"Got it — I've held your spot. Ref [BOOKING_REF]. Payment link: [PAYMENT_LINK] — I'll confirm as soon as it comes through."`

- **Email writing style example (line ~298):** replaced `"Booking confirmation: You're all set! Your booking reference is [BOOKING_REF]. Here's your payment link: [PAYMENT_LINK]. See you Saturday! 🎉"` with `"Hold placed (payment pending): Got it — I've held your spot. Your booking reference is [BOOKING_REF]. Complete payment at [PAYMENT_LINK] and I'll confirm the booking as soon as it comes through."`

- **New CONFIRMATION WORDING rule** inserted into the BOOKING BEHAVIOUR section right after `STATE MANAGEMENT`. Tells Marina explicitly:
  - For `payment.timing` upfront/deposit: use held-awaiting-payment language; forbidden words list ("Confirmed", "All set", "You're all set", "See you [day]", "Done"); no celebratory emoji until payment clears
  - For `payment.timing` none: confirmed language is fine, one celebratory emoji is fine
  - This rule explicitly overrides the tone/style example guidance above

### 3. Frontend: new "hold placed" state (`Messages.tsx`)

Two edits to `artifacts/dashboard/src/pages/Messages.tsx`:

- **Added `Clock` to the lucide-react imports** at line 10
- **Rewrote the system message rendering block** (lines ~357-388) to support three states instead of two:
  - `/booking confirmed/i` → green `CheckCircle2`, clickable, scrolls to booking info (unchanged)
  - `/hold placed/i` → **amber `Clock`**, clickable, scrolls to booking info (NEW)
  - `/escalat|relay/i` → amber `AlertTriangle`, clickable, navigates to /escalations (unchanged)
  - fallback → amber `AlertTriangle`, non-clickable (unchanged)

### Tests — 7 new in `wtyj/tests/social/test_163_hold_confirmation_wording.py`

**Group A — prompt-level assertions (no mocks):**
1. `test_prompt_contains_confirmation_wording_rule_whatsapp` — WhatsApp prompt has the rule with both timings + "Forbidden words" list
2. `test_prompt_contains_confirmation_wording_rule_email` — Email prompt has the same rule
3. `test_whatsapp_writing_style_no_longer_says_all_set` — WhatsApp GOOD REPLIES block purged of "All set!"
4. `test_email_writing_style_no_longer_says_youre_all_set` — Email writing style block purged of "You're all set" (scoped to the style block only, since the CONFIRMATION WORDING rule legitimately lists "You're all set" as a forbidden phrase)

**Group B — integration (mocked orchestrator):**
5. `test_system_message_says_hold_placed_for_upfront_timing` — full `handle_incoming_whatsapp_message` path with `payment.timing="upfront"` → last system message starts with "Hold placed" and does NOT say "Booking confirmed"
6. `test_system_message_says_booking_confirmed_for_none_timing` — same path with `payment.timing="none"` → last system message says "Booking confirmed" and does NOT say "Hold placed"

**Group C — source-level guard:**
7. `test_source_system_message_branches_on_payment_timing` — reads social_agent.py source, asserts both `"Hold placed — awaiting payment"` and `"Booking confirmed: "` strings exist AND the `_payment_timing in ("upfront", "deposit")` branch keyword is within 3KB of `flags["hold_created"] = True`

## Test results

```
$ python3 -m pytest wtyj/tests/social/test_163_hold_confirmation_wording.py -v
============================= 7 passed in 0.29s ==============================

$ python3 -m pytest wtyj/tests/ -q --tb=line
753 passed, 6 warnings in 4.07s
```

**753 passing / 0 failures.** Baseline was 746 from Brief 162. Math: 746 + 7 = 753. ✓

## Frontend typecheck

```
$ cd /Users/benson/Projects/wetakeyourjob-dashboard/artifacts/dashboard && pnpm typecheck
12 pre-existing errors, 0 new errors.
```

Pre-existing errors are in `ContentPipeline.backup.tsx` (missing `scheduled` property, from Brief 155 era) and `Messages.tsx:97-111` (missing `channel` property on Conversation type, from Brief 156 era when LinkedIn was removed). None of these touch the code Brief 163 edited (lines 10 and 356-388).

## Unexpected findings during execution

### 1. First test run had 3 failures, all fixable in one patch

- **Test #4 failed because my own CONFIRMATION WORDING rule lists "You're all set" as a forbidden phrase.** The rule literally says `Forbidden words in this state: "Confirmed", "All set", "You're all set", ...`. Whole-prompt search for `"You're all set"` matched the rule itself, not the writing style block. Fix: scoped the test to read only between `GOOD REPLY EXAMPLES` and `AVOID:` / `BOOKING BEHAVIOUR`. This is a real lesson for any test that does whole-prompt substring matching — forbidden-word rules necessarily contain the forbidden words, so you can't grep the whole prompt for them.
- **Tests #5 and #6 failed because `_cleanup_phone` used the wrong table name.** I wrote `whatsapp_messages` but the actual state_registry table is `whatsapp_threads`. Copied the cleanup pattern from `test_070_whatsapp_booking.py:55-61` verbatim (deletes from `whatsapp_threads`, `whatsapp_booking_state`, `service_bookings`).

Both fixes landed in a single edit cycle. After the patch all 7 tests passed.

### 2. Brief-reviewer caught pre-existing test_070 would not break

The brief had hand-wavy "check at execution time; update only if needed" language for `test_070_whatsapp_booking.py::test_orchestrator_booking_confirmed`. Reviewer verified by reading the test that it asserts on `reply`, `booking_ref`, `payment_link`, and flag state — but NOT on the system message text. So Brief 163's wording change was safe, and no update was actually needed. The hand-wave worked out but the brief should have been more specific.

### 3. Minor prompt-level tension with pre-existing emoji guidance

Lines 275 and 310 in marina_agent.py already said `"Emojis: only in booking confirmations. Otherwise skip them."`. The new CONFIRMATION WORDING rule says `"Do NOT include a celebratory emoji"` for the upfront/deposit state. These are not strictly contradictory (the new rule is more specific), and Marina's prompt interpretation will favor the more specific rule, but a future brief could harmonize the wording by updating lines 275/310 to say `"Emojis: only in true booking confirmations where payment.timing == 'none' — see CONFIRMATION WORDING rule below."` Non-blocking for Brief 163.

### 4. Historical "Booking confirmed" system messages are not backfilled

Any WhatsApp thread that had a "Booking confirmed: X" system message before Brief 163 deployed continues to render with the green `CheckCircle2` tag. That's correct historical behavior — they represent past operator-visible state, not a current claim. Marina's new replies will write "Hold placed — awaiting payment" going forward for BlueMarlin (upfront timing). Adamus (timing=none) continues to write "Booking confirmed" unchanged.

## Deployment

- Backend pushed: commit `<TBD — to be added after commit>`
- Dashboard pushed: commit `<TBD — to be added after commit>`
- VPS: `docker compose down && build && up -d` on `wtyj-bluemarlin`; Adamus container `docker compose down && up -d` (shares the same rebuilt image)

## Files modified

| File | Change |
|------|--------|
| `wtyj/agents/social/social_agent.py` | Conditional system message text based on `_payment_timing` |
| `wtyj/agents/marina/marina_agent.py` | WhatsApp + email writing style examples + new CONFIRMATION WORDING rule |
| `wtyj/tests/social/test_163_hold_confirmation_wording.py` | **NEW** — 7 tests |
| `wtyj/briefs/marina_brief_163_hold_confirmation_wording.md` | **NEW** — this brief |
| `artifacts/dashboard/src/pages/Messages.tsx` (dashboard repo) | New `isHoldPlaced` state with amber Clock tag |

## Brief 163 is complete.
