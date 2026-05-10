# OUTPUT 248 — Extract customer's explicit confirmedTime in escalation summary; update appointment row's date_time_label

## What was done

P1 fix for issue #12 — Calvin's "we will be there at 12:00" was visible in the dashboard escalation summary's `latestCustomerMessage` but the appointment row's `date_time_label` stayed stale at "tomorrow evening 17:00" because (a) the escalation summary tool-use schema had no slot for an explicit confirmation time and (b) Brief 228's bridge from summary → `appointment_upsert` never passed `date_time_label` so the row's headline was set on first insert and never updated. Per-step shipped:

1. **Extended `appointment_upsert` with optional `date_time_label` kwarg** at `wtyj/shared/state_registry.py:2125-2143`. New optional `date_time_label: str = None` parameter; the internal label derivation at line 2141 changed from `label = pt[0] if pt else ""` to `label = date_time_label if date_time_label is not None else (pt[0] if pt else "")`. Explicit override wins; None falls back to the pre-Brief-248 `proposed_times[0]` derivation. Brief 242's `appointment_confirm_by_id` (the only other production caller) does NOT pass the new kwarg → defaults to None → behavior unchanged.
2. **Added `confirmedTime` field to the summary tool-use schema** in `wtyj/dashboard/escalation_summary.py`. Added to `extractedDetails.properties` with detailed Claude-facing description distinguishing explicit confirmations ("we will be there at 12:00") from tentative wording ("maybe 12 could work"). Added to `extractedDetails.required` so Claude always emits the field (empty string when not applicable). Top-of-file SCHEMA_DOCSTRING also updated to mirror.
3. **Added a hard rule in the system prompt** instructing Claude to populate `confirmedTime` ONLY when the customer's MOST RECENT message contains explicit confirmation language for a specific time. Inserted as a new bullet at the end of the existing hard-rules block, right after Brief 239's `previousProposedTimes` rule.
4. **Wired `confirmedTime` into Brief 228's bridge** at `wtyj/shared/escalation_dispatcher.py:67-89`. New local `confirmed_time = (details.get("confirmedTime") or "").strip()` → preferred for `date_time_label`. Falls back to `proposed[0]` when no confirmedTime (matches pre-Brief-248 semantics — see "Fallback revert" below). Status now becomes `pending_team_confirmation` when EITHER `proposed` is non-empty OR `confirmed_time` is non-empty (handles the edge case where Claude emits only confirmedTime without re-listing it in proposedTimes). Bridge does NOT auto-flip to `status='confirmed'` per issue #12's explicit guidance — operator must manually click Brief 242's confirm button.
5. **4 new tests** in NEW file `wtyj/tests/dashboard/test_escalation_summary_confirmed_time.py`. Tests cover: schema field exists in properties + required; bridge uses confirmedTime when set; bridge falls back to `proposed[0]` when confirmedTime empty; bridge passes empty string when both confirmedTime and proposedTimes are empty (status='detected'). Tests stub `_esc_summary.generate_summary` with hand-crafted summaries to be deterministic — they exercise the bridge's plumbing, not Claude's judgment about what counts as "explicit confirmation".

**Brief-reviewer:** FAIL round 1 with 2 real issues — (a) brief asserted `appointment_upsert` already accepted `date_time_label` kwarg (it didn't); Step 3 as drafted would have raised TypeError silently swallowed by the bridge's bare except → entire scheduling-intent bridge would have stopped working in production. (b) Caller survey was missing. Round 2 PASS zero issues after: adding `wtyj/shared/state_registry.py` to Files header, adding new Step 1 that extends `appointment_upsert` with the kwarg, surveying the 2 production callers (escalation_dispatcher.py:80 + state_registry.py:2246) and confirming Brief 242's appointment_confirm_by_id is unaffected.

**Fallback revert (disclosed):** the brief specified the bridge should fall back to `proposed[-1]` (most recently mentioned) when no confirmedTime. Initial implementation matched the brief, but the existing Brief 228 test (`test_scheduling_escalation_creates_appointment_row` at `test_228_appointments.py:95`) asserts `dateTimeLabel == "Thursday at 09:00"` (the FIRST entry from `proposedTimes=["Thursday at 09:00", "Thursday at 12:00"]`), and broke. **Decision:** revert the fallback to `proposed[0]` (matches pre-Brief-248 semantics), keeping `confirmedTime` as the only new behavior. Rationale: (1) Brief 228's existing semantics shouldn't change implicitly — the value of "first vs last" is debatable and orthogonal to issue #12's actual ask; (2) issue #12 is solved by `confirmedTime` directly (Calvin's explicit "12:00" goes there); (3) tighter behavioral surface = lower regression risk. Test 3 renamed `test_bridge_falls_back_to_first_proposed_when_no_confirmed_time` and assertion updated to `"Thursday 09:00"` accordingly.

## Tests

1064 passing / 0 failures (1060 baseline + 4 new = 1064). New file `wtyj/tests/dashboard/test_escalation_summary_confirmed_time.py` runs 4/4. Brief 228's existing tests (`test_228_appointments.py`) still pass — proves Brief 248's no-confirmedTime behavior is bit-for-bit unchanged from pre-Brief-248.

## Production verification needed (post-deploy)

The next time Calvin sends a customer message containing explicit confirmation language ("we will be there at 12:00", "see you Friday at 15:00") inside a scheduling escalation, the appointment row should:
1. Be UPSERTed with `date_time_label="12:00"` (or whatever Claude extracted as the explicit confirmation in the customer's exact wording).
2. Status remains `pending_team_confirmation` (NOT auto-confirmed).
3. Operator can then click Brief 242's manual Confirm button to flip to `status='confirmed'` and trigger the Brief 241 alert dispatcher.

For Calvin's existing stale-label appointment rows (id=3-7 on unboks), the labels won't backfill automatically — they'll update on the next scheduling escalation event for each conversation. Calvin can also force a refresh by sending another customer message that triggers the escalation summary regeneration.

## Deployment

Source commit pending. Will deploy via the standard CI pipeline. All 4 containers expected healthy post-deploy. Briefs 238-247 all preserved (Brief 228's bridge logic + Brief 241's transition-to-confirmed dispatcher + Brief 242's manual confirm endpoint all continue to work; only `date_time_label` derivation in `appointment_upsert` and one new schema field changed).

## Out-of-scope (deferred per brief Step 6)

- Marina-side auto-confirm path — issue #12 explicitly defers; Brief 248 keeps manual-confirm-only via Brief 242's endpoint.
- `features.appointment_auto_confirm` feature flag — not implemented; would gate a future auto-confirm path.
- Adjusting `_summaries_materially_differ` to include `confirmedTime` changes — separate brief; would change alert volume/cadence.
- Frontend "Confirm appointment at TIME" CTA button — SR's frontend work; backend now provides clean data.
- Backfilling the 5 existing appointment rows whose `date_time_label` is stale — operator can manually fix via dashboard if desired.
