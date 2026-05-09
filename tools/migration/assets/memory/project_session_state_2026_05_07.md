---
name: Session state 2026-05-07
description: End-of-session snapshot. Briefs 209-218 + hotfixes shipped. Tier 2 of SR's product contract mostly complete. 998 tests passing. All 4 containers healthy. 216 + 219 + 220 still queued.
type: project
originSessionId: a8da0e6a-d80e-4538-ae7c-11b06ae6beb0
---
End-of-session snapshot taken 2026-05-07 evening (continuing from 2026-05-06 session).

## Current state at end of session

- **All 4 production containers healthy.** Ports 8001 (bluemarlin), 8002 (adamus), 8003 (consultadespertares), 8004 (unboks). Plus staging on 9001.
- **998 tests passing / 0 failures.** Up from 937 at start of yesterday's session.
- **Latest commit on main:** `b68ea34` (Brief 217 post-exec docs). Source latest: `91eff7b` (Brief 217). Below that: `6c6e6a7` Brief 218, `2e36547` /guidance hotfix, `68c0436` Brief 215, `7f3f856` Brief 214, `2511a65` Brief 213, `4129cc2` Brief 212, `380a059` Brief 211, `c2f6bd5` Brief 210 hotfix, `a84efc3` Brief 210, `190e690` Brief 209.
- **CI pipeline green throughout.** No deploys rolled back. No regressions.

## Briefs shipped this overnight stretch (in order)

- **Brief 209** — Calvin → Marina rebrand for unboks (config/prompt only). All Calvin references in client.json flipped to Marina; agent_internal_id renamed calvin-csa → marina-unboks. New SCHEDULING/ACTIVATION DIRECTIVE block in freeform_notes per SR's spec.
- **Brief 210** — Email reply-from-dashboard for hard escalations. POST /escalations/:id/reply now handles channel="email" via smtp_send + email_thread state append. Plus a `[FIX]` for the `{message}` field name SR's frontend uses.
- **Brief 211** — Dashboard contract fields. `escalated`/`escalationResolved`/`escalationMode`/`aiMuted` derived from existing storage. Added routable `phone` field to /escalations email rows so clicking opens the actual thread.
- **Brief 212** — Endpoint polish. /learning aliases, raw-array body for PUT /schedule/slots, new POST /ai-editor Claude proxy for SR's translate/style/fix composer.
- **Brief 213** — Escalation control surface. Mode + takeover + handback + ai_muted enforcement at all 4 customer-message ingestion paths (DM IG/FB, Zernio-WhatsApp, Meta-WhatsApp, email_poller). Brief-reviewer FAILed round 1 (caught the WhatsApp-coverage gap), PASS round 2.
- **Brief 214** — POST /escalations/:id/guidance for soft mode. Operator coaches Marina, Marina relays in her voice. Hard mode returns 409.
- **Brief 215** — Operator-answer-as-approved-learning. New escalation_learnings table + 5 helpers + auto-creation hooks at 4 sites + 3 endpoints. Repointed /learning from content_learnings (Brief 212 alias) to escalation_learnings.
- **`[FIX]` post-Brief-218** (commit `2e36547`) — `/guidance` accepts the `{guidance}` field name SR's frontend uses (was 400-ing because the model only knew `{message}` and `{answer}`).
- **Brief 218** — Email forward + delete actions. POST /messages/conversations/:id/email/forward (smtp_send the latest customer message to a new recipient list with optional operator note) + /email/delete (mark thread `flags.deleted=True`, filter from inbox). Provider-side IMAP MOVE deferred.
- **Brief 217** — Escalation alert delivery. Two new tables (`alert_settings` singleton + `alert_deliveries` audit log). When a customer triggers an escalation, backend pings the operator on configured channels (email + WhatsApp v1). Telegram + Messenger return "skipped: provider not configured". Brief-reviewer FAILed twice (relay-row alert spam blocker round 1; dispatcher registration NameError round 2). Patch+ship per Benson direction.

## What's actively live now

