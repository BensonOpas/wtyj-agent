# OUTPUT 158 — Escalation display fixes

## What was done

Three edits to a single frontend file: `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/pages/Escalations.tsx`.

### Edit 1 — `parseEscalationBody` (lines 122-133)

```diff
 const parseEscalationBody = (body: string) => {
   const emailMatch = body.match(/Email:\s*(\S+@\S+)/i);
-  const phoneMatch = body.match(/WhatsApp:\s*(\d+)/);
+  const phoneMatch = body.match(/WhatsApp:\s*(\S+)/);
+  const questionMatch = body.match(/Their question:\s*(.+?)(?:\n|$)/);
   const chatLogStart = body.indexOf("=== CHAT LOG ===");
   const chatLog = chatLogStart >= 0 ? body.slice(chatLogStart + 16).trim() : "";
   return {
     email: emailMatch?.[1] || "",
     phone: phoneMatch?.[1] || "",
+    question: questionMatch?.[1]?.trim() || "",
     chatLog,
   };
 };
```

### Edit 2 — REASON field rendering (line 524)

```diff
-<p className="text-sm font-medium text-foreground">{cleanSubject(selected.subject)}</p>
+<p className="text-sm font-medium text-foreground">{parsed.question || cleanSubject(selected.subject)}</p>
```

### Edit 3 — Conversation block rendering (lines 528-535)

```diff
-{parsed.chatLog && (
+{(parsed.chatLog || isSemi(selected.notification_type)) && (
   <div>
-    <h3>Conversation</h3>
+    <h3>{isSemi(selected.notification_type) ? "Relay Details" : "Conversation"}</h3>
     <pre>
-      {parsed.chatLog}
+      {isSemi(selected.notification_type) ? selected.body : parsed.chatLog}
     </pre>
   </div>
 )}
```

### Backend: NO changes

Brief 158 v1 originally proposed backend changes to `social_agent.py` and `email_poller.py` to add chat log markers to relay bodies. Round-1 reviewer flagged that the customer's CURRENT message wouldn't be in `wa_get_full_history` at the relay creation point because both code paths (legacy Meta and Zernio) store the user message AFTER `handle_incoming_whatsapp_message` returns (per Brief 089's intentional ordering to avoid duplicating in Claude's prompt context).

I rewrote the brief to a frontend-only approach that pulls the question from the existing `Their question:` line in the relay body. Backend code is untouched. Zero risk of regression in the orchestrator pipeline.

## Test results

**No backend tests run** — backend is untouched, regression suite would be a no-op.

**Frontend typecheck:**

```
$ pnpm typecheck
src/pages/ContentPipeline.backup.tsx(112,9): pre-existing
src/pages/Messages.tsx (12 errors): pre-existing — Conversation type missing `channel`
```

**Zero new TypeScript errors** introduced by Brief 158. Same pre-existing-error baseline as Brief 156/157.

## Live deploy verification

**No VPS deploy needed.** Backend container code is unchanged.

Replit auto-pulls the dashboard from the `master` branch on push. The dashboard repo push went through (`59175f6`); Replit will redeploy within ~2 minutes.

## Bugs fixed

### Bug 1 — `PHONE: 69` truncation (FIXED)

**Root cause:** `body.match(/WhatsApp:\s*(\d+)/)` captured only leading digits of the Zernio conversation_id `69d41ae77d2c605d08114697`, stopping at the `d`.

**Fix:** changed `(\d+)` to `(\S+)`. Now captures the full identifier whatever its shape — hex conversation_ids, real phone numbers, future identifier formats. Verified by reading the new regex and tracing it against the actual body string.

### Bug 2 — Semi escalation has no body (FIXED)

**Root cause:** the dashboard's conversation section was conditionally rendered behind `{parsed.chatLog && (...)}`. The relay body has no `=== CHAT LOG ===` marker, so `parsed.chatLog` is empty, so the entire section was hidden — even though the relay body contains `Their question:`, `Booking context:`, and `INSTRUCTIONS:` (everything an operator needs).

**Fix:** the conditional now also renders for semi escalations (`isSemi(selected.notification_type)`), and the body content for semi is the full raw `selected.body` rendered in a `<pre>` block under a "Relay Details" header. The operator now sees ALL the structured fields the relay body contains.

### Bug 3 — REASON shows customer name on semi (FIXED)

**Root cause:** `cleanSubject(subject)` splits on `" - "` and takes the last segment. The relay subject `[RELAY-token] NO-REF - Calvin Adamus` only has 2 segments after the `]`, so the last segment is the customer name.

