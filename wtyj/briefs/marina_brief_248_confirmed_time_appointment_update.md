# BRIEF 248 — Extract customer's explicit confirmedTime in escalation summary; update appointment row's date_time_label

**Status:** Draft (round 2) | **Files:** wtyj/shared/state_registry.py, wtyj/dashboard/escalation_summary.py, wtyj/shared/escalation_dispatcher.py, wtyj/tests/dashboard/test_escalation_summary_confirmed_time.py | **Depends on:** Brief 247 (`d3e93d4`) | **Blocks:** none

## Context

Issue #12 (Calvin live verification, P1) — during Nr 2 verification, Calvin sent: `"apologies, i have gille de la Tourette / can u pls confirm our apointment, we will be there are 12:00"`. Dashboard escalation summary correctly showed scheduling intent + the 12:00 time in the customer's latest message text. But the appointment row was NOT updated to reflect "12:00" — it stayed at a stale `date_time_label` from earlier in the conversation. Calvin expected the appointment to become or update with the explicitly-confirmed time, ready for the operator to click Brief 242's manual Confirm button.

**Verified production state on unboks (2026-05-10 audit):**
- 5 appointment rows EXIST in `appointments` table for unboks (id=3-7), all with `status='pending_team_confirmation'`. So Brief 228's `escalation_summary → appointment_upsert` bridge IS firing for the right cases (`extractedDetails.intent == 'scheduling'`).
- Calvin's WhatsApp conversation `69efec187aca03948969dc95` has appointment id=4 with `title='Intake call appointment'`, `date_time_label='tomorrow evening 17:00'`, `updated_at='2026-05-10T10:51:14'`.
- The thread chronology shows Calvin's actual most recent customer message at 10:51:02 was `"apologies, i have gille de la Tourette / can u pls confirm our apointment, we will be there are 12:00"`.
- The escalation summary at 10:51:06 (id=25) had `extractedDetails.proposedTimes=['tomorrow evening 17:00', 'monday morning at 11:00']` — neither of which is `12:00`. Claude extracted older times from history, missed the explicit confirmation in the latest message.

**Root cause:** Brief 228's bridge in `wtyj/shared/escalation_dispatcher.py:67-89` calls `appointment_upsert(..., proposed_times=details.get("proposedTimes"), ...)` but **does NOT pass `date_time_label`**. The appointment row's `date_time_label` is set on first insert (from the legacy initial value or default) and never updated by the bridge — only `proposed_times_json` and `status` get UPSERTed. So when the customer explicitly confirms a specific time later, the row's headline time field stays stale.

**Plus a related Claude-side gap:** the summary tool-use schema (`wtyj/dashboard/escalation_summary.py:86-108`) has `proposedTimes` (every time the customer mentioned) and `previousProposedTimes` (times explicitly retracted). It does NOT have a separate `confirmedTime` field for "the single specific time the customer JUST EXPLICITLY confirmed they will attend in their most recent message". Claude has no schema slot to record an explicit confirmation, so this signal gets lost into the noise of `proposedTimes`.

**Verified read-only:**
- `wtyj/dashboard/escalation_summary.py:86-115` — current `extractedDetails` schema has `intent`, `proposedTimes`, `previousProposedTimes`, `topic`. No confirmedTime.
- `wtyj/dashboard/escalation_summary.py:163-180` — system prompt has hard rules but no instruction to extract an explicit confirmation time as a separate field.
- `wtyj/shared/escalation_dispatcher.py:64-89` — Brief 228's bridge. Calls `appointment_upsert` with `proposed_times` + `status` only. No `date_time_label` parameter.
- `wtyj/shared/state_registry.py:2125-2127` — actual signature is `appointment_upsert(conversation_id, channel, customer_name, title, proposed_times, location='', status='detected') -> int`. **It does NOT currently accept `date_time_label` as a kwarg.** Internally derives `label = proposed_times[0] if proposed_times else ""` (line 2141) and writes that string to the `date_time_label` column. So today the column is always set from the FIRST proposed time, never the explicit confirmation. Brief 248's Step 1 extends the function with a new optional `date_time_label: str = None` kwarg that overrides the derivation when non-None.
- **Production callers of `appointment_upsert`:** verified via `grep -rn "appointment_upsert(" wtyj/ --include='*.py' | grep -v "def appointment_upsert\|test_"`. Only 2 callers: (a) `wtyj/shared/escalation_dispatcher.py:80` — Brief 228 bridge (the one this brief modifies); (b) `wtyj/shared/state_registry.py:2246` — `appointment_confirm_by_id` helper (Brief 242 confirm endpoint). Caller (b) does NOT pass the new kwarg → defaults to None → derivation preserved → behavior unchanged. Confirmed by reading `state_registry.py:2240-2254`.
- `appointments` table schema verified live: `date_time_label TEXT NOT NULL DEFAULT ''`. Updates work.

