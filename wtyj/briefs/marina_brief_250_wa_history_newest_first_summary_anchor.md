# BRIEF 250 — Fix `wa_get_full_history` to return newest N (not oldest N) + anchor escalation summary on latest customer message

**Status:** Draft (round 2) | **Files:** wtyj/shared/state_registry.py, wtyj/dashboard/escalation_summary.py, wtyj/tests/test_201_dm_agent_em_dash.py | **Depends on:** Brief 249 (`54675df`) | **Blocks:** none

## Context

Issue #20 (Calvin live verification, P1) — the dashboard escalation summary box stays anchored to OLDER proposed times even when the customer's latest message proposes a new time. Calvin's exact reproduction: customer message at 2026-05-11T00:36:19Z said `"damm i see that my dog is sick and it will be 10:00 can u make it 10 o clock for hte apointment ?"`. The escalation summary id=29 created 2 seconds later (00:36:21Z) showed:
- `proposedTimes: ['tomorrow evening 17:00', 'monday morning at 11:00']` — **NO 10:00**
- `confirmedTime: 'Ill be there'` — Claude's stale extraction from a 23h-old message
- `customerWants: "Calvin wants to keep his original Monday morning at 11:00 intake appointment and has confirmed he will attend."` — **HALLUCINATION — Calvin is asking to RESCHEDULE to 10:00 because his dog is sick**
- `operatorNeedsToDecide: "Confirm that Monday at 11:00 is still reserved..."` — anchored to stale proposal
- `recommendedOptions: ["Confirm Monday at 11:00 is still on..."]` — same staleness
- `latestCustomerMessage: "no,leave it . its fine . Ill be there"` — **a message from 2026-05-10T01:32, 23 HOURS BEFORE the dog-sick message**

The operator reading this summary would Confirm Monday 11:00 — completely missing that the customer just asked to move to 10:00.

**Verified read-only — root cause is a long-latent SQL bug in `wa_get_full_history`:**

`wtyj/shared/state_registry.py:1584-1595`:
```python
def wa_get_full_history(phone: str, limit: int = 100) -> list:
    """Get full conversation history for a phone number (no 24h cutoff). Oldest first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, role, text, created_at FROM whatsapp_threads "
        "WHERE phone = ? ORDER BY created_at ASC LIMIT ?",
        (phone, limit)
    ).fetchall()
    conn.close()
    return [{"id": r[0], "role": r[1], "text": r[2], "created_at": r[3]} for r in rows]
```

**`ORDER BY created_at ASC LIMIT ?` returns the OLDEST N rows, not the newest N.** When conversation length > limit, this silently truncates the most-recent messages.

**Production verification:** Calvin's WhatsApp thread `69efec187aca03948969dc95` has **44 messages** total. `escalation_dispatcher.py:37` calls `wa_get_full_history(customer_id, limit=20)` → returns the OLDEST 20 messages (from 2026-05-10 early morning era). The dog-sick message at message #44 (last position) is INVISIBLE to Claude AND to Brief 239's `latestCustomerMessage` extraction (which walks `reversed(history)` of the SAME stale window and picks the most-recent customer message AMONG THOSE 20 — which happens to be "Ill be there" from message ~14).

