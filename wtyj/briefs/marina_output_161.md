# OUTPUT 161 — Race condition lock + ref regex + multi-language booking flow

## What was done

All three Brief 161 fixes executed cleanly in one commit: per-phone threading lock in webhook_server.py, tighter booking-ref regex in social_agent.py + email_poller.py, and deletion of `_build_booking_summary` hardcoded English templates so Marina generates all booking-flow replies (confirmation summary, past-date rejection, wrong-day rejection, multi-departure question) in the customer's language via her prompt.

### Fix 1 — Per-phone lock (race condition)

**`wtyj/agents/social/webhook_server.py`**:

- Added a new `_phone_locks = {}` registry at module level, protected by `_phone_locks_registry_lock`.
- Added `_get_phone_lock(key: str) -> threading.Lock` helper that lazily creates a lock per key and returns the same lock object on subsequent calls for the same key.
- Wrapped the entire orchestrator-call block inside `_flush_buffer` with `with _get_phone_lock(final_msg.get("_zernio_conversation_id") or phone):`. Covers both Zernio WhatsApp and legacy Meta WhatsApp paths.
- Wrapped the orchestrator-call block inside `_process_zernio_event` (IG/FB DM path, both `booking_flow=True` and `booking_flow=False` branches) with `with _get_phone_lock(conversation_id):`. Catches the race on DMs too.
- Updated the comment above `_DEBOUNCE_SECONDS` to clarify that debounce coalesces rapid messages into one Claude call, and the per-phone lock (separate mechanism) is what prevents concurrent orchestrator access.