## Why This Approach

**Considered:** Have the bridge pick the FIRST item from `proposedTimes` as `date_time_label` whenever the appointment row is upserted. **Rejected:** `proposedTimes` is "every time the customer mentioned" — the first item is rarely the most recent confirmation. Would produce wrong labels (e.g., "Thursday 09:00" when the customer ultimately confirmed "Wednesday 15:00"). Worse than no update.

**Considered:** Add a Python heuristic that grabs time-like substrings from `latestCustomerMessage` (e.g., regex for `\d{1,2}:\d{2}`). **Rejected:** Rule 5 violation (Python language classifier). Also fragile across language locales (`14h00`, `2pm`, `klockan 12`).

**Considered:** Add a separate Claude moderation call inside the bridge that asks "did the customer just confirm a specific time?" given the latest message. **Rejected:** second Claude call per escalation = doubles latency + cost; the existing summary call already has the full conversation context and can do this extraction in one pass with one new schema field.

**Considered:** Make the bridge auto-flip the appointment to `status='confirmed'` when `confirmedTime` is populated. **Rejected per issue #12 explicit guidance:** *"This issue is NOT asking to enable full Marina auto-confirm. Manual confirm remains the safe final action unless `features.appointment_auto_confirm` is later enabled."* The bridge keeps `status='pending_team_confirmation'` and lets the operator click Brief 242's confirm button.

**Considered:** Detect the confirmation pattern in `marina_agent` and route to a dedicated "appointment confirm" path instead of escalation. **Rejected:** much larger scope; current architecture treats explicit confirmations as "still need operator review because it's a new customer-stated time". Would require Marina prompt + tool-schema changes + a new `confirm_appointment` tool action. Defer to a future brief if/when full auto-confirm is in scope.

**Tradeoff — Claude's "explicit confirmation" judgment is fuzzy:** the schema field tells Claude to extract `confirmedTime` ONLY for explicit confirmation language ("we will be there at 12:00", "see you at 15:00"), not for tentative wording ("maybe 12 could work", "how about Tuesday?"). The judgment is Claude's per Rule 2; we trust the prompt + Claude's language understanding. Tests cannot fully cover this judgment without a real LLM call (which is not run in CI per existing test boundary policy). Document the judgment expectation in the schema description + tests cover the bridge's deterministic plumbing (when `confirmedTime` IS populated, the appointment row IS updated; when NOT populated, no update).

**Tradeoff — `confirmedTime` overrides prior `date_time_label`:** if a customer explicitly confirms 12:00 today, then tomorrow says "actually 13:00 instead", the bridge will update the row to "13:00". That's correct behavior — the customer's most recent explicit confirmation wins. The operator has full conversation context in the dashboard if they need to verify.

## Instructions

### Step 1 — Extend `appointment_upsert` with optional `date_time_label` kwarg

In `wtyj/shared/state_registry.py:2125-2127`, the current signature is:

```python
def appointment_upsert(conversation_id: str, channel: str, customer_name: str,
                       title: str, proposed_times: list, location: str = "",
                       status: str = "detected") -> int:
    """Brief 228: upsert an appointment row keyed on conversation_id.
    proposed_times is a list of strings; we store JSON and pick the first
    one for date_time_label (frontend uses that as the headline).
    ...
```

Replace with:

```python
def appointment_upsert(conversation_id: str, channel: str, customer_name: str,
                       title: str, proposed_times: list, location: str = "",
                       status: str = "detected",
                       date_time_label: str = None) -> int:
    """Brief 228: upsert an appointment row keyed on conversation_id.
    proposed_times is a list of strings; we store JSON.

    Brief 248: date_time_label is the headline time string the frontend
    displays. When supplied (e.g., the customer's explicit confirmation
    extracted by the Brief 248 confirmedTime schema field), use it
    verbatim. When None (legacy callers like Brief 242's
    appointment_confirm_by_id), fall back to the first proposed_time —
    preserves pre-Brief-248 behavior so existing callers don't change.
    ...
```

In the function body at line 2141, replace:

```python
    pt = proposed_times or []
    label = pt[0] if pt else ""
```

with:

```python
    pt = proposed_times or []
    # Brief 248: explicit override wins; otherwise fall back to first
    # proposed time (pre-Brief-248 behavior preserved for callers that
    # don't supply date_time_label, e.g. appointment_confirm_by_id).
    label = date_time_label if date_time_label is not None else (pt[0] if pt else "")
```

The rest of the function body (lines 2142-2198 — INSERT/UPDATE SQL, transition-to-confirmed detection, alert dispatcher fire) is unchanged. The Brief 241 transition-to-confirmed dispatcher still receives `date_time_label=label` in its `appointment_dict` payload (line 2188), which now reflects the explicit confirmation when supplied.

**Caller survey (verified):**
- `wtyj/shared/escalation_dispatcher.py:80` — Brief 228 bridge → Step 4 of THIS brief updates this caller to pass the new kwarg.
- `wtyj/shared/state_registry.py:2246` — `appointment_confirm_by_id` (Brief 242 confirm endpoint helper) → does NOT pass the new kwarg → defaults to None → falls back to `pt[0]` derivation → behavior unchanged. Verified by reading the call site.

### Step 2 — Add `confirmedTime` field to the summary tool-use schema

In `wtyj/dashboard/escalation_summary.py` at lines 96-109 (after `previousProposedTimes`, before `topic`), insert a new schema property:

```python
                    "confirmedTime": {
                        "type": "string",
                        "description": (
                            "The single specific time the customer EXPLICITLY "
                            "confirmed they will attend, in their exact "
                            "wording. Populate ONLY when the customer's most "
                            "recent message contains explicit confirmation "
                            "language for a specific time. Examples that "
                            "QUALIFY: 'we will be there at 12:00' → '12:00'; "
                            "'see you Friday at 15:00 sharp' → 'Friday at "
                            "15:00 sharp'; 'confirmed for Tuesday 9am' → "
                            "'Tuesday 9am'. Examples that do NOT qualify "
                            "(leave empty string): 'maybe 12 could work', "
                            "'how about Tuesday?', 'I'm thinking Friday', "
                            "any tentative or hypothetical wording. The "
                            "confirmation must be in the LATEST customer "
                            "message, not earlier in the thread. Empty "
                            "string when no explicit confirmation in latest "
                            "message."
                        ),
                    },
```

Update the `extractedDetails.required` array at line 115 from `["intent", "proposedTimes", "topic"]` to `["intent", "proposedTimes", "topic", "confirmedTime"]` so Claude must always emit the field (empty string when not applicable). This makes the field's absence-vs-empty unambiguous downstream.

Also update the top-of-file SCHEMA_DOCSTRING at lines 9-25 to mention the new field. Currently shows:
```python
    "extractedDetails": {
        "intent": str,             # scheduling | complaint | refund | ...
        "proposedTimes": [str],    # every time slot the customer mentioned
```
Add (in the same shape) right after `proposedTimes`:
```python
        "confirmedTime": str,      # the single time the customer EXPLICITLY confirmed in their latest message; empty when no explicit confirmation
```

### Step 3 — Add a hard rule in the system prompt for the new field

