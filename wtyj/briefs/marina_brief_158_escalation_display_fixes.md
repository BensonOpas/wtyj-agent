# BRIEF 158 — Escalation display fixes (PHONE "69" + semi missing body + REASON shows customer name)

**Status:** Draft (rewritten v2 — frontend-only approach after round-1 reviewer flagged the chat log timing problem)
**Files:**
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Escalations.tsx` (`parseEscalationBody`, REASON rendering, conversation block rendering)

**Depends on:** Brief 157 (Marina escalation wording)
**Blocks:** Brief 159 (relay end-to-end repair) — needs the dashboard to actually show the question and the conversation before we can debug the relay flow

---

## Context

User reported 3 dashboard escalation bugs from a real test session (screenshots provided):

### Bug 1 — `PHONE: 69` on every escalation card

Both semi and full escalation detail views show `PHONE: 69`. The customer is on WhatsApp via Zernio.

**Root cause:** `phone` variable in `social_agent.py` is the Zernio conversation_id (e.g. `69d41ae77d2c605d08114697`), NOT a phone number. The relay/escalation body strings contain the line `WhatsApp: 69d41ae77d2c605d08114697`. The dashboard's `parseEscalationBody` regex at `Escalations.tsx:124` is `body.match(/WhatsApp:\s*(\d+)/)` — `(\d+)` captures only leading digits and stops at the first non-digit (`d`), so it captures `"69"`.

### Bug 2 — Semi escalation has NO body / conversation log

Comparing the two screenshots:
- **Full escalation detail page** shows the full CONVERSATION section with `[USER / ASSISTANT]` message log
- **Semi escalation detail page** has CUSTOMER + PHONE + REASON fields and a "Mark Resolved" button — and **nothing else**. No conversation, no question, nothing for the operator to see what they need to answer.

**Root cause:** the dashboard's `parseEscalationBody` only extracts `email`, `phone`, and `chatLog` (the section between `=== CHAT LOG ===` and end of body). The relay body in `social_agent.py:542-552` has NO `=== CHAT LOG ===` section — but it DOES have `Their question: {relay_question}`, `Booking context:`, and `INSTRUCTIONS:` lines that contain ALL the info the operator needs. The dashboard just doesn't render any of it because the conversation block is gated behind `{parsed.chatLog && (...)}`.

The relay body already has everything an operator needs for a relay — we just need to display it.

### Bug 3 — `REASON` field shows the customer name on semi escalation

Compare the screenshots:
- **Semi escalation:** REASON = `"Calvin Adamus"` (the customer's name — wrong)
- **Full escalation:** REASON = `"Customer provided email for escalation; complaint involves alleged crew assault and refund request..."` (the actual reason — correct)

**Root cause:** the dashboard's `cleanSubject` function (`Escalations.tsx:134-138`) splits the subject on `" - "` and takes the last segment as the "reason":

```js
const cleanSubject = (subject: string): string => {
  const parts = subject.split(" - ");
  const intent = parts[parts.length - 1]?.trim() || subject;
  return intent.charAt(0).toUpperCase() + intent.slice(1);
};
```

The relay subject format is `[RELAY-{token}] {ref} - {customer_name}` (only 2 segments after the `]`), so `cleanSubject` returns `"Calvin Adamus"` (the customer name). The full escalation subject has 3 segments (`[ESCALATION] ref - name (WhatsApp:...) - reason`), so it correctly returns the reason.

The relay body has `Their question: {relay_question}` on its own line — that's the actual reason and we can parse it directly.

---

## Why This Approach

### Frontend-only

The relay body already has all the info the operator needs (`Their question:`, `Booking context:`, `INSTRUCTIONS:`). The dashboard just isn't extracting or displaying it. Three small frontend changes solve all three bugs without touching the backend at all.

### Why NOT add `=== CHAT LOG ===` to the backend body (the v1 approach, abandoned)

Round 1 reviewer flagged that I was about to introduce a backend change that would break in a subtle way:

1. The plan was to call `state_registry.wa_get_full_history(phone, limit=20)` inside the relay creation block at `social_agent.py:537` to build a chat log.
2. **But** the customer's CURRENT message (the one that triggered the escalation) is NOT in `wa_get_full_history(phone)` at that point. Both code paths (legacy Meta at `webhook_server.py:215` and Zernio at `webhook_server.py:177-183`) call `wa_store_message` / `dm_store_message` AFTER `handle_incoming_whatsapp_message` returns. That ordering exists for a reason: Brief 089 explicitly moved storage to after-processing to avoid duplicating the current message in Claude's prompt context.
3. So my backend chat log would always be missing the customer's current question — the operator would see prior history but not the actual question that needs answering.

Meanwhile, the question is ALREADY in the body as `Their question: {relay_question}`. Parsing that line on the frontend gives us the question without any backend churn.

### Why NOT change the backend subject format to add the question

Same logic: the question is already in the body. We don't need to put it in two places. The frontend can pull it from the body and use it for the REASON field directly.

### Out of scope

- **Brief 159 — relay end-to-end repair.** Brief 158 makes the dashboard SHOW the relay question + conversation. Brief 159 fixes the operator-answer → Marina → customer flow. Different concern, different files.
- **Adding chat history to relay bodies on the backend.** Even if we wanted this, the timing problem (current message not in history) means the backend approach gives degraded info. Out of scope. If a future brief wants this, the right place to inject the current message is in `webhook_server.py` BEFORE calling the orchestrator (with the documented duplicate-prompt-context tradeoff that Brief 089 navigated).
- **Renaming the `Phone` field label** for non-phone identifiers — cosmetic, doesn't fix any bug.
- **Per-channel field labels** (e.g. `WhatsApp ID` vs `Email`) — over-engineering.
- **Migrating existing escalation rows** — DB was wiped this morning; no historical relay data to backfill.

---

## Source Material

### Current `parseEscalationBody` (Escalations.tsx:122-132)

```ts
const parseEscalationBody = (body: string) => {
  const emailMatch = body.match(/Email:\s*(\S+@\S+)/i);
  const phoneMatch = body.match(/WhatsApp:\s*(\d+)/);
  const chatLogStart = body.indexOf("=== CHAT LOG ===");
  const chatLog = chatLogStart >= 0 ? body.slice(chatLogStart + 16).trim() : "";
  return {
    email: emailMatch?.[1] || "",
    phone: phoneMatch?.[1] || "",
    chatLog,
  };
};
```

### Current `cleanSubject` (Escalations.tsx:134-138)

```ts
const cleanSubject = (subject: string): string => {
  const parts = subject.split(" - ");
  const intent = parts[parts.length - 1]?.trim() || subject;
  return intent.charAt(0).toUpperCase() + intent.slice(1);
};
```

NOT changing this — leaving it for full escalations which work correctly.

### Current escalation detail rendering (Escalations.tsx:502-538)

```tsx
<div className="space-y-4 flex-1 overflow-y-auto min-h-0">
  {(() => {
    const parsed = parseEscalationBody(selected.body);
    return (
      <>
        <div className="flex flex-wrap gap-3">
          <div>...Customer: {selected.customer_name}</div>
          {parsed.email && (<div>...Email: {parsed.email}</div>)}
          <div>...Phone: {parsed.phone || selected.customer_id}</div>
          <div>...Reason: {cleanSubject(selected.subject)}</div>
        </div>
        {parsed.chatLog && (
          <div>
            <h3>Conversation</h3>
            <pre>{parsed.chatLog}</pre>
          </div>
        )}
      </>
    );
  })()}