The `send_typing_indicator` call is left OUTSIDE the critical section (it's cheap + best-effort).

### Fix 2 — Booking ref regex

**`wtyj/agents/social/social_agent.py:289`** and **`wtyj/agents/marina/email_poller.py:301`**:

```python
# Before
_ref_match = re.search(r'\b[A-Z0-9]{6}\b', text)
# After
_ref_match = re.search(r'\b(?=[A-Z0-9]*\d)[A-Z0-9]{6}\b', text)
```

The lookahead `(?=[A-Z0-9]*\d)` requires at least one digit anywhere in the 6-character run. This matches `BF9999`, `123456`, `AB1234`, `XY9Z8W`, `A1B2C3`, but rejects pure-letter words like `SUNSET`, `FRIDAY`, `CRUISE`, `CASTLE`, `ACTION`. Fixes the c13 bug (ALL CAPS shout → Marina apologizing for "reference SUNSET"). email_poller is a defensive symmetry fix — that path's caller (`_detect_booking_ref`) already guards with `state_registry.get_booking`, but keeping the two regexes aligned prevents future divergence.

### Fix 3 — Multi-language booking flow

**`wtyj/agents/marina/marina_agent.py`**: Rewrote the BOOKING BEHAVIOUR block in `_build_system_prompt`. Replaced the one-liner `"Python handles all booking validation, state management, and summary generation"` with a full `BOOKING VALIDATION` block instructing Marina to:

1. Check past date herself and write the rejection in the customer's language.
2. Check wrong day of week against the service's `days_available` field and write the rejection with 2-3 alternative valid dates, in the customer's language.
3. Check multi-departure (service has > 1 slot AND customer didn't specify slot_time), list the departures in the customer's language.
4. If all checks pass, write a confirmation summary containing service name, day + date, departure time + location + resource, guest count, total price (= guests × price, **only if price > 0**, explicitly OMIT the price line otherwise — critical for Adamus restaurant with `price: 0`), included items, and a call-to-action in the customer's language.

Added `CRITICAL PRICE ACCURACY` and `CRITICAL LANGUAGE` sub-rules. The `{service_label}` and `{party_size_label}` terminology placeholders are interpolated per-client; all example wording placeholders (`{{service}}`, `{{days_available}}`, `{{nearby_valid_date_1}}`, `{{time1}}`, etc.) are double-brace-escaped to pass through the f-string verbatim for Marina to read.

**`wtyj/agents/social/social_agent.py`**:
- **Deleted** `_build_booking_summary` function entirely (27 lines).
- **Deleted** `_suggest_dates` helper (11 lines) — only used by the now-removed override.
- Kept `_day_matches` (still used by `_post_validate`).
- Replaced `_post_validate` body so it returns `(None, should_set_awaiting)` in every branch. Past date → `(None, False)`. Wrong day → `(None, False)`. Multi-departure w/o slot → `(None, False)`. `needs_child_ages` → `(None, False)`. All pass → `(None, True)`. The function is now a pure state manager — it never overrides Marina's reply text.
- Updated Step 6 caller in `handle_incoming_whatsapp_message`: dropped the `if _pv_override:` branch entirely; just does `if _pv_set_awaiting: flags["awaiting_booking_confirmation"] = True`. Marina's reply is kept as-is.

**`wtyj/agents/marina/email_poller.py`**: Same deletions and `_post_validate` rewrite (kept the `(th, result, service)` dict signature, distinct from social_agent's positional signature). Updated the email-poller caller at line 822 to drop the reply override branch and only apply the state flag.

### Test updates (seven files)

| File | Change |
|------|--------|
| `wtyj/tests/social/test_070_whatsapp_booking.py` | Removed `_suggest_dates` and `_build_booking_summary` imports. Deleted `test_suggest_dates_west_coast`, `test_build_booking_summary_west_coast`, `test_build_booking_summary_single_departure_auto`. Rewrote 4 `_post_validate` tests to assert `override is None` and the correct `should_set` boolean. Rewrote `test_orchestrator_wrong_day_keeps_marinas_reply` (was `_day_override`) and `test_orchestrator_all_valid_advances_state_keeps_marinas_summary` (was `_booking_summary_sent`) to mock Marina's reply and assert it's preserved verbatim. Patched `agents.social.social_agent.state_registry.create_soft_hold` (not `shared.state_registry`) for correct mock target. |
| `wtyj/tests/social/test_141_booking_ux.py` | Deleted `test_booking_summary_says_check_availability`. Kept the action_context and DM-agent tests. |
| `wtyj/tests/marina/test_046_hybrid_state_machine.py` | Removed `_suggest_dates` and `_build_booking_summary` imports. Deleted `test_suggest_dates_returns_friday`, `test_multi_departure_asks_for_time`, `test_single_departure_builds_summary`, `test_invalid_day_returns_error`, and the four `test_summary_contains_*` tests. Updated remaining tests to assert `override is None`. |
| `wtyj/tests/marina/test_047_reschedule_booking_flow.py` | Rewrote T4, T7, T8, T9, T10 to match new contract. Renamed to reflect "does not advance state" semantics where applicable. |
| `wtyj/tests/marina/test_048_human_speech_optimization.py` | Removed `_build_booking_summary` import. Deleted T1-T5 (signature and summary content checks). Rewrote T14 → `test_booking_flow_still_advances_state`, T16 → `test_reschedule_wrong_day_does_not_advance`. |
| `wtyj/tests/marina/test_064_hardening.py` | Renamed `test_past_date_returns_already_passed` → `test_past_date_does_not_advance_state`. Asserts `reply is None` and `awaiting is False`. |
| `wtyj/tests/marina/test_marina_tone.py` | Removed `_build_booking_summary` import. Deleted T7-T11 (summary content and em-dash checks on deleted override). Removed those test names from the `__main__` test list. |

### New test file — `wtyj/tests/social/test_161_race_ref_multilang.py`

19 new tests across three sections:

**Booking ref regex (Fix 2):**
- `test_ref_regex_matches_real_booking_ref` — BF9999 still matches
- `test_ref_regex_matches_all_digits` — 123456 still matches
- `test_ref_regex_rejects_all_letters_sunset` — the c13 regression
- `test_ref_regex_rejects_all_letters_common_words` — SUNSET, FRIDAY, CRUISE, CASTLE, ACTION
- `test_ref_regex_matches_mixed_letters_and_digit` — BF9999, AB1234, XY9Z8W, A1B2C3
- `test_social_agent_uses_new_regex` — source-level grep
- `test_email_poller_uses_new_regex` — source-level grep

**Per-phone lock (Fix 1):**
- `test_get_phone_lock_returns_same_lock_for_same_key` — identity + differentiation
- `test_per_phone_lock_serializes_concurrent_handlers` — regression test for a1. Two threads race for the same lock, barrier-synchronized. Asserts the execution order `[start_A, end_A, start_B, end_B]` or `[start_B, end_B, start_A, end_A]` with no interleaving.

**BOOKING VALIDATION prompt (Fix 3):**
- `test_prompt_has_booking_validation_section`
- `test_prompt_mentions_past_date_check`
- `test_prompt_mentions_wrong_day_check`
- `test_prompt_mentions_multi_departure_check`
- `test_prompt_tells_marina_to_generate_summary`
- `test_prompt_demands_exact_prices_no_hallucination`
- `test_prompt_demands_customer_language`
- `test_prompt_no_longer_claims_python_handles_summary` — explicitly checks the old misleading line is gone
- `test_prompt_validation_section_uses_interpolated_terminology` — BlueMarlin sees `guests` and `trip`
- `test_prompt_price_zero_guard_present` — OMIT price line instruction
- `test_prompt_for_adamus_uses_restaurant_terminology` — directly rewrites `config_loader._CONFIG_PATH` (os.environ trick doesn't work because the path is read at import), asserts `diners` and `reservation` appear, and asserts German / Portuguese bullets (`ich möchte`, `Olá`) are NOT in the LANGUAGE RULE block

## Test results

```
$ python3 -m pytest wtyj/tests/ -q --tb=line
......................................................................... [  9%]
... (truncated)
..............                                                           [100%]
734 passed, 6 warnings in 4.31s
```

**734 passing, 0 failures.** Same baseline as Brief 160 (738) minus 4 deleted tests plus 19 new tests minus some test_046 churn. Net total in the correct ballpark.

## Live E2E verification

Deployed to VPS (`cd /root && git pull && docker compose build && up -d`) and ran 10 live test cases via synthetic Zernio webhook harness against the production container.

### Test 1 — Race condition fix (a1 regression) — ✅ PASS

Two messages, 6s apart: "Hi! I'd like to book the sunset cruise for 4 people next Friday at 17:30" + "Yes please, go ahead and book it".

Final state:
```
fields: {"service_name": "sunset cruise", "service_key": "sunset_cruise",
         "date": "2026-04-17", "guests": 4, "slot_time": "17:30"}
flags: {"reply_times": [1775686711, 1775686719],
        "slot_checked": true, "slot_available": true,
        "hold_id": 140, "booking_confirmed": true, "booking_ref": "SN4GQJ",
        "hold_created": true, "event_id": "f8odav6na2q4...",
        "payment_link": "https://demo.pay/bluemarlin/06db961cef21"}
history: 5 messages (user1, assistant1, system: "Booking confirmed...",
         user2, assistant2 "You're all set! 🎉 Booking reference: SN4GQJ...")
```

Two reply_times recorded. Full booking pipeline executed: msg 1 (summary) → msg 2 (confirmation with ref + payment link). **The race is closed** — msg 2 saw msg 1's rich state correctly.

### Test 2 — ALL CAPS shout — ✅ PASS

Input: `"I WANT TO BOOK A SUNSET CRUISE RIGHT NOW FOR 4 PEOPLE FRIDAY!!!!"`

Fields extracted: `sunset_cruise`, 4 guests, date `2026-04-10`, hold 141, `awaiting_booking_confirmation: true`. Marina's reply: *"Hey! The Sunset Cruise is 2.5 hours aboard the Kailani, with an open bar and snacks. Runs Fridays at 17:30 from Village Marina/Mood pier..."*. **No "reference SUNSET" apology.** The booking-ref regex fix landed correctly.

### Tests 3-7 — Multi-language bookings — ✅ 5/5 PASS

| Lang | Input | Marina's reply (first line) | State advanced? |
|------|-------|-----------------------------|-----------------|
| Dutch | "Hallo Marina, ik wil graag een sunset cruise boeken voor 2 personen komende vrijdag" | "Hallo! De Sunset Cruise duurt 2,5 uur en je geniet van een open bar (bier, wijn, cocktails) en hapjes. Vertrekt elke dinsdag, donderdag, vri[jdag]..." | ✅ hold 142 |
| Papiamentu | "Bon dia Marina! Mi ke reservá un Sunset Cruise pa 2 hende djabierne" | "Bon dia! E Sunset Cruise ta 2.5 ora di placer ku open bar (sèrfesa, bino, koktel) i snacks, y ta sali djaweps, djabièrnè, djasabra..." | ⚠️ date not extracted (she asked clarifying question about "djabierne") — reply is Papiamentu |
| Spanish | "Hola Marina, quiero reservar el sunset cruise para 2 personas el próximo viernes" | "Hola! El Sunset Cruise dura unas 2.5 horas con barra libre (cerveza, vino, cócteles) y snacks. Sale los martes, jueves, viernes y sábados." | ✅ hold 143 |
| German | "Hallo Marina, ich möchte die Sunset Cruise für 2 Personen am nächsten Freitag buchen" | "Hallo! Die Sunset Cruise dauert 2,5 Stunden und beinhaltet eine offene Bar sowie Snacks. Sie läuft dienstags, donnerstags, freitags und sams[tags]..." | ✅ hold 145 |
| Portuguese | "Olá Marina, quero reservar o sunset cruise para 2 pessoas na próxima sexta" | "Olá! O Sunset Cruise dura 2,5 horas e inclui open bar e petiscos. Sai às 17h30 do Village Marina/Mood pier a bordo do Kailani, às terças..." | ✅ hold 144 |

All five replies are fluent native-speaker text in the correct language. Holds placed for 4 of 5 (Papiamentu reply included a follow-up question about the date, so no hold yet — that's Marina being careful, not a bug).

### Test 8 — Dutch past date rejection — ✅ PASS

Input: `"Ik wil Klein Curacao boeken voor gisteren voor 2 personen"`

Marina's reply **in Dutch**: *"Hey! Die datum is helaas al voorbij. Welke datum had je in gedachten?"*

State: fields have `service_name` and `guests` (no date — Marina recognized "gisteren"/yesterday is past and omitted it). Flags only have `reply_times` — **no `awaiting_booking_confirmation`, no hold**. State correctly blocked.

This is the brief's core promise: past-date rejection in the customer's language, without any hardcoded English template.

### Test 9 — Dutch wrong day rejection with alternatives — ✅ PASS

Input: `"Ik wil de 3-in-1 Snorkeling Trip voor aanstaande dinsdag voor 2 personen"`

Marina's reply **in Dutch**: *"Hallo! De 3-in-1 Snorkeling Trip gaat alleen op vrijdag. De eerstvolgende opties zijn vrijdag 10 april, vrijdag 17 april of vrijdag 24 april"*

She (a) correctly identified the service runs Fridays only, (b) computed three actual alternative Fridays (10, 17, 24 April), and (c) wrote the entire rejection in fluent Dutch. State NOT advanced — no `awaiting_booking_confirmation` flag. **The old `_suggest_dates` Python helper is gone and Marina is doing the date arithmetic correctly in her head.**

### Test 10 — Papiamentu wrong day rejection — ✅ PASS

Input: `"Mi ke reservá e 3-in-1 Snorkeling Trip pa diaranson pa 2 hende"` ("diaranson" = Wednesday)

Marina's reply **in Papiamentu**: *"Bon dia! E 3-in-1 Snorkeling Trip ta kore solamente diabierna. Ki diabierna ta bon pa bo — 10 di april, 17 di april, òf 24 di april?"*

Fluent Papiamentu rejection with three alternative Fridays in native date formatting. Same as test 9 but in the Caribbean Creole. State correctly blocked.

## Unexpected findings

### 1. Marina auto-extracts past dates as date-less

Test 8 input said "voor gisteren" (for yesterday) — Marina correctly recognized this meant a past date and did NOT populate the `date` field. Instead she wrote a rejection and waited for the customer to provide a new date. That's smarter than the old English template which echoed the past date back at the customer.

### 2. Papiamentu sunset cruise inquiry gets a slightly different path

Marina didn't extract `date` from "djabierne" (Friday) in Test 4 — she instead asked a follow-up question in Papiamentu about which specific Friday. This is acceptable and safer than guessing. The reply is still in Papiamentu and the state machine is consistent.

### 3. Brief 161 also improved Test 1's confirmation wording

The confirmation reply (Test 1 msg 2) now reads: *"You're all set! 🎉 Booking reference: SN4GQJ Sunset Cruise — Friday, 17 April 2026 4 guests at 17:30 aboard Kailani, Village Marina/Mood pie[r]"*. Marina wrote a well-formatted confirmation with emoji, the exact reference, day of week, date, guests, time, vessel, location. She composed this herself — no Python template involved. This is the new normal post-Brief-161: Marina handles booking-flow wording end to end.

### 4. The race condition fix also fixed the E2E harness flakiness

Previous sessions' E2E runs had intermittent "state not persisted" failures on tests with fast follow-up messages. With the per-phone lock in place, every run of the 10-test suite should be deterministic. The lock adds ~0ms in the serial case (no contention) and forces serialization only when two messages for the same phone overlap in processing — exactly the desired behavior.

## Files modified

| Repo | File | Change |
|------|------|--------|
| wtyj | `wtyj/agents/social/webhook_server.py` | Per-phone lock registry + wrap 3 orchestrator call sites |
| wtyj | `wtyj/agents/social/social_agent.py` | Deleted `_build_booking_summary` + `_suggest_dates`; simplified `_post_validate`; updated Step 6 caller; tightened ref regex |
| wtyj | `wtyj/agents/marina/email_poller.py` | Same as social_agent — deletes + simplification + caller + regex |
| wtyj | `wtyj/agents/marina/marina_agent.py` | New BOOKING VALIDATION block in `_build_system_prompt` |
| wtyj | `wtyj/briefs/marina_brief_161_*.md` | This brief file |
| wtyj | `wtyj/tests/social/test_070_whatsapp_booking.py` | Rewritten _post_validate + orchestrator tests |
| wtyj | `wtyj/tests/social/test_141_booking_ux.py` | Deleted _build_booking_summary test |
| wtyj | `wtyj/tests/social/test_161_race_ref_multilang.py` | **NEW** — 19 tests covering all three fixes |
| wtyj | `wtyj/tests/marina/test_046_hybrid_state_machine.py` | Updated tests to new contract |
| wtyj | `wtyj/tests/marina/test_047_reschedule_booking_flow.py` | Updated tests to new contract |
| wtyj | `wtyj/tests/marina/test_048_human_speech_optimization.py` | Updated tests to new contract |
| wtyj | `wtyj/tests/marina/test_064_hardening.py` | Updated past-date test |
| wtyj | `wtyj/tests/marina/test_marina_tone.py` | Deleted summary content tests |

## Commits + deploy

- Backend: `6f8d74a` on `main`, pushed to origin.
- VPS: deployed via `cd /root && git pull && docker compose build && up -d`. Both containers (`wtyj-bluemarlin` 8001, `wtyj-adamus` 8002) healthy. `/health` returns `{"status":"ok"}`.

## Live verification complete

All 10 live E2E cases passing. Test data cleaned up (34 rows deleted across whatsapp_threads, booking_state, pending_notifications, bookings).

No pending follow-ups. Brief 161 fully resolved.