In `wtyj/dashboard/escalation_summary.py` at lines 163-180 (the system_prompt's hard rules block), add a new bullet at the END of the hard rules list (before the user_prompt construction):

```python
            "- When the customer's MOST RECENT message contains an explicit "
            "confirmation that they will attend at a specific time (e.g., "
            "\"we will be there at 12:00\", \"see you Friday at 15:00\"), "
            "populate confirmedTime with that exact time wording. Tentative "
            "language (\"maybe 12\", \"how about Tuesday?\") does NOT qualify. "
            "When in doubt, leave confirmedTime empty."
```

Insert this as a new line in the `system_prompt = (...)` string concatenation, right after the existing `previousProposedTimes` rule that ends with `"Do not put the same time in both lists."`.

### Step 4 — Wire `confirmedTime` into the appointment_upsert bridge

In `wtyj/shared/escalation_dispatcher.py` at lines 67-89 (the Brief 228 bridge), the current code reads:

```python
    if summary_dict:
        try:
            details = (summary_dict.get("extractedDetails") or {})
            if details.get("intent") == "scheduling":
                proposed = details.get("proposedTimes") or []
                topic = details.get("topic") or "Meeting"
                if channel == "email":
                    thread_key = state_registry._find_email_thread_key_for(customer_id)
                    conv_id = f"email::{thread_key}" if thread_key else customer_id
                else:
                    conv_id = customer_id
                status = ("pending_team_confirmation"
                          if proposed else "detected")
                state_registry.appointment_upsert(
                    conversation_id=conv_id,
                    channel=channel,
                    customer_name=customer_name or "",
                    title=topic,
                    proposed_times=proposed,
                    status=status,
                )
        except Exception:
            pass
```

Replace with:

```python
    if summary_dict:
        try:
            details = (summary_dict.get("extractedDetails") or {})
            if details.get("intent") == "scheduling":
                proposed = details.get("proposedTimes") or []
                topic = details.get("topic") or "Meeting"
                # Brief 248: prefer the customer's explicit confirmation time
                # for the appointment row's headline date_time_label. Falls
                # back to the most recent proposedTime when no explicit
                # confirmation, so the row still has a sensible label.
                confirmed_time = (details.get("confirmedTime") or "").strip()
                date_time_label = (
                    confirmed_time if confirmed_time
                    else (proposed[-1] if proposed else "")
                )
                if channel == "email":
                    thread_key = state_registry._find_email_thread_key_for(customer_id)
                    conv_id = f"email::{thread_key}" if thread_key else customer_id
                else:
                    conv_id = customer_id
                # Brief 248: when confirmedTime is populated, ensure status
                # reflects "ready for operator confirm" even if proposedTimes
                # happens to be empty (Claude may emit only confirmedTime
                # for "we'll be there at 12:00" without re-listing it in
                # proposedTimes).
                status = ("pending_team_confirmation"
                          if (proposed or confirmed_time)
                          else "detected")
                state_registry.appointment_upsert(
                    conversation_id=conv_id,
                    channel=channel,
                    customer_name=customer_name or "",
                    title=topic,
                    proposed_times=proposed,
                    status=status,
                    date_time_label=date_time_label,
                )
        except Exception:
            pass
```

Three behavioral changes:
1. New local `confirmed_time` extracts from `details.get("confirmedTime")`.
2. New local `date_time_label` prefers `confirmed_time`, falls back to the **last** entry in `proposed_times` (most recently mentioned, not first), empty string if neither.
3. `status` now becomes `pending_team_confirmation` when EITHER `proposed` is non-empty OR `confirmed_time` is non-empty (handles the edge case where Claude emits only confirmedTime without re-listing it in proposedTimes).
4. New kwarg `date_time_label=date_time_label` passed to `appointment_upsert`.

### Step 5 — Add 4 new tests

Create `wtyj/tests/dashboard/test_escalation_summary_confirmed_time.py` (NEW file — there's no existing per-source-module test file for `escalation_summary.py` or `escalation_dispatcher.py` covering this concern; existing dispatcher tests in `test_217_alert_delivery.py` cover the alert path, not the appointment bridge).

```python
"""Brief 248: tests for the confirmedTime extraction in escalation summary
+ bridge to appointment_upsert's date_time_label parameter."""
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")


def test_summary_tool_schema_includes_confirmed_time_field():
    """Brief 248: the SUMMARY_TOOL schema MUST include confirmedTime in
    extractedDetails.properties so Claude has a slot to record explicit
    customer confirmations. Required so absence-vs-empty is unambiguous."""
    from dashboard.escalation_summary import SUMMARY_TOOL
    schema = SUMMARY_TOOL["input_schema"]["properties"]
    details_props = schema["extractedDetails"]["properties"]
    assert "confirmedTime" in details_props, (
        f"extractedDetails.properties must include confirmedTime; "
        f"has {sorted(details_props.keys())}")
    assert "confirmedTime" in schema["extractedDetails"]["required"], (
        "confirmedTime must be in extractedDetails.required so Claude "
        "always emits it (empty string when not applicable)")


def test_bridge_uses_confirmed_time_as_date_time_label_when_set(monkeypatch):
    """Brief 248 + 228: when the summary's extractedDetails.confirmedTime
    is populated, the bridge passes it as appointment_upsert's
    date_time_label kwarg (overriding the proposed_times fallback)."""
    from shared import escalation_dispatcher
    from shared import state_registry

    captured = {}
    def fake_upsert(**kw):
        captured.update(kw)
        return 999
    monkeypatch.setattr(state_registry, "appointment_upsert", fake_upsert)
    # Stub the Claude call so the dispatcher uses the supplied summary.
    fake_summary = {
        "extractedDetails": {
            "intent": "scheduling",
            "proposedTimes": ["Thursday 09:00", "Friday 12:00"],
            "confirmedTime": "12:00",
            "topic": "Discovery call",
        },
    }
    monkeypatch.setattr(
        escalation_dispatcher._esc_summary, "generate_summary",
        lambda **kw: fake_summary)
    monkeypatch.setattr(state_registry, "wa_get_full_history", lambda *a, **k: [])

    escalation_dispatcher._generate_escalation_summary(
        escalation_id=1, channel="whatsapp",
        customer_id="248_cust_phone", customer_name="Calvin Test")

    assert captured.get("date_time_label") == "12:00", (
        f"date_time_label must equal confirmedTime when set; "
        f"captured kwargs={captured}")
    assert captured.get("status") == "pending_team_confirmation"
    # proposed_times still passed through for separate dashboard display
    assert captured.get("proposed_times") == ["Thursday 09:00", "Friday 12:00"]


def test_bridge_falls_back_to_last_proposed_when_no_confirmed_time(monkeypatch):
    """Brief 248: when confirmedTime is empty/missing, the bridge falls
    back to the LAST entry in proposedTimes (most recently mentioned),
    not the first. This is a behavioral change from pre-Brief-248 where
    the bridge passed no date_time_label at all."""
    from shared import escalation_dispatcher
    from shared import state_registry

    captured = {}
    monkeypatch.setattr(state_registry, "appointment_upsert",
                         lambda **kw: captured.update(kw) or 999)
    fake_summary = {
        "extractedDetails": {
            "intent": "scheduling",
            "proposedTimes": ["Thursday 09:00", "Friday 12:00"],
            "confirmedTime": "",  # empty — fall back to proposed[-1]
            "topic": "Discovery call",
        },
    }
    monkeypatch.setattr(
        escalation_dispatcher._esc_summary, "generate_summary",
        lambda **kw: fake_summary)
    monkeypatch.setattr(state_registry, "wa_get_full_history", lambda *a, **k: [])

    escalation_dispatcher._generate_escalation_summary(
        escalation_id=2, channel="whatsapp",
        customer_id="248_cust_phone_2", customer_name="Calvin Test")

    assert captured.get("date_time_label") == "Friday 12:00", (
        f"date_time_label must fall back to last proposed time when "
        f"confirmedTime is empty; captured={captured}")


def test_bridge_uses_empty_label_when_no_times_at_all(monkeypatch):
    """Brief 248: when both confirmedTime AND proposedTimes are empty
    but intent IS scheduling (e.g., 'I want to schedule something soon'
    with no time), the bridge passes empty string for date_time_label
    and status='detected'."""
    from shared import escalation_dispatcher
    from shared import state_registry

    captured = {}
    monkeypatch.setattr(state_registry, "appointment_upsert",
                         lambda **kw: captured.update(kw) or 999)
    fake_summary = {
        "extractedDetails": {
            "intent": "scheduling",
            "proposedTimes": [],
            "confirmedTime": "",
            "topic": "General scheduling intent",
        },
    }
    monkeypatch.setattr(
        escalation_dispatcher._esc_summary, "generate_summary",
        lambda **kw: fake_summary)
    monkeypatch.setattr(state_registry, "wa_get_full_history", lambda *a, **k: [])

    escalation_dispatcher._generate_escalation_summary(
        escalation_id=3, channel="whatsapp",
        customer_id="248_cust_phone_3", customer_name="Calvin Test")

    assert captured.get("date_time_label") == ""
    assert captured.get("status") == "detected"
```

**Test design notes:**
- Test 1 is a schema-shape test (data file = unit under test; not a source-string-grepper because we're checking the runtime SUMMARY_TOOL dict's content, not source text).
- Tests 2-4 stub `_esc_summary.generate_summary` with hand-crafted summary dicts — the test exercises the BRIDGE's deterministic logic (which kwargs get passed to `appointment_upsert`), not Claude's judgment about what counts as "explicit confirmation". Claude's prompt-side judgment is documented in the schema description + system prompt rule; verifying it requires real LLM calls which are not run in CI.
- Boundary mock at `state_registry.appointment_upsert` so the test doesn't write to the dev DB.
- All 3 behavior tests use distinct customer_ids so they don't dedup against each other on re-runs.

### Step 6 — Out of scope (documented for future briefs)

- **Marina-side auto-confirm path** (parse customer message → call appointment_upsert with status='confirmed' directly) — issue #12 explicitly defers this. Manual confirm via Brief 242 endpoint stays the canonical path.
- **`features.appointment_auto_confirm` feature flag** — not implemented; flag would gate a future auto-confirm path.
- **Adjusting the `_summaries_materially_differ` dedup logic in `state_registry.py`** to include `confirmedTime` changes as a "material difference" — Brief 239's existing logic compares `customerWants + latestCustomerMessage + proposedTimes`. Adding `confirmedTime` would mean a fresh confirmation triggers a new alert fire even if other fields are unchanged. That's probably the right behavior but is a separate brief because it changes alert volume/cadence.
- **Frontend "Confirm appointment at 12:00" CTA button** — issue's "conservative acceptable behavior" alternative; SR's frontend work; backend now provides clean data via the updated date_time_label.
- **Backfill the 5 existing `appointments` rows whose date_time_label is stale** — out of scope; rare; operator can manually fix via the dashboard if desired.

## Tests

4 new tests in `wtyj/tests/dashboard/test_escalation_summary_confirmed_time.py` (NEW file).

Expected after-test count: **1064 passing / 0 failures** (1060 baseline + 4 new = 1064).

## Success Condition

After this brief lands:
1. SUMMARY_TOOL schema has `confirmedTime` in `extractedDetails.properties` AND in `extractedDetails.required`.
2. Summary system prompt instructs Claude to populate `confirmedTime` ONLY for explicit confirmation language in the LATEST customer message.
3. When Claude returns a non-empty `confirmedTime`, the bridge passes it as `appointment_upsert(..., date_time_label=...)`.
4. When Claude returns empty `confirmedTime` but non-empty `proposedTimes`, the bridge falls back to `proposedTimes[-1]` (most recent).
5. When both are empty, the bridge passes `date_time_label=""`.
6. Bridge keeps `status='pending_team_confirmation'` (no auto-confirm; operator clicks Brief 242's confirm button).
7. Existing intent='scheduling' bridge logic still fires for all 5 currently-tracked appointment rows on the next escalation event for those conversations.
8. 1064 tests passing (1060 + 4 new).

## Rollback

```
git revert <brief-248-commit-sha>
git push origin main
```

This restores the pre-Brief-248 schema (no confirmedTime field) and the pre-Brief-228-extended bridge (no date_time_label kwarg). Existing appointment rows keep their stale labels; new escalations behave as they did before this brief. CI re-deploys in ~90s.