</div>
```

### Current `social_agent.py` semi-escalation body (lines 542-552) — read-only reference

```python
_alert_body = (
    f"Customer: {_cname} (WhatsApp: {phone})\n"
    f"Their question: {relay_question}\n\n"
    f"Booking context:\n"
    f"  Trip: {fields.get('service_key', '')} | "
    f"Date: {fields.get('date', '')} | "
    f"Guests: {fields.get('guests', '')}\n"
    f"  Ref: {_ref}\n\n"
    f"INSTRUCTIONS: Reply to this email with your answer.\n"
    f"Marina will relay it to the customer in her own words."
)
```

The `Their question: {relay_question}` line is the key — that's the data the frontend needs to extract.

### Current `email_poller.py` semi-escalation body (lines 969-979) — read-only reference

Same shape. Has `Their question: {relay_question}` on its own line. Same regex works for both.

### Existing tests — must remain green

- `test_077_relay_bridge.py::test_semi_inserts_pending_notification` (line 327) — substring check `"[RELAY-" in subject`. Frontend changes don't affect backend behavior; passes unchanged.
- `test_077_relay_bridge.py::test_relay_notification_uses_profile_name` (lines 192-211) — asserts `"Jan de Vries" in match[0]["subject"]` and `"Jan de Vries" in match[0]["body"]`. Frontend-only changes don't affect this; passes unchanged.

No backend tests are touched at all.

### `isSemi` helper (Escalations.tsx:120) — already exists

```ts
const isSemi = (type: string) => type === "relay" || type === "semi_escalation";
```

I'll reuse this for the conditional body rendering.

---

## Instructions

### Step 1 — Read the file before editing

`~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Escalations.tsx` lines 100-540 (covers the helper functions, the row renderer, and the detail page rendering).

### Step 2 — Update `parseEscalationBody` (Escalations.tsx:122-132)

Replace the function with:

```ts
const parseEscalationBody = (body: string) => {
  const emailMatch = body.match(/Email:\s*(\S+@\S+)/i);
  const phoneMatch = body.match(/WhatsApp:\s*(\S+)/);
  const questionMatch = body.match(/Their question:\s*(.+?)(?:\n|$)/);
  const chatLogStart = body.indexOf("=== CHAT LOG ===");
  const chatLog = chatLogStart >= 0 ? body.slice(chatLogStart + 16).trim() : "";
  return {
    email: emailMatch?.[1] || "",
    phone: phoneMatch?.[1] || "",
    question: questionMatch?.[1]?.trim() || "",
    chatLog,
  };
};
```

**Three additions:**
1. Phone regex changed from `(\d+)` to `(\S+)` — captures the full identifier (Zernio hex conversation_id, real phone, etc.) instead of just leading digits.
2. New `question` field — extracts the text after `Their question:` up to the next newline or end-of-string. Non-greedy match (`.+?`) so it stops at the first newline.
3. Returned object includes `question` alongside the existing `email`, `phone`, `chatLog`.

### Step 3 — Update REASON field rendering (around Escalations.tsx:522-525)

Find the existing REASON field block:

```tsx
<div className="flex-1 min-w-[200px] p-3 rounded-lg bg-muted/30 border border-border">
  <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Reason</p>
  <p className="text-sm font-medium text-foreground">{cleanSubject(selected.subject)}</p>