**Fix:** the new `parsed.question` field is extracted from the `Their question:` line in the body via `/Their question:\s*(.+?)(?:\n|$)/`. The REASON field now reads `parsed.question || cleanSubject(selected.subject)` — semi shows the question, full falls back to cleanSubject (which already works for full).

## Unexpected findings

### 1. Round-1 reviewer surfaced a chat log timing bug that killed the v1 backend approach

The original Brief 158 v1 proposed adding `=== CHAT LOG ===` to the relay body on the backend so the dashboard's existing chat log extraction would work. The reviewer's "executor sanity check" item caught me: the customer's CURRENT message (the one that triggered the relay) is NOT in `wa_get_full_history(phone)` when the relay creation code runs.

Both code paths confirm this:
- Legacy Meta: `webhook_server.py:215` calls `wa_store_message(phone, "user", ...)` AFTER `handle_incoming_whatsapp_message` returns
- Zernio: `webhook_server.py:177-183` calls `dm_store_message` AFTER `handle_incoming_whatsapp_message` returns (note: different table!)

This ordering exists for a reason — Brief 089 explicitly moved storage to after-processing to avoid duplicating the current message in Claude's prompt context (the message would appear once in CONVERSATION HISTORY and once in INBOUND MESSAGE if stored before).

If I had executed v1, the chat log on relays would silently miss the most important message — the one the operator needs to answer. The frontend approach sidesteps this entirely because the `Their question: {relay_question}` line is constructed from `result.get("relay_question")` which IS the current question.

### 2. The Zernio path uses `dm_store_message` not `wa_store_message`

Discovered while tracing the chat log timing. Zernio WhatsApp messages get stored in a different table than legacy Meta WhatsApp. This means `wa_get_full_history(phone)` would return EMPTY for Zernio-mediated WhatsApp customers (since their messages live in the dm_messages table).

This is a much bigger latent issue: the FULL escalation chat log construction at `social_agent.py:614-624` calls `wa_get_history(phone)` which won't return anything for Zernio customers. So FULL escalations from Zernio WhatsApp also have empty chat logs in their bodies.

The user's screenshots happen to show a full escalation that DOES have a conversation visible — let me assume that's because the test conversation was on the legacy Meta path, OR the chat log section is empty but the dashboard still renders the section header. Worth investigating in a future brief, but **out of scope for Brief 158**.

This finding should be flagged in the Brief 159 (relay repair) research phase — Brief 159 may need to address the same Zernio/Meta history table mismatch.

### 3. `isSemi` helper already existed

`Escalations.tsx:120` already has `const isSemi = (type: string) => type === "relay" || type === "semi_escalation"`. I reused it for the conditional body rendering. No new helper needed.

### 4. Brief 158 was the smallest brief of the session

Three frontend edits, one file, zero backend changes, zero deploy. ~5 minutes brief→ship including the v1 → v2 rewrite. The reviewer's "executor sanity check" recommendation in round 1 saved a significant amount of execution time and a likely production bug.

## Files modified

| Repo | File | Change |
|------|------|--------|
| dash | `artifacts/dashboard/src/pages/Escalations.tsx` | parseEscalationBody (regex + question), REASON rendering, conversation block rendering |
| wtyj | `wtyj/briefs/marina_brief_158_*.md` | new brief file (v2 rewrite) |

## Commits

- Backend (brief file only): `6b11402` on `main`
- Dashboard (the actual fix): `59175f6` on `master`

## Next

**Brief 159 — Relay end-to-end repair** (Issue 5 from the user's original list). The operator-answer → Marina → customer relay flow is broken. Now that the dashboard correctly shows the relay question (Brief 158), we can debug the answer path. Brief 159 will need to also investigate the Zernio/Meta chat log table mismatch surfaced in Finding #2.

## Live verification pending

Brief 158 needs one user-driven test to confirm the dashboard renders correctly:

1. Trigger a fresh semi escalation by sending Marina a question she can't answer (e.g. "is the boat wheelchair accessible?", "do you have wifi onboard?")
2. Open the dashboard → Escalations → click the new semi escalation
3. **PHONE field** should show the full WhatsApp identifier (long hex), NOT "69"
4. **REASON field** should show the question, NOT the customer name
5. **"Relay Details" section** below the cards should show `Customer:`, `Their question:`, `Booking context:`, `INSTRUCTIONS:`
6. (Existing FULL escalation behavior should be UNCHANGED — verify by clicking an old full escalation if any exist)