- **Marina rebrand for unboks live.** All outgoing messages signed Marina; SCHEDULING directive shapes activation-call replies.
- **Email reply from dashboard works** (POST /reply with channel="email"). SR's "Reply to customer" button on email rows is real.
- **Soft escalation flow works** (POST /guidance, since `[FIX]` `2e36547`). SR's "Send to Marina" button is real.
- **Soft/hard mode + takeover + handback persist.** SR's mode toggle UI fully wired.
- **AI muted on takeover** is enforced at every customer-message ingestion path (4 sites covered).
- **Every operator answer creates an approved learning entry** in escalation_learnings.
- **Email forward + delete from dashboard** work. Delete is local-only (provider-side IMAP MOVE deferred).
- **Escalation alerts** fire to email + WhatsApp on new escalations. Operator's WhatsApp goes to their CONFIGURED phone, not the business WhatsApp.
- **Brief 211's contract fields + Brief 212's endpoint polish + AI Editor + /learning aliases** all live from earlier in the same session.

## What's still queued from SR's product contract

1. **Brief 216 — Your Info / Settings** (held for SR conversation). Path A confirmed: GET/PUT over whitelisted client.json fields. Two flavors of "Your Info Updates": permanent (manually removable) + scheduled (auto-expires after end_date, like a Valentine's promo). Marina reads both at prompt build (client.json already, plus new info_updates table).
2. **Brief 219 — Marina USES the approved learnings.** The deferred read+inject from Brief 215. Touches `marina_agent._build_system_prompt` (the most sensitive file in the project). New helper `get_approved_learnings_for_prompt(channel, limit=20)` + new "APPROVED ANSWERS" block in the prompt template. Behind a feature flag in client.json; default-off, enable per-tenant after eyeball testing.
3. **Brief 220 — Block conversation** (NOT block Marina — SR confirmed it's the ignore-it-entirely flavor). Same semantic as `ignored_phones` from Brief 208 but per-conversation runtime state (not client.json config). Webhook drops messages before storage. New endpoint POST /messages/conversations/:id/block. Operator sees a "Blocked conversations" management list with unblock buttons.

## Process lessons from the night (already in marina_lessons.md)

- **Pluggable callback for circular import avoidance.** state_registry has `_alert_dispatcher = None` + `set_alert_dispatcher(fn)` setter; dashboard.api registers the callback at module-load time. Reusable pattern for storage-layer-calls-application-layer needs.
- **INSERT OR REPLACE on fixed id=1 for singleton tables.** Atomic upsert without DELETE-then-INSERT race window.
- **When hooking into a shared chokepoint, grep ALL its call sites first.** Brief 217 round 1 fail: I hooked `create_pending_notification` unconditionally; reviewer caught that relay rows would spam alerts.
- **Module-load registration ordering matters.** Brief 217 round 2 fail: `set_alert_dispatcher(fn)` placed at top of module before `fn` was defined → NameError. Place registration immediately adjacent to the function definition.
- **Test infrastructure file changes need to be in the brief's Files header.** Brief 217 added an autouse fixture in `wtyj/tests/social/conftest.py` for test isolation; that file was not in the declared list. Output-reviewer flagged as scope creep with mitigating context.
- **/guidance soft-mode flow uses RAW operator text as humanAnswer, not Marina's reformulation.** Both Brief 214 (which initially had this design) and Brief 215 (which auto-creates learnings) anchor on this — the operator's intent is the canonical knowledge to remember, not Marina's polish.

## Two minor open issues (informational, not blocking)

1. **Calvin@gaimin.io escalation row id=1 still has status="sent"** (not "replied"). Was created during E2E testing on 2026-05-06. Could stay or be manually marked resolved.
2. **Escalation row id=2 has customer_id="hello@unboks.org"** (our own inbox). Marina escalated and stored OUR address as the contact. Probably a bug in escalation creation when the inbound is from our own inbox. Worth a fix if it recurs in production.

## Resume path on next session

1. Read this file + `project_open_work.md` + `wtyj/briefs/system_state.md` (latest brief outcomes).
2. Brief 216 needs SR's input on "Your Info Updates" UI flavors (permanent + scheduled).
3. Brief 219 (Marina uses learnings) and Brief 220 (block conversation) are well-specified and ready to execute when Benson says go.
4. SR's full product contract is mostly done — what remains is the read+inject half of learning + Your Info + the block-conversation feature.