**Caller survey (verified via grep):** 5 production callers of `wa_get_full_history`, all silently affected when their `limit` < total messages:
- `wtyj/agents/social/social_agent.py:695` — `limit=20` (escalation context for re-escalation logic)
- `wtyj/shared/escalation_dispatcher.py:37` — `limit=20` (Brief 235 summary generation; **the issue #20 bug site**)
- `wtyj/shared/state_registry.py:4136` — `limit=10` (internal — verified to be the `_last_customer_message_for` helper used by Brief 215 learning saves)
- `wtyj/dashboard/api.py:1404` — `limit=200` (full-conversation detail view; affects any conversation > 200 messages)
- `wtyj/dashboard/api.py:2342` — `limit=30` (suggest-reply context)

All 5 callers want the MOST RECENT N messages, not the oldest N. The bug has been latent in production since Brief 134-era when the function was added — silent until Calvin's 44-message conversation surfaced it.

**Why this issue manifests as a "summary intelligence" bug rather than a "dashboard shows wrong messages" bug:**
- `dashboard/api.py:1404` (limit=200) hides the bug for most conversations.
- The escalation summary path is the FIRST place where the truncation actually matters because it drives operator decision-making.
- Brief 248's `confirmedTime` extraction also goes through Claude over the truncated history — Claude sees only the OLDEST messages and over-fits to those.

**Verified — no other bugs in the summary chain:**
- Brief 239's `latestCustomerMessage` extraction at `escalation_dispatcher.py:55-62` is correct (walks `reversed(history)` and picks the first user-role message). The bug is upstream — `history` itself is truncated.
- Brief 248's `confirmedTime` schema field + prompt rule (added in `escalation_summary.py`) is correct. Claude is making reasonable judgments given the (stale) input it sees.
- The system prompt at `escalation_summary.py:163-189` already says "Extract EVERY proposed time/slot/option from the customer's messages." It just doesn't see the new ones.

## Why This Approach

**Considered:** Bump the limit at the call site in `escalation_dispatcher.py:37` from 20 to 100 or 200. **Rejected:** This is a workaround that doesn't fix the underlying bug — `social_agent.py:695` (limit=20), `state_registry.py:4136` (limit=10), and `dashboard/api.py:2342` (limit=30) all silently truncate to the OLDEST N. Future code paths that call `wa_get_full_history` with reasonable-looking small limits would inherit the same bug. The fix belongs at the SQL layer.

**Considered:** Add a new function `wa_get_recent_history(phone, limit)` that orders DESC and reverses, leaving `wa_get_full_history` unchanged. **Rejected:** parallel functions with overlapping semantics confuse callers (which one returns "the recent N"?). The existing function's docstring says "Oldest first" describing the OUTPUT order, not the SELECTION order — fixing the SELECT to pick the newest N while preserving the "oldest first" output is the lowest-surprise change.

**Considered:** Make this a 2-brief split — fix the SQL bug in one brief, address the summary anchoring in another. **Rejected:** they're the same bug. Once Claude sees the actual latest messages, the existing prompt (Brief 227 + 239 + 248) handles them correctly. Calvin's example summary would naturally include the dog-sick message + 10:00 once the history fetch returns the right window. Adding a prompt rule "anchor on the latest customer message" would still produce wrong output if the latest message is invisible to Claude. Fix the data layer first; the prompt tweak is belt-and-suspenders for edge cases where Claude DOES see the message but still over-weights older context.

**Considered:** Skip the prompt tweak entirely; rely on the SQL fix alone. **Rejected:** Calvin's expected behavior in issue #20 explicitly asks for "Customer wants/needs reflects the latest requested change" + "Suggested next step tells operator what to do now." A single prompt rule reinforces this without adding a new schema field. The prompt rule cost is one bullet; the SQL fix cost is one operator change. Both ship together.

**Tradeoff — backward-compatibility on the "oldest first" output contract:** all 5 production callers iterate the returned list expecting oldest-first order (verified by reading each call site). The SQL changes from `ORDER BY ASC LIMIT ?` to `ORDER BY DESC LIMIT ?` then `reversed()` in Python before returning — preserves the output order contract while changing the SELECTION semantic. Existing tests that assert on order continue to pass.

**Tradeoff — when limit > total messages (most conversations):** behavior is unchanged. `LIMIT 200` on a 44-message conversation returns all 44 with both ASC and DESC SELECT (just sorted differently before Python's `reversed()`). The bug only manifests when `total > limit`.

## Instructions

### Step 1 — Fix `wa_get_full_history` SQL

In `wtyj/shared/state_registry.py:1584-1595`, replace:

```python
def wa_get_full_history(phone: str, limit: int = 100) -> list:
    """Get full conversation history for a phone number (no 24h cutoff). Oldest first.
    Brief 201: also returns row id (SQLite autoincrement) so frontends can use it
    as a stable React key."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, role, text, created_at FROM whatsapp_threads "
        "WHERE phone = ? ORDER BY created_at ASC LIMIT ?",
        (phone, limit)
    ).fetchall()
    conn.close()
    return [{"id": r[0], "role": r[1], "text": r[2], "created_at": r[3]} for r in rows]
```

with:

```python
def wa_get_full_history(phone: str, limit: int = 100) -> list:
    """Get the most-recent conversation history for a phone number
    (no 24h cutoff). Returns the most recent `limit` messages, ordered
    oldest-first in the output (callers iterate forward through time).

    Brief 201: also returns row id (SQLite autoincrement) so frontends can use it
    as a stable React key.

    Brief 250: SELECT changed from `ORDER BY ASC LIMIT ?` to `ORDER BY
    DESC LIMIT ? ... reversed()`. Pre-Brief-250 the function returned
    the OLDEST N messages when total > limit — silently truncating the
    most recent ones. This broke escalation summary generation for any
    conversation > 20 messages (escalation_dispatcher.py:37 calls with
    limit=20) because Claude only saw stale history. Output order
    contract preserved: still oldest-first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, role, text, created_at FROM whatsapp_threads "
        "WHERE phone = ? ORDER BY created_at DESC LIMIT ?",
        (phone, limit)
    ).fetchall()
    conn.close()
    # Brief 250: reversed() to keep the documented oldest-first output
    # contract; SELECT picks the most-recent N rows.
    return [{"id": r[0], "role": r[1], "text": r[2], "created_at": r[3]} for r in reversed(rows)]
```

The function signature, return shape, and output ordering are unchanged from the caller's perspective. Only the SELECTION semantic changes — picks the newest N instead of the oldest N when truncating.

### Step 2 — Add prompt rule anchoring summary on latest customer message

In `wtyj/dashboard/escalation_summary.py` system prompt (around lines 175-189), the current hard-rules block ends with the Brief 248 confirmedTime rule. Add a new bullet at the END of the hard rules, immediately after the Brief 248 rule that ends with `"When in doubt, leave confirmedTime empty."`:

```python
            "- Brief 250: when the customer's MOST RECENT message changes "
            "the requested time, asks to reschedule, or introduces a new "
            "decision point (e.g., \"can u make it 10 instead\", \"actually "
            "let's do tomorrow\", \"my dog is sick can we move to X\"), "
            "the customerWants, operatorNeedsToDecide, and "
            "recommendedOptions fields MUST reflect that NEW request. "
            "Older proposed times that the customer hasn't explicitly "
            "kept on the table belong in previousProposedTimes (if they "
            "were retracted) OR may be omitted from proposedTimes if the "
            "newest message clearly supersedes them. The summary should "
            "tell the operator what to decide RIGHT NOW based on the "
            "latest message, not what was being decided 20 messages ago."
```

This rule does not add a new schema field — it tightens Claude's prompt-side judgment about how to write `customerWants` / `operatorNeedsToDecide` / `recommendedOptions` when the latest message changes the decision context.

### Step 3 — Add 3 new tests by extending the existing per-module test file

Per Brief 236's test-location rule: extend `wtyj/tests/test_201_dm_agent_em_dash.py` — that file already has `test_wa_get_full_history_includes_id` at line 91-100, the existing per-module test for `wa_get_full_history`. Append the 3 new tests at the end of that file:

```python


# ── Brief 250: wa_get_full_history must return MOST RECENT N when total > limit ─

def test_wa_get_full_history_returns_most_recent_when_total_exceeds_limit():
    """Brief 250: when a conversation has more messages than `limit`,
    the function MUST return the most-recent `limit` messages, not the
    oldest. Pre-Brief-250 the SQL was `ORDER BY ASC LIMIT ?` which
    returned the oldest N -- silently truncating the messages Claude
    needed to see in the escalation summary (issue #20 root cause)."""
    from shared import state_registry
    phone = "250_recent_phone"
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()
    # Seed 25 messages with sequential text. msg_0 is oldest, msg_24 is newest.
    for i in range(25):
        state_registry.wa_store_message(phone, "user", f"msg_{i}")
    history = state_registry.wa_get_full_history(phone, limit=10)
    assert len(history) == 10, f"expected 10 entries, got {len(history)}"
    # The 10 returned should be the MOST RECENT 10: msg_15..msg_24.
    texts = [m["text"] for m in history]
    assert texts[-1] == "msg_24", (
        f"last entry must be the most recent (msg_24); got {texts[-1]!r}")
    assert texts[0] == "msg_15", (
        f"first entry must be msg_15 (10th newest); got {texts[0]!r}")
    # Pre-Brief-250 this would have been msg_0..msg_9 -- oldest 10.
    assert "msg_0" not in texts, (
        f"msg_0 (oldest) MUST NOT be in the most-recent 10; "
        f"this would indicate the pre-Brief-250 ASC bug; texts={texts}")
    # Cleanup
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


def test_wa_get_full_history_preserves_oldest_first_output_order():
    """Brief 250: even though the SELECT now picks the newest N, the
    output order is still oldest-first (callers iterate forward through
    time). Backward-compat with all 5 production callers."""
    from shared import state_registry
    phone = "250_order_phone"
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()
    for i in range(5):
        state_registry.wa_store_message(phone, "user", f"order_{i}")
    history = state_registry.wa_get_full_history(phone, limit=10)
    assert len(history) == 5
    texts = [m["text"] for m in history]
    assert texts == ["order_0", "order_1", "order_2", "order_3", "order_4"], (
        f"output must be oldest-first (order_0 first, order_4 last); "
        f"got {texts}")
    # Cleanup
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


def test_wa_get_full_history_returns_all_when_total_below_limit():
    """Brief 250: when total messages <= limit, behavior is unchanged
    from pre-Brief-250 -- all messages returned, oldest-first. This is
    the common case for short conversations and dashboard full-history
    views (limit=200)."""
    from shared import state_registry
    phone = "250_below_limit_phone"
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()
    for i in range(3):
        state_registry.wa_store_message(phone, "user", f"all_{i}")
    history = state_registry.wa_get_full_history(phone, limit=100)
    assert [m["text"] for m in history] == ["all_0", "all_1", "all_2"]
    # Cleanup
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()
```

**Test design notes:**
- Tests 1, 2, 3 exercise the real SQL bug fix end-to-end (real DB, real `wa_store_message` writes, real `wa_get_full_history` read). The 25-message seed in Test 1 directly reproduces Calvin's 44-message scenario at smaller scale -- pre-Brief-250 the test would FAIL because `texts[-1]` would be `"msg_9"` (oldest 10).
- Cleanup uses inline DELETE at start AND end of each test (defensive pre-clean + post-clean). The dev DB is shared; Brief 240's `_wipe_*_for` helper pattern would be cleaner but adding a new helper just for these 3 tests is over-engineering.
- **Test 4 from round 1 was DROPPED** per round-1 reviewer's correct call: opening `escalation_summary.__file__` and grepping for "Brief 250" / "MOST RECENT message" is the exact source-string-grepper pattern Brief 236 banned. The Brief 250 prompt rule's effect is observable in production (next escalation Calvin sends with a change-request) AND would require real Claude calls to test in CI -- which we don't run. Dropping the test loses zero behavioral coverage.

### Step 4 — Out of scope (documented for future briefs)

- **Brief 248 confirmedTime over-extraction on pure acknowledgements** ("Ill be there" being captured as confirmedTime) — separate concern; flagged in issue #19's verification comment. The current Brief 250 prompt doesn't address it. A future 1-line prompt tweak could add explicit "doesn't qualify" examples for pure acknowledgements without a time. Defer until it actually surfaces as user-visible weirdness.
- **Caching/indexing for `wa_get_full_history`** — the SQL already uses `phone` as a WHERE filter; adding an index on `(phone, created_at)` would speed up the DESC + LIMIT pattern. Defer until query times become measurable.
- **Backfill prior escalation summaries that were generated against truncated history** — the 5 existing appointment rows on unboks have stale `dateTimeLabel` values from pre-Brief-250 summary generations. They'll auto-correct on the next escalation event for each conversation. Out of scope for this brief.
- **Bump limits at call sites** — limits stay at their current values (20, 30, 200, etc.). The bug fix at the SQL layer makes the limits semantically correct; bumping numbers is a separate decision about how much context Claude needs.
- **Prompt rule about retracting older proposed times automatically** — Brief 250's rule says older times "may be omitted" or go in `previousProposedTimes` "if retracted". A stricter rule could auto-move all older times to previous when the latest message proposes new ones. Defer; over-zealous removal could lose context the operator wants.

## Tests

3 new tests appended to `wtyj/tests/test_201_dm_agent_em_dash.py` (extends existing per-module test file per Brief 236; that file already has `test_wa_get_full_history_includes_id` at line 91).

Expected after-test count: **1073 passing / 0 failures** (1070 baseline + 3 new = 1073).

Dropped 1 test from round 1 draft (Test 4: banned source-string-grepper per Brief 236; not replaced because the prompt rule's effect is observable in production but not unit-testable without real Claude calls).

## Success Condition

After this brief lands:
1. `wa_get_full_history(phone, limit=N)` returns the most-recent N messages when total > N (output still oldest-first for backward-compat).
2. When total <= N, behavior is unchanged from pre-Brief-250 (returns all, oldest first).
3. The escalation summary's `latestCustomerMessage` field correctly reflects the customer's most recent message even on long conversations.
4. Claude has visibility into the most-recent customer messages when generating summaries; `customerWants` / `operatorNeedsToDecide` / `recommendedOptions` reflect the latest decision context.
5. Brief 248's `confirmedTime` extraction continues to work; Brief 239's `latestCustomerMessage` extraction continues to work; Brief 228's `appointment_upsert` bridge continues to work — all just with correct (non-truncated) input.
6. Existing 1070 tests still pass.
7. Production verification (Calvin sends another customer message that changes a decision context): the next escalation summary should reflect the change.

## Rollback

```
git revert <brief-250-commit-sha>
git push origin main
```

This restores the pre-Brief-250 SQL bug (oldest N returned when truncating) and removes the Brief 250 prompt rule. The 5 production callers go back to silently truncating to the oldest N. Calvin's escalation summaries go back to anchoring on stale older proposals. CI re-deploys in ~90s.