</div>
```

Replace the `<p>` line with:

```tsx
  <p className="text-sm font-medium text-foreground">{parsed.question || cleanSubject(selected.subject)}</p>
```

**Behavior:**
- For semi escalations (relay body has `Their question: ...`): displays the question
- For full escalations (no `Their question:` line, so `parsed.question` is empty): falls back to `cleanSubject(selected.subject)` which already works correctly

### Step 4 — Update conversation block rendering (around Escalations.tsx:527-534)

Find the existing conditional conversation block:

```tsx
{parsed.chatLog && (
  <div>
    <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Conversation</h3>
    <pre className="text-sm text-foreground/80 whitespace-pre-wrap leading-relaxed bg-muted/30 border border-border rounded-xl p-4 max-h-96 overflow-y-auto font-sans">
      {parsed.chatLog}
    </pre>
  </div>
)}
```

Replace with:

```tsx
{(parsed.chatLog || isSemi(selected.notification_type)) && (
  <div>
    <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
      {isSemi(selected.notification_type) ? "Relay Details" : "Conversation"}
    </h3>
    <pre className="text-sm text-foreground/80 whitespace-pre-wrap leading-relaxed bg-muted/30 border border-border rounded-xl p-4 max-h-96 overflow-y-auto font-sans">
      {isSemi(selected.notification_type) ? selected.body : parsed.chatLog}
    </pre>
  </div>
)}
```

**Behavior:**
- **Full escalation** (existing behavior): shows the chat log section extracted from the body, header reads "Conversation"
- **Semi escalation** (new behavior): shows the FULL raw body in the `<pre>` block, header reads "Relay Details". Operator sees `Customer: ...`, `Their question: ...`, `Booking context: ...`, `INSTRUCTIONS: ...` — every structured field the relay body contains.

**Why show the full body for semi instead of trying to parse out individual sections?** Lower complexity, more information visible. The relay body is short and structured — a `<pre>` block renders it cleanly. The operator gets ALL the info the backend put in the body, not just the parts the frontend knew to extract.

### Step 5 — Frontend typecheck

```bash
cd /Users/benson/Projects/wetakeyourjob-dashboard/artifacts/dashboard
pnpm typecheck 2>&1 | tail -20
```

Expected: same pre-existing errors as Brief 156/157 (`ContentPipeline.backup.tsx` + `Messages.tsx Conversation.channel`) and zero new errors. The changes are pure JSX/TS additions that build on existing patterns.

### Step 6 — No backend regression run needed

This brief touches ZERO backend code. The marina + social regression suite is unchanged from Brief 157's run (738 / 0). Skipping the run to save time. If you want to be extra safe, run it anyway — it's fast and idempotent.

### Step 7 — Commit + push (dashboard repo only)

```bash
# No backend commit — frontend-only brief

