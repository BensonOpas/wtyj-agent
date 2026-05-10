# BRIEF 239 — Escalation alert quality + active summary freshness

**Status:** Draft | **Files:** `wtyj/shared/state_registry.py` (extend `create_pending_notification` with `mode` param + reorder summary-then-alert + pass summary to dispatcher; add `_summaries_materially_differ` helper for update-spam suppression), `wtyj/dashboard/api.py` (`_fire_escalation_alerts` accepts `summary_dict` + `is_update` and builds rich subject/body when summary present; the rich body surfaces `previousProposedTimes` when non-empty), `wtyj/dashboard/escalation_summary.py` (add `previousProposedTimes` to SUMMARY_TOOL schema + prompt rule), `wtyj/shared/escalation_dispatcher.py` (attach `latestCustomerMessage` derived from history before persisting), `wtyj/agents/social/dm_agent.py` (pass `mode="soft"` on the one `[ESCALATE]` create_pending_notification call), `wtyj/agents/social/social_agent.py` (pass `mode` on the 6 `'escalation'` create_pending_notification calls — soft for capacity/booking-flow-off/semi, hard for re-escalation/full-booking/manifest-failure), `wtyj/agents/marina/email_poller.py` (pass `mode` on the 4 `'escalation'` create_pending_notification calls), `wtyj/tests/social/test_217_alert_delivery.py` (EXTEND with rich-body + suppression + Friday-12:00 cases) | **Depends on:** Brief 213 (pending_notifications.mode column), Brief 217 (alert dispatcher), Brief 227 (structured summary), Brief 235 (dispatcher registration in both processes + dedup status filter), Brief 238 (tenant isolation guard — touched files must not regress allowlist semantics) | **Blocks:** Nr 2 client dashboard usefulness — operators can't act on alerts they don't understand.

## Context

The CTO posted a real bad-alert example from production:

```
Subject: New escalation: Calvin
Body:
  New escalation in Unboks
  Customer: Calvin
  Channel: whatsapp
  Mode: (unset)
  Summary: Marina escalated a whatsapp conversation
  Action: Open dashboard to review.
```

This email tells the operator nothing useful — no reason, no latest message, no decision needed, no proposed times, no options. Meanwhile the dashboard's structured summary panel (Brief 227) DOES have all of that information stored on the same row. The two surfaces are inconsistent.

The CTO also flagged that when a customer changes their mind mid-escalation (e.g., "i changed my mind, i wanna change it to friday 12:00" after earlier proposing Thu 17:00 / Mon 11:00), the dashboard summary stays stale — the operator sees the old proposed times.

### Audit findings (where each problem lives)

