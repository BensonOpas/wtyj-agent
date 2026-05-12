# OUTPUT 263 — Operator-approved learnings extension

## What was done

P1 for issue #32. Calvin's spec: Agent must not auto-learn from every operator reply; operator must explicitly approve, edit, or dismiss a suggested learning. Pre-emptive grep caught Brief 215 era had already shipped the foundation (`escalation_learnings` table at `state_registry.py:449`, `/learning` endpoint family at `dashboard/api.py:419-445`, prompt-path integration at `get_approved_learnings_for_prompt` line 4220). Brief 263 closes the 4 surface gaps Calvin's spec called out: PATCH endpoint, dismiss endpoint, audit columns (`approved_at` / `dismissed_at` / `approved_by`), and `/escalation-learnings/*` alias paths with Calvin's status-term vocabulary (`pending` / `approved` / `dismissed` mapping to internal `suggested` / `approved` / `deleted`).

The deeper product decision — "stop auto-learning from operator replies" (which would mean changing `save_escalation_learning`'s default from `'approved'` to `'suggested'`) — is honestly deferred to a follow-up brief. Brief 263 ships the operator-approval flow Calvin needs to verify the UX works end-to-end before flipping the default for existing tenants. Documented openly in the brief's Context section and lessons.

## Storage / data model

- **`escalation_learnings` table** (Brief 215 era) — schema extended with three idempotent ALTER TABLE additions for the Brief 263 audit fields:
  - `approved_at TEXT` — populated only on `status='approved'` transition.
  - `dismissed_at TEXT` — populated only on `status='deleted'` transition (soft-reject via the new `/dismiss` endpoint; legacy `DELETE /learning/{id}` hard-removes the row).
  - `approved_by TEXT` — operator label captured from POST body on the new `/approve` endpoint.
- Statuses remain `suggested | approved | saved | deleted` at storage. The API surface maps to Calvin's `pending | approved | dismissed` vocabulary. The `saved` status from Brief 215 surfaces as `approved` externally (frontend doesn't need to know about the saved/approved distinction).
- New helper `create_pending_learning` inserts with status='suggested', `ai_may_use_automatically=0`. Approve transition flips both `status='approved'` AND `ai_may_use_automatically=1` so the prompt-path filter picks it up.
- New helper `edit_escalation_learning_text` rejects edits on any non-suggested row (text is frozen once operator approves/dismisses).

## Endpoint paths

| Path | Method | Purpose | Body | Response |
|---|---|---|---|---|
| `/escalation-learnings` | GET | List learnings, filter by `?status=pending\|approved\|dismissed` | — | `[<row in spec shape>]` |
| `/escalations/{id}/suggest-learning` | POST | Create new pending suggestion | `{suggestedText, sourceQuestion?, channel?, operator?}` | `<row in spec shape>` |
| `/escalation-learnings/{id}` | PATCH | Edit text while pending | `{suggestedText}` | `<row>` (409 if already approved/dismissed) |
| `/escalation-learnings/{id}/approve` | POST | Approve, record audit | `{operator?}` | `<row>` |
| `/escalation-learnings/{id}/dismiss` | POST | Soft-reject | — | `<row>` |

Legacy `/learning/*` endpoints (Brief 215) preserved unchanged for backward compat.

## Request/response shape

```ts
interface EscalationLearning {
  id: string;          // stringified row id
  escalationId: string; // mapped from conversation_id (closest existing field)
  status: "pending" | "approved" | "dismissed";
  suggestedText: string;
  approvedText: string | null;  // = suggestedText when status=approved, else null
  createdAt: string;            // ISO
  updatedAt: string;            // ISO
  approvedAt: string | null;    // populated on approve transition
  dismissedAt: string | null;   // populated on dismiss transition
  operator: string | null;      // approved_by if set, else created_by
}
```

## How approved learnings enter Agent prompt path

Unchanged from Brief 215 / 219 / 230: `get_approved_learnings_for_prompt(channel, limit)` at `state_registry.py:4220` filters `status IN ('approved', 'saved') AND ai_may_use_automatically = 1`. Suggested (pending) rows are excluded by the status filter; dismissed rows are excluded by both filters (deleted status + ai_may_use=0). The new approve endpoint flips ai_may_use_automatically=1, so an operator-approved row becomes prompt-eligible immediately on the next prompt build.

Gating remains via `client.json::features.approved_learnings_in_prompt` (default false). Tenants must opt in.

## Validation / safety

- Brief 263 introduces no new validators beyond Brief 215's existing status-enum check in `update_escalation_learning_status`. The PATCH endpoint rejects edits when status ≠ 'suggested' (HTTP 409). The suggest endpoint requires `suggestedText`; the channel-resolution rule rejects with HTTP 400 if no pending_notifications row exists AND no body channel is provided.
- No secrets ever round-trip through any endpoint. Operator labels are free-form strings supplied by the client. No raw provider tokens stored.

## Tests / build result

1122 passing / 0 failures (1116 baseline + 6 new). All 6 in `wtyj/tests/social/test_215_escalation_learning.py` (canonical per-module file; Brief 215 named it):

1. `test_brief_263_suggest_learning_creates_pending_row` — round-trip via POST suggest + GET pending.
2. `test_brief_263_patch_edits_pending_text` — PATCH on a pending row updates `human_answer`; SQL inspection confirms persistence.
3. `test_brief_263_patch_rejects_approved_row` — PATCH on approved row returns 409; text unchanged.
4. `test_brief_263_approve_records_approved_at_and_operator` — POST approve sets `approved_at` + `approved_by` + flips `ai_may_use_automatically=1`. SQL inspection confirms all three.
5. `test_brief_263_dismiss_records_dismissed_at_and_excludes_from_prompt` — **load-bearing security assertion**: dismiss soft-rejects (status='deleted' + dismissed_at) AND `get_approved_learnings_for_prompt` excludes the dismissed row. Proves Calvin's rule 7.
6. `test_brief_263_legacy_learning_endpoints_unchanged` — Brief 215 `/learning` GET shape (camelCase, `humanAnswer` / `conversationId`) and `/learning/{id}/approve` continue to work. No breaking change for any existing dashboard caller.