# Commit the brief markdown to backend repo for traceability
cd /Users/benson/Projects/bluemarlin-agent
git add wtyj/briefs/marina_brief_158_escalation_display_fixes.md
git commit -m "Brief 158 — escalation display fixes (frontend-only)"
git push

# Dashboard
cd ~/Projects/wetakeyourjob-dashboard
git add artifacts/dashboard/src/pages/Escalations.tsx
git commit -m "Brief 158 — escalation display fixes: phone regex, semi body, reason"
git push
```

### Step 8 — No VPS deploy needed

Backend code is unchanged. No image rebuild, no container restart. Replit will auto-deploy the dashboard frontend within ~2 min of the push.

### Step 9 — User-driven live test

User triggers a fresh semi escalation by sending Marina a question she can't answer (e.g. "is the boat wheelchair accessible?" — falls outside FAQ, requires crew confirmation). Confirm:

1. Marina replies "Let me check with the team and get back to you" (or similar warm acknowledgment)
2. A new semi escalation row appears in the dashboard escalations page
3. **PHONE field shows the full WhatsApp ID** (long hex like `69d41ae77d2c605d08114697`), NOT "69"
4. **REASON field shows the relay question** (e.g. "is the boat wheelchair accessible?"), NOT the customer name
5. **A "Relay Details" section appears** below the cards, showing the full body with `Their question:`, `Booking context:`, `INSTRUCTIONS:` etc.
6. (Out of scope for 158 — Brief 159 will fix the relay reply path)

Same drill for full escalation: send a complaint, confirm PHONE shows full ID and the existing CONVERSATION section still renders correctly.

Same drill for email channel: send a question to BlueMarlin's polled inbox that triggers a relay, confirm the dashboard escalation row shows the question in REASON and the relay details below.

---

## Tests

No new automated tests. The dashboard repo has no test infrastructure for `Escalations.tsx` rendering. Manual visual verification per Step 9 is the test plan.

The backend regression suite is untouched because this brief makes zero backend changes.

---

## Success Condition

**One sentence:** A fresh semi escalation triggered by a customer question shows the customer's full WhatsApp identifier in the PHONE field, the relay question in the REASON field, and the full structured relay body in the "Relay Details" section on the dashboard escalation detail page — and the existing full escalation display continues to render correctly.

---

## Rollback

```bash
cd ~/Projects/wetakeyourjob-dashboard
git revert <commit-sha>
git push
```

Replit auto-deploys the revert. Backend is untouched, no VPS rollback needed. The change is JSX + one regex character, fully clean revert.

---

## Risks I want flagged before execution

1. **`Their question:` line might contain unexpected content.** If the `relay_question` ever contains a literal newline (Marina writes `"What about\ndietary?"`), the regex `(.+?)(?:\n|$)` stops at the first newline and only captures the first line. Acceptable — the full question is still visible in the relay body block below.
2. **Email-channel escalation PHONE fallback to email.** Pre-existing behavior, NOT changed by Brief 158. Email semi escalations will still show the customer's email in the PHONE field because the body has no `WhatsApp:` line, the regex returns empty, and the dashboard falls back to `customer_id` which IS the email. Acknowledged as accepted; the PHONE label is misleading on email-channel escalations regardless. Out of scope.
3. **The "Relay Details" header text** could be more specific. Open to suggestions — "Operator Brief", "Question Context", etc. Default = "Relay Details" because it's clear without being too techy.
4. **Frontend regex for the question is fragile to format changes.** If a future brief changes the relay body to use `Question:` instead of `Their question:`, the parser breaks. Mitigated by: this regex is in ONE place (`parseEscalationBody`), easy to update, and Brief 158 also doesn't propose changing the backend body format anytime soon.