**Call-site inventory.** A grep for `create_pending_notification(` returns 16 sites total. Verified by reading each: **11 are `notification_type='escalation'`** (these need mode); **5 are `notification_type='relay'`** (these are Marina's "ask the team a question" relay flow, gated out of `_alert_dispatcher` at `state_registry.py:1436`, and do not need mode). Exact split:

| File | Line | notification_type |
|---|---|---|
| dm_agent.py | 272 | escalation |
| social_agent.py | 260 | relay |
| social_agent.py | 276 | escalation |
| social_agent.py | 495 | escalation |
| social_agent.py | 593 | relay |
| social_agent.py | 682 | escalation |
| social_agent.py | 716 | escalation |
| social_agent.py | 764 | escalation |
| social_agent.py | 895 | escalation |
| email_poller.py | 736 | relay |
| email_poller.py | 749 | escalation |
| email_poller.py | 1037 | relay |
| email_poller.py | 1106 | escalation |
| email_poller.py | 1147 | escalation |
| email_poller.py | 1221 | escalation |

This brief touches the 11 escalation rows. Relay rows are out of scope.

**1. Vague alert email body** — `wtyj/dashboard/api.py:1569-1594` `_fire_escalation_alerts` builds the email body from the `subject` argument it receives. The summary line of the email IS the `subject`. For DM escalations, `wtyj/agents/social/dm_agent.py:278` hardcodes `subject=f"{_agent} escalated a {channel} conversation"`. That is exactly the "Marina escalated a whatsapp conversation" string the operator sees. The dispatcher never opens the row's `escalation_summary` column.

**2. Mode shows "(unset)"** — `_alert_dispatcher` is called from `wtyj/shared/state_registry.py:1438` with four positional args: `(row_id, customer_name, channel, subject)`. The dispatcher signature at `dashboard/api.py:1569` declares a fifth `mode=None` param, never populated by the caller. Even if the caller tried to pass it, `create_pending_notification` itself doesn't accept a `mode` argument — `pending_notifications.mode` is set only via the separate Brief 213 `set_escalation_mode` endpoint that operators call manually from the dashboard. So the row is born with `mode IS NULL` and the alert literally cannot know.

**3. Stale active summary on re-escalation** — Brief 235 already fixed half of this: `create_pending_notification` (state_registry.py:1396-1425) now UPDATEs an existing `pending`/`sent` row instead of inserting a duplicate. After the update it triggers `_summary_dispatcher` again (lines 1444-1457), which regenerates the structured summary from the latest history. **So the summary DOES update — but ONLY when `create_pending_notification` is called again.** If the customer's "i changed my mind" message doesn't trigger a re-escalation flag (e.g., the Marina/dm_agent path stores the message but doesn't re-call `create_pending_notification` because the conversation is already escalated), the summary stays stale. Verified in `wtyj/agents/social/dm_agent.py:266` — the `[ESCALATE]` sentinel detection is the only trigger; absent the sentinel, no re-summary. In `wtyj/agents/social/social_agent.py:240-282` (Brief 184), the fully-escalated guard DOES re-call `create_pending_notification` on `semi_escalation:true` or `requires_human:true`. So the WA path handles re-escalation; the DM path only does if Calvin emits `[ESCALATE]` again.

**4. Alert and dashboard are two disjoint summary code paths** — dashboard reads `state_registry.get_active_escalation_summary_for(cid)` (state_registry.py:1868) which parses the JSON stored on the row. Alert dispatcher only sees the static `subject` string. Nothing wires them together.

**5. Duplicate "New escalation" spam** — every call to `create_pending_notification` (state_registry.py:1436) fires `_alert_dispatcher` regardless of insert-vs-update. Subject is always "New escalation: Calvin". A customer who sends 4 follow-up messages on an open escalation generates 4 identical-looking-but-different-bodied emails to the operator with stale subjects.

**6. `latestCustomerMessage` and `previousProposedTimes` are not in the summary schema** — the CTO's spec for the rich body and the Friday-12:00 example references both. SUMMARY_TOOL (escalation_summary.py:36-108) has `reason / customerWants / operatorNeedsToDecide / recommendedOptions / extractedDetails.{intent,proposedTimes,topic}` — neither `latestCustomerMessage` nor `previousProposedTimes`. Both must be added AND consumed (the alert body must surface them) so the schema isn't dead weight.

### What this brief delivers

A single structured summary, generated once at escalation time, used by BOTH the dashboard and the alert email. The alert dispatcher receives the summary and builds a rich subject + body when it's available; it falls back to the legacy vague format when it's not (no Anthropic key, generation failed, etc.). Mode is set at insert time so it actually shows up. Update-vs-create is signalled to the dispatcher so the subject reads "Updated escalation:" instead of "New escalation:" on the second+ fire. Update spam is suppressed by comparing the new summary against the previous one — only fires a follow-up alert if the operator-relevant content actually changed. `previousProposedTimes` is added to the schema AND surfaced as a "Previously proposed (now retracted): …" line in the alert body when non-empty, so the operator sees both the change and the new ask. `latestCustomerMessage` is derived in Python from the conversation history (cheaper than asking Claude) and surfaces verbatim in the rich body.

### Out of scope (deferred — explicit per CTO directive)

- **Appointment alerts** — Brief 228 wired `appointment_upsert` into the summary dispatcher; this brief does not extend that.
- **WhatsApp alert delivery itself** — `_fire_escalation_alerts` currently calls `send_whatsapp_message` for the `whatsapp` alert channel. Touched only to ensure the new subject/body propagate correctly; no fixes to the WA delivery path itself. Existing `alert_deliveries` row contracts preserved exactly.
- **BlueMarlin** — deprecated per Brief 238 + CTO directive. Test fixtures use the BlueMarlin-loaded conftest config (existing pattern) but no BlueMarlin-specific code is touched.
- **Relay rows** — the 5 `notification_type='relay'` call sites are not touched. Relay is a separate flow gated out of the alert dispatcher.
- **Per-tenant alert template overrides** — keep a single template hardcoded in `_fire_escalation_alerts`. Tenant-template-friendly because content comes from `client.json` (`business.name`) + the per-tenant Claude-generated `escalation_summary`. No `if tenant == 'unboks'` anywhere.

## Why This Approach

Three options were considered for the summary-reuse decision:

**A — Two separate summary builders, one for dashboard and one for email (current state, vague).** Rejected. Drift between the two surfaces is exactly the bug. The structured summary already exists for the dashboard; reusing it costs zero new Claude calls.

**B — Generate a separate, simpler "alert blurb" with a second Claude call dedicated to the email.** Rejected. Doubles the Claude spend per escalation. Risks divergence between what the email says and what the dashboard panel shows. Violates Rule 1 of CLAUDE.md (one Claude call per inbound).

**C — Reuse the Brief 227 `escalation_summary` for both the dashboard and the alert email; reorder `create_pending_notification` so the summary is generated BEFORE the alert fires; pass it to the dispatcher (chosen).** One Claude call per escalation. Both surfaces read from the same JSON. The alert builder formats the same dict differently; the dashboard renders it as panels. Backward compatible — when summary generation fails (no API key, Anthropic 529, etc.), the alert dispatcher falls back to the existing vague format and the dashboard's frontend already has its own generic-text fallback. Tradeoff: makes `create_pending_notification` reorder summary-then-alert, which is a hot path; profiled cost is one Claude call (already in the path) plus one extra DB read for the previous summary in the suppression check (~negligible).

For update-spam suppression, three detection methods were considered:

**1 — Time-based debounce (suppress within N minutes).** Rejected. A customer might change their mind and then go silent; the operator would miss the late update because the suppression window expired.

**2 — Full-JSON deep equality on the summary dict.** Rejected. Claude regenerates summaries from scratch each time; trivial wording differences in `reason`/`operatorNeedsToDecide` would defeat the suppression even when the operator-relevant content is unchanged.

**3 — Material-difference comparison on three operator-relevant fields: `customerWants`, `latestCustomerMessage`, and `extractedDetails.proposedTimes` (chosen).** Deterministic, easy to test, captures the only changes that change what the operator must do. Acknowledged limitation: a customer who pivots from "refund" to "complaint" while keeping the same wording-and-times would be suppressed; this is unlikely in practice and fixable later by adding `intent` to the comparison if it surfaces. Documented here so future-you doesn't have to rediscover it.

For the rich subject:

- When `summary_dict` is None → legacy `New escalation: Calvin` / `Updated escalation: Calvin` (Brief 217 contract preserved).
- When `summary_dict` present and `intent="scheduling"` and `is_update=True` and `proposedTimes` non-empty → `Updated escalation: Calvin changed meeting time to Friday 12:00`.
- When `summary_dict` present and `intent="scheduling"` (any other state) → `Escalation alert: Calvin needs a scheduling decision`.
- When `summary_dict` present and `intent != "scheduling"` and `customerWants` non-empty → `Escalation alert: Calvin — <first 60 chars of customerWants>`.
- Fallback → `Escalation alert: Calvin`.

## Instructions

### Step 1 — Extend `wtyj/dashboard/escalation_summary.py` SUMMARY_TOOL schema

In `SUMMARY_TOOL["input_schema"]["properties"]["extractedDetails"]["properties"]`, add a new optional field after `proposedTimes`:

```python
"previousProposedTimes": {
    "type": "array",
    "items": {"type": "string"},
    "description": (
        "Time slots the customer proposed earlier in the conversation but "
        "explicitly retracted or changed. Use this when the customer says "
        "they 'changed their mind' or proposes a different time after an "
        "earlier proposal. Empty list when there is no retraction. Do not "
        "include times that are still on the table — those go in proposedTimes."
    ),
},
```

DO NOT add this to the `required` list of `extractedDetails` — it is opt-in. Update the system_prompt block (`generate_summary` lines 142-161) to add one line at the end of the "Hard rules" section:

```
- When the customer explicitly retracts a previously proposed time and
  proposes a different one (e.g., "i changed my mind, change it to X"),
  put the new time in proposedTimes and the retracted time(s) in
  previousProposedTimes. Do not put the same time in both lists.
```

The alert body in Step 4 reads this field — it is NOT dead schema.

### Step 2 — Surface `latestCustomerMessage` in `wtyj/shared/escalation_dispatcher.py`

In `_generate_escalation_summary`, after the `summary_dict = _esc_summary.generate_summary(...)` call (line 41-47) and BEFORE the appointment_upsert block, append the latest customer message derived from history:

```python
if summary_dict and history:
    # Brief 239: surface the most recent customer-side message in the
    # summary so the alert email and dashboard can display it verbatim
    # without the operator having to scroll the conversation. Walk the
    # history newest-last and pick the most recent message whose role is
    # customer/user/incoming.
    for _msg in reversed(history):
        _role = (_msg.get("role") or "").lower()
        if _role in ("user", "customer", "incoming"):
            _text = (_msg.get("text") or _msg.get("content")
                     or _msg.get("body") or "").strip()
            if _text:
                summary_dict["latestCustomerMessage"] = _text
                break
```

This keys off the same role-name set already used in `_format_history` at line 117 of `escalation_summary.py`, so it stays consistent.

### Step 3 — Add `mode` parameter + reorder summary-then-alert in `wtyj/shared/state_registry.py`

In `create_pending_notification` (lines 1384-1459):

1. Add `mode: Optional[str] = None` to the signature, after `relay_token`. Update the docstring to mention mode.

2. **Define `existing` at function scope** so non-escalation paths don't NameError on `is_update = (existing is not None)`. Initialize it before the `if notification_type == "escalation":` dedup block:
   ```python
   existing = None  # Brief 239: gate-safe initialization for is_update below
   if notification_type == "escalation":
       existing = conn.execute(
           "SELECT id FROM pending_notifications "
           "WHERE customer_id = ? AND notification_type = 'escalation' "
           "AND status IN ('pending', 'sent') "
           "ORDER BY created_at DESC LIMIT 1",
           (customer_id,)).fetchone()
       if existing:
           row_id = existing[0]
   ```

3. Modify the INSERT (current line 1411-1418) to include the `mode` column:
   ```python
   cur = conn.execute(
       "INSERT INTO pending_notifications "
       "(notification_type, relay_token, channel, customer_id, customer_name, "
       "subject, body, status, created_at, mode) "
       "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
       (notification_type, relay_token, channel, customer_id, customer_name,
        subject, body, now, mode)
   )
   ```

4. Modify the UPDATE (current line 1421-1425) so a non-None `mode` overwrites; a None preserves whatever mode was previously set (`COALESCE`):
   ```python
   conn.execute(
       "UPDATE pending_notifications "
       "SET subject = ?, body = ?, customer_name = ?, created_at = ?, "
       "mode = COALESCE(?, mode) "
       "WHERE id = ?",
       (subject, body, customer_name, now, mode, row_id))
   ```

5. **Reorder the summary-then-alert block.** Move the existing summary-generation block (current lines 1442-1457) BEFORE the alert-dispatcher block (current lines 1436-1440). Capture the result so the alert dispatcher can be called with it.

6. Add `_summaries_materially_differ` helper as a module-level function near the top of state_registry.py (next to the other dispatcher globals at lines 22-43):
   ```python
   def _summaries_materially_differ(old: dict, new: dict) -> bool:
       """Brief 239: compare two escalation_summary dicts; return True only
       if operator-relevant content has changed (proposed times, latest
       customer message, or what the customer wants). Used to suppress
       duplicate update alert emails when the summary regenerated but the
       situation didn't actually change for the operator.

       Returns True when the dicts differ on customerWants OR
       latestCustomerMessage OR extractedDetails.proposedTimes. Returns
       False when all three match. Returns True (defensive: fire alert)
       if either input is not a dict."""
       if not isinstance(old, dict) or not isinstance(new, dict):
           return True
       if old.get("customerWants") != new.get("customerWants"):
           return True
       if old.get("latestCustomerMessage") != new.get("latestCustomerMessage"):
           return True
       _o = (old.get("extractedDetails") or {}).get("proposedTimes") or []
       _n = (new.get("extractedDetails") or {}).get("proposedTimes") or []
       if list(_o) != list(_n):
           return True
       return False
   ```

7. Replace the alert-dispatch block to:
   - Compute `is_update = (existing is not None)` AFTER the row write completes (and `existing` is in scope thanks to step 2)
   - Read the previous summary BEFORE the new one is persisted (only on update path)
   - Generate fresh summary
   - Persist fresh summary
   - Decide whether to fire based on `is_update` + material-differ check
   - Read the row's `mode` (which is what we just set) and pass it to the dispatcher
   - Pass `summary_dict` and `is_update` to the dispatcher

   New shape (illustrative — preserve the try/except guard around dispatch):
   ```python
   # Brief 188: escalation/relay created → conversation is now "open"
   set_conversation_status(customer_id, "open", channel)

   is_update = (existing is not None) and (notification_type == "escalation")

   prev_summary = None
   if is_update:
       try:
           conn = _get_conn()
           _row = conn.execute(
               "SELECT escalation_summary FROM pending_notifications "
               "WHERE id = ?", (row_id,)).fetchone()
           conn.close()
           if _row and _row[0]:
               prev_summary = json.loads(_row[0])
       except Exception:
           prev_summary = None

   # Brief 227 + 239: generate fresh summary BEFORE alert fires so the
   # alert body can use it
   summary_dict = None
   if notification_type == "escalation" and _summary_dispatcher is not None:
       try:
           summary_dict = _summary_dispatcher(
               row_id, channel, customer_id, customer_name)
           if summary_dict:
               conn = _get_conn()
               conn.execute(
                   "UPDATE pending_notifications SET escalation_summary = ? "
                   "WHERE id = ?", (json.dumps(summary_dict), row_id))
               conn.commit()
               conn.close()
       except Exception:
           summary_dict = None

   # Brief 217 + 239: alert dispatch — suppress duplicate updates with
   # unchanged summary
   if notification_type == "escalation" and _alert_dispatcher is not None:
       should_fire = True
       if is_update and prev_summary is not None and summary_dict is not None:
           should_fire = _summaries_materially_differ(prev_summary, summary_dict)
       if should_fire:
           try:
               conn = _get_conn()
               _r = conn.execute(
                   "SELECT mode FROM pending_notifications WHERE id = ?",
                   (row_id,)).fetchone()
               conn.close()
               actual_mode = _r[0] if _r else None
           except Exception:
               actual_mode = None
           try:
               _alert_dispatcher(row_id, customer_name, channel, subject,
                                  mode=actual_mode,
                                  summary_dict=summary_dict,
                                  is_update=is_update)
           except Exception:
               pass

   return row_id
   ```

   **Note on ordering:** keep `set_conversation_status` ahead of summary/alert. The status flip must happen regardless of whether the alert/summary succeeds.

### Step 4 — Rich subject/body in `wtyj/dashboard/api.py:_fire_escalation_alerts`

Replace the body of `_fire_escalation_alerts` (lines 1569-1653). Signature gains two kwargs:

```python
def _fire_escalation_alerts(escalation_id: int, customer_name: str,
                             channel: str, summary: str,
                             mode: str = None,
                             summary_dict: dict = None,
                             is_update: bool = False) -> None:
```

(The 4th positional param keeps its existing name `summary` to preserve
backward compatibility with Brief 217's signature and the three Brief 226
tests at `wtyj/tests/social/test_226_alternative_email_destination.py`
that pass `summary=` as a kwarg. The new `summary_dict` and `is_update`
kwargs are additive only.)

```python
```

Add three module-level helpers (place above `_fire_escalation_alerts`):

```python
def _channel_label(channel: str) -> str:
    return {
        "whatsapp": "WhatsApp",
        "email": "Email",
        "instagram": "Instagram",
        "facebook": "Facebook",
        "messenger": "Messenger",
    }.get((channel or "").lower(), (channel or "").title() or "(unknown)")


def _mode_label(mode: str) -> str:
    if mode == "soft":
        return "Agent needs help"
    if mode == "hard":
        return "Hard escalation"
    return "(unset)"


def _build_alert_subject(customer_name: str, summary_dict: dict,
                          is_update: bool) -> str:
    if not summary_dict:
        # Legacy vague subject (preserves Brief 217 contract for
        # rows whose summary generation failed or hasn't run yet)
        prefix = "Updated escalation" if is_update else "New escalation"
        return f"{prefix}: {customer_name or 'customer'}"
    name = customer_name or "customer"
    intent = ((summary_dict.get("extractedDetails") or {}).get("intent") or "").lower()
    proposed = ((summary_dict.get("extractedDetails") or {}).get("proposedTimes") or [])
    prefix = "Updated escalation" if is_update else "Escalation alert"
    if intent == "scheduling" and is_update and proposed:
        return f"{prefix}: {name} changed meeting time to {proposed[0]}"
    if intent == "scheduling":
        return f"{prefix}: {name} needs a scheduling decision"
    wants = (summary_dict.get("customerWants") or "").strip()
    if wants:
        return f"{prefix}: {name} — {wants[:60]}"
    return f"{prefix}: {name}"


def _build_alert_body(customer_name: str, channel: str, mode: str,
                      summary_dict: dict, fallback_subject: str,
                      client_name: str) -> str:
    if not summary_dict:
        # Legacy vague body (preserved for no-summary rows)
        safe_summary = (fallback_subject or "")[:200]
        return (
            f"New escalation in {client_name}\n\n"
            f"Customer: {customer_name or '(unknown)'}\n"
            f"Channel: {channel or '(unknown)'}\n"
            f"Mode: {_mode_label(mode)}\n"
            f"Summary: {safe_summary}\n"
            f"Action: Open dashboard to review."
        )
    reason = (summary_dict.get("reason") or "(no reason captured)").strip()
    decide = (summary_dict.get("operatorNeedsToDecide") or "(no decision specified)").strip()
    options = summary_dict.get("recommendedOptions") or []
    options_text = "\n".join(f"- {o}" for o in options[:5]) or "- (no options listed)"
    latest_msg = (summary_dict.get("latestCustomerMessage") or "").strip()
    latest_block = ""
    if latest_msg:
        latest_block = f'Latest customer message:\n"{latest_msg}"\n\n'
    # Brief 239: surface previousProposedTimes as a "Previously proposed
    # (now retracted)" line when non-empty. Consumes the schema field
    # added in Step 1.
    prev_times = ((summary_dict.get("extractedDetails") or {})
                  .get("previousProposedTimes") or [])
    prev_block = ""
    if prev_times:
        prev_block = (f"Previously proposed (now retracted): "
                      f"{', '.join(prev_times)}\n\n")
    return (
        f"Escalation alert\n\n"
        f"Customer: {customer_name or '(unknown)'}\n"
        f"Channel: {_channel_label(channel)}\n"
        f"Mode: {_mode_label(mode)}\n\n"
        f"Reason:\n{reason}\n\n"
        f"{prev_block}"
        f"{latest_block}"
        f"Decision needed:\n{decide}\n\n"
        f"Suggested options:\n{options_text}\n\n"
        f"Action:\nOpen dashboard to reply."
    )
```

Inside the dispatcher itself, call these helpers and use their results in the existing per-channel dispatch loop. Pseudo:

```python
biz = config_loader.get_business() or {}
client_name = biz.get("name", "Unboks")
default_email = biz.get("support_email", "") or biz.get("email", "")

email_subject = _build_alert_subject(customer_name, summary_dict, is_update)
alert_text = _build_alert_body(customer_name, channel, mode, summary_dict,
                                summary, client_name)

# email branch:
smtp_send(dest, email_subject, alert_text)
# whatsapp branch:
ok = send_whatsapp_message(dest, alert_text)
# alert_deliveries writes unchanged
```

### Step 5 — Mode wiring at the 11 escalation `create_pending_notification` call sites

Audit and pass `mode` consistently. **Read 5-10 lines around each site before editing** to confirm the assignment matches the actual escalation type. Plan:

**Soft mode** (the AI is asking for human input — the AI is still expected to reply once the human helps):
- `wtyj/agents/social/dm_agent.py:272` — `[ESCALATE]` sentinel = AI asked for help → `mode="soft"`
- `wtyj/agents/social/social_agent.py:495` — group exceeds capacity, operator chooses how to handle the special arrangement → `mode="soft"`
- `wtyj/agents/social/social_agent.py:716` — booking_flow OFF, escalates booking intents to operator → `mode="soft"`
- `wtyj/agents/social/social_agent.py:895` — `semi_escalation:true` from Marina's response → `mode="soft"`
- `wtyj/agents/marina/email_poller.py:749` — Brief 192 relay-style escalation (still escalation, semi-style) → `mode="soft"`
- `wtyj/agents/marina/email_poller.py:1106` — semi/relay escalation in email Marina path → `mode="soft"`
- `wtyj/agents/marina/email_poller.py:1147` — semi/relay escalation in email Marina path → `mode="soft"`

**Hard mode** (the AI is stepping out — human takes over the conversation):
- `wtyj/agents/social/social_agent.py:276` — Brief 184 RE-escalation `requires_human:true` → `mode="hard"`
- `wtyj/agents/social/social_agent.py:682` — full booking-context escalation w/ `requires_human:true` → `mode="hard"`
- `wtyj/agents/social/social_agent.py:764` — manifest API failure after 2 retries (system-side, no human-collab needed) → `mode="hard"`
- `wtyj/agents/marina/email_poller.py:1221` — full email escalation `requires_human:true` → `mode="hard"`

For each call site, add `mode="soft"` or `mode="hard"` as a kwarg at the end of the existing call. The 5 relay rows (social_agent.py:260, social_agent.py:593, email_poller.py:736, email_poller.py:1037) are NOT touched — relay rows skip the alert dispatcher entirely (`state_registry.py:1436` gate) and their `mode` column stays NULL.

### Step 6 — Tests in `wtyj/tests/social/test_217_alert_delivery.py` (EXTEND, do not rewrite)

Add 7 new tests at the bottom of the file (six logic tests + one previousProposedTimes assertion):

```python
# ── Brief 239: rich alert body, suppression, Friday-12:00 case ─────────

def _make_summary(reason="Calvin wants to schedule a meeting.",
                   wants="Schedule a meeting.",
                   decide="Choose a time.",
                   options=None,
                   intent="scheduling",
                   proposed=None,
                   prev_proposed=None,
                   latest_msg=""):
    s = {
        "reason": reason,
        "customerWants": wants,
        "operatorNeedsToDecide": decide,
        "recommendedOptions": options or ["Confirm Friday 12:00",
                                            "Suggest another time",
                                            "Switch to human takeover"],
        "extractedDetails": {
            "intent": intent,
            "proposedTimes": proposed or ["Friday 12:00"],
            "topic": "scheduling",
        },
    }
    if prev_proposed is not None:
        s["extractedDetails"]["previousProposedTimes"] = prev_proposed
    if latest_msg:
        s["latestCustomerMessage"] = latest_msg
    return s


def test_alert_body_uses_rich_summary_when_available(monkeypatch):
    """Brief 239: when summary_dict is supplied, body includes reason,
    decision, options, and the latest customer message verbatim."""
    from dashboard import api as dapi
    captured = {}
    def fake_smtp(to, subj, body): captured.update(to=to, subj=subj, body=body)
    monkeypatch.setattr(dapi, "smtp_send", fake_smtp)
    monkeypatch.setattr(dapi.state_registry, "get_alert_settings",
                         lambda **k: {"channels": {"email": {"enabled": True,
                                                              "destination": "ops@example.com"}}})
    monkeypatch.setattr(dapi.state_registry, "record_alert_delivery",
                         lambda *a, **k: None)
    summary = _make_summary(latest_msg="i changed my mind, i wanna change it to friday 12:00")
    dapi._fire_escalation_alerts(
        escalation_id=1, customer_name="Calvin", channel="whatsapp",
        subject="ignored", mode="soft", summary_dict=summary, is_update=False)
    assert "Reason:" in captured["body"]
    assert "Calvin wants to schedule" in captured["body"]
    assert "i changed my mind" in captured["body"]
    assert "Mode: Agent needs help" in captured["body"]
    assert "- Confirm Friday 12:00" in captured["body"]


def test_alert_body_falls_back_to_vague_when_no_summary(monkeypatch):
    """Brief 239: when summary_dict is None (Claude failed), body uses the
    legacy Brief 217 format so old tests + no-API-key paths still work."""
    from dashboard import api as dapi
    captured = {}
    def fake_smtp(to, subj, body): captured.update(to=to, subj=subj, body=body)
    monkeypatch.setattr(dapi, "smtp_send", fake_smtp)
    monkeypatch.setattr(dapi.state_registry, "get_alert_settings",
                         lambda **k: {"channels": {"email": {"enabled": True,
                                                              "destination": "ops@example.com"}}})
    monkeypatch.setattr(dapi.state_registry, "record_alert_delivery",
                         lambda *a, **k: None)
    dapi._fire_escalation_alerts(
        escalation_id=1, customer_name="Calvin", channel="whatsapp",
        subject="Marina escalated a whatsapp conversation",
        mode=None, summary_dict=None, is_update=False)
    assert "Marina escalated a whatsapp conversation" in captured["body"]
    assert captured["subj"] == "New escalation: Calvin"


def test_alert_subject_specific_for_scheduling_update(monkeypatch):
    """Brief 239: when intent=scheduling AND is_update AND proposedTimes
    non-empty, subject names the new time."""
    from dashboard import api as dapi
    captured = {}
    def fake_smtp(to, subj, body): captured.update(subj=subj)
    monkeypatch.setattr(dapi, "smtp_send", fake_smtp)
    monkeypatch.setattr(dapi.state_registry, "get_alert_settings",
                         lambda **k: {"channels": {"email": {"enabled": True,
                                                              "destination": "ops@example.com"}}})
    monkeypatch.setattr(dapi.state_registry, "record_alert_delivery",
                         lambda *a, **k: None)
    summary = _make_summary(proposed=["Friday 12:00"])
    dapi._fire_escalation_alerts(
        escalation_id=1, customer_name="Calvin", channel="whatsapp",
        subject="ignored", mode="soft", summary_dict=summary, is_update=True)
    assert captured["subj"] == "Updated escalation: Calvin changed meeting time to Friday 12:00"


def test_alert_body_surfaces_previous_proposed_times(monkeypatch):
    """Brief 239: when previousProposedTimes is non-empty, body includes a
    'Previously proposed (now retracted): ...' line. Verifies the schema
    field added in Step 1 is consumed by the body builder in Step 4."""
    from dashboard import api as dapi
    captured = {}
    def fake_smtp(to, subj, body): captured.update(body=body)
    monkeypatch.setattr(dapi, "smtp_send", fake_smtp)
    monkeypatch.setattr(dapi.state_registry, "get_alert_settings",
                         lambda **k: {"channels": {"email": {"enabled": True,
                                                              "destination": "ops@example.com"}}})
    monkeypatch.setattr(dapi.state_registry, "record_alert_delivery",
                         lambda *a, **k: None)
    summary = _make_summary(
        proposed=["Friday 12:00"],
        prev_proposed=["tomorrow evening 17:00", "Monday morning 11:00"],
        latest_msg="i changed my mind, i wanna change it to friday 12:00")
    dapi._fire_escalation_alerts(
        escalation_id=1, customer_name="Calvin", channel="whatsapp",
        subject="ignored", mode="soft", summary_dict=summary, is_update=True)
    assert ("Previously proposed (now retracted): "
            "tomorrow evening 17:00, Monday morning 11:00") in captured["body"]


def test_re_escalation_with_changed_summary_fires_updated_alert(monkeypatch):
    """Brief 239: real round-trip — call create_pending_notification twice
    for the same customer; second call has a materially-different summary;
    second alert fires with is_update=True and the new proposedTimes."""
    from shared import state_registry
    summaries = iter([
        _make_summary(proposed=["Thursday 17:00", "Monday 11:00"],
                       latest_msg="i can do thu 17 or mon 11"),
        _make_summary(proposed=["Friday 12:00"],
                       prev_proposed=["Thursday 17:00", "Monday 11:00"],
                       latest_msg="i changed my mind, i wanna change it to friday 12:00"),
    ])
    monkeypatch.setattr(state_registry, "_summary_dispatcher",
                         lambda *a, **k: next(summaries))
    fired = []
    def fake_dispatch(eid, name, ch, subj, mode=None, summary_dict=None, is_update=False):
        fired.append({"is_update": is_update,
                       "subject": subj,
                       "summary": summary_dict})
    monkeypatch.setattr(state_registry, "_alert_dispatcher", fake_dispatch)
    cid = "test-friday-conv"
    state_registry.create_pending_notification(
        "escalation", "whatsapp", cid, "Calvin", "Marina escalated", "...",
        mode="soft")
    state_registry.create_pending_notification(
        "escalation", "whatsapp", cid, "Calvin", "Marina escalated", "...",
        mode="soft")
    assert len(fired) == 2
    assert fired[0]["is_update"] is False
    assert fired[1]["is_update"] is True
    assert (fired[1]["summary"]["extractedDetails"]["proposedTimes"]
            == ["Friday 12:00"])
    assert (fired[1]["summary"]["extractedDetails"]["previousProposedTimes"]
            == ["Thursday 17:00", "Monday 11:00"])


def test_re_escalation_with_unchanged_summary_suppresses_alert(monkeypatch):
    """Brief 239: when the regenerated summary is materially identical to
    the previous one, no follow-up alert fires — only the first one."""
    from shared import state_registry
    same = _make_summary(proposed=["Friday 12:00"],
                          latest_msg="i wanna change it to friday 12:00")
    monkeypatch.setattr(state_registry, "_summary_dispatcher",
                         lambda *a, **k: dict(same))
    fired = []
    monkeypatch.setattr(state_registry, "_alert_dispatcher",
                         lambda *a, **k: fired.append((a, k)))
    cid = "test-noop-conv"
    state_registry.create_pending_notification(
        "escalation", "whatsapp", cid, "Calvin", "subj1", "body1",
        mode="soft")
    state_registry.create_pending_notification(
        "escalation", "whatsapp", cid, "Calvin", "subj2", "body2",
        mode="soft")
    assert len(fired) == 1


def test_mode_set_at_create_persists_and_renders(monkeypatch):
    """Brief 239: passing mode='soft' to create_pending_notification puts
    mode='soft' on the row; the alert dispatcher receives mode='soft';
    the rich body says 'Mode: Agent needs help' (not '(unset)')."""
    from shared import state_registry
    from dashboard import api as dapi
    monkeypatch.setattr(state_registry, "_summary_dispatcher",
                         lambda *a, **k: _make_summary(latest_msg="hi"))
    captured = {}
    def fake_smtp(to, subj, body): captured.update(body=body)
    monkeypatch.setattr(dapi, "smtp_send", fake_smtp)
    monkeypatch.setattr(dapi.state_registry, "get_alert_settings",
                         lambda **k: {"channels": {"email": {"enabled": True,
                                                              "destination": "ops@example.com"}}})
    monkeypatch.setattr(dapi.state_registry, "record_alert_delivery",
                         lambda *a, **k: None)
    cid = "test-mode-conv"
    rid = state_registry.create_pending_notification(
        "escalation", "whatsapp", cid, "Calvin", "subj", "body", mode="soft")
    conn = state_registry._get_conn()
    row = conn.execute("SELECT mode FROM pending_notifications WHERE id=?",
                        (rid,)).fetchone()
    conn.close()
    assert row[0] == "soft"
    assert "Mode: Agent needs help" in captured.get("body", "")
```

Seven tests. All exercise real branches (rich body, fallback body, specific subject, previousProposedTimes consumption, re-escalation update with changed summary, suppression on unchanged summary, mode persistence). Each test mocks only at boundaries (`smtp_send`, `_summary_dispatcher`, `record_alert_delivery`, `get_alert_settings`).

**Regression baseline:** 1022 passing / 0 failures (per Brief 238 system_state). After this brief: **1029 passing / 0 failures** (1022 + 7 new).

## Success Condition

After execution:

1. `python3 -m pytest wtyj/tests/social/test_217_alert_delivery.py -q` passes (existing + 7 new).
2. `python3 -m pytest wtyj/tests/ -q` reports 1029 passing / 0 failures.
3. `grep -nE "create_pending_notification\(\s*['\"]escalation['\"]" wtyj/agents/ -r` lists exactly 11 escalation call sites; running `grep -B1 -A6 ... | grep "mode="` against the same output shows all 11 have a mode kwarg.
4. `python3 -c "from dashboard.api import _build_alert_subject; print(_build_alert_subject('Calvin', None, False))"` prints `New escalation: Calvin` (legacy fallback).
5. `python3 -c "from dashboard.api import _build_alert_subject; s={'extractedDetails':{'intent':'scheduling','proposedTimes':['Friday 12:00']}}; print(_build_alert_subject('Calvin', s, True))"` prints `Updated escalation: Calvin changed meeting time to Friday 12:00`.
6. After deploy, an inbound test message that triggers `[ESCALATE]` in unboks's container produces a `pending_notifications` row with `mode='soft'` (verifiable via `docker exec wtyj-unboks sqlite3 /app/data/state_registry.db "SELECT id, mode, customer_name, escalation_summary IS NOT NULL FROM pending_notifications ORDER BY id DESC LIMIT 1"`).
7. CI green; all 4 containers healthy post-deploy; `tenant_guard.is_account_allowed` still importable in unboks/bluemarlin (Brief 238 not regressed).

## Rollback

Code-only rollback: `git revert <this brief's source commit>` and push. The pipeline auto-deploys the revert (~90 seconds + per-tenant restart). All existing `pending_notifications` rows keep their `mode` and `escalation_summary` columns regardless of revert (no destructive schema change — both columns were ALTER TABLE ADD COLUMN long before this brief).

If only the alert dispatcher is misbehaving in production (e.g., rich body breaks for a particular tenant whose `client.json` lacks `business.name`), set `_alert_dispatcher` to a no-op via a one-line monkey-patch in `dashboard/api.py` (`state_registry.set_alert_dispatcher(lambda *a, **k: None)`) and `docker compose restart wtyj-unboks`. Escalations still create rows + dashboard summaries; only the email goes silent until a fix ships.

The summary dispatcher reordering in Step 3 does not change the persisted JSON shape — `escalation_summary` rows from before this brief continue to render unchanged on the dashboard. New rows gain optional `latestCustomerMessage` and `extractedDetails.previousProposedTimes`; SR's frontend's existing fallback parser already handles missing fields per Brief 227's contract.