## Production health

CI queued post-commit `d40030b`. All 4 containers expected healthy on the new image. Schema migration runs on first boot via the idempotent ALTER TABLE pattern.

## Replit contract for the approval UI

SR's task: build an Inbox-adjacent "Pending learnings" surface using the new endpoints. Suggested wireframe:

1. **Pending list view** (Settings or Inbox sidebar):
   ```ts
   const { data } = useQuery({
     queryKey: ["escalation-learnings", "pending"],
     queryFn: () => fetch(
       `/api/${tenant}/dashboard/api/escalation-learnings?status=pending`,
       { headers: { Authorization: `Bearer ${token}` } }
     ).then(r => r.json()),
   });
   ```
   Each row shows `suggestedText`, `escalationId` (link to the source escalation if numeric), `createdAt`, `operator` (suggester).

2. **Suggest from escalation detail**: when operator reads an escalation, a "Save reply as learning" button POSTs:
   ```ts
   await fetch(
     `/api/${tenant}/dashboard/api/escalations/${escalationId}/suggest-learning`,
     {
       method: "POST",
       headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
       body: JSON.stringify({
         suggestedText: operatorComposedText, // pre-filled from the reply field
         sourceQuestion: customerLatestMessage,
         channel: "whatsapp", // or "email" etc.
         operator: currentOperatorLabel,
       }),
     },
   );
   ```

3. **Edit before approval**: textarea bound to `suggestedText`, debounced PATCH:
   ```ts
   await fetch(
     `/api/${tenant}/dashboard/api/escalation-learnings/${id}`,
     { method: "PATCH", body: JSON.stringify({ suggestedText: editedText }), ... },
   );
   ```

4. **Approve / Dismiss buttons**:
   - Approve: POST `/escalation-learnings/{id}/approve` with `{operator: currentOperator}`. On 200, refetch the list (the row drops out of `?status=pending`).
   - Dismiss: POST `/escalation-learnings/{id}/dismiss` (no body). On 200, refetch.

5. **Error surfacing**: HTTP 400 ("channel required when escalation row not found"), 409 ("Learning not editable"), 404. All return JSON `{detail: string}` — render in toast/banner.

## Calvin retest steps

1. **Backend smoke test (curl)**:
   ```bash
   TOKEN=$(curl -sX POST https://api.unboks.org/api/unboks/dashboard/api/login \
     -H "Content-Type: application/json" \
     -d '{"password": "<dashboard pw>"}' | jq -r .token)

   # Suggest a learning
   curl -sX POST https://api.unboks.org/api/unboks/dashboard/api/escalations/test/suggest-learning \
     -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"suggestedText":"Test bakery hours 7-19","channel":"whatsapp","operator":"calvin"}'
   # Capture id from response

   # List pending
   curl -sH "Authorization: Bearer $TOKEN" \
     'https://api.unboks.org/api/unboks/dashboard/api/escalation-learnings?status=pending'

   # Edit
   curl -sX PATCH https://api.unboks.org/api/unboks/dashboard/api/escalation-learnings/<id> \
     -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"suggestedText":"Updated bakery hours 7-20"}'

   # Approve
   curl -sX POST https://api.unboks.org/api/unboks/dashboard/api/escalation-learnings/<id>/approve \
     -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"operator":"calvin"}'

   # Verify approved list contains it with approvedAt populated
   curl -sH "Authorization: Bearer $TOKEN" \
     'https://api.unboks.org/api/unboks/dashboard/api/escalation-learnings?status=approved'

   # Try to PATCH approved row - expect 409
   curl -sX PATCH https://api.unboks.org/api/unboks/dashboard/api/escalation-learnings/<id> \
     -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"suggestedText":"should fail"}'

   # Dismiss
   curl -sX POST https://api.unboks.org/api/unboks/dashboard/api/escalation-learnings/<id>/dismiss \
     -H "Authorization: Bearer $TOKEN"

   # Verify dismissed list contains it with dismissedAt populated
   curl -sH "Authorization: Bearer $TOKEN" \
     'https://api.unboks.org/api/unboks/dashboard/api/escalation-learnings?status=dismissed'
   ```

2. **Agent prompt-path test**: enable `features.approved_learnings_in_prompt: true` in unboks's `client.json`. Suggest + approve a learning. Send a customer WhatsApp message; verify Marina's reply incorporates the approved learning. Then dismiss it; send another message; verify Marina no longer references the learning.

3. **Legacy compat**: verify the existing `/learning` GET still works and returns the Brief 215 shape (`humanAnswer` / `conversationId` / etc.) — important for any dashboard wiring that's already using the legacy path.

If anything misbehaves, paste the request + response and I'll iterate.

## Out of scope (deferred)

- **Default-flip**: changing `save_escalation_learning`'s default from `status='approved'` to `status='suggested'` so every operator reply becomes a pending suggestion by default. Calvin's product call; needs explicit confirmation per tenant. Brief 263 ships the surface so Calvin can verify the operator-approval flow works end-to-end before the default flip.
- **Bulk operations** (bulk approve, bulk dismiss): not in Calvin's #32 spec; defer until the UX justifies it.
- **Re-suggest history** (multiple suggestions on the same escalation tracked separately): defer; each call to `/suggest-learning` creates a new row, frontend can group them by escalationId if needed.
