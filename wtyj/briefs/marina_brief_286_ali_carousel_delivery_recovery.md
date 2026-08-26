# BRIEF 286 — Ali carousel delivery recovery
**Status:** Approved by owner | **Files:** `wtyj/agents/social/ali_vehicle_recommendations.py`, `wtyj/agents/social/zernio_dm_client.py`, `wtyj/agents/social/webhook_server.py`, `wtyj/agents/social/ali_quote_workflow.py`, `wtyj/shared/state_registry.py`, existing Ali vehicle and Zernio tests | **Depends on:** Briefs 281, 285; GitHub issue #222 | **Blocks:** none

## Context

Zernio can accept an Ali vehicle carousel and its picker, then emit a sparse `message.failed` for the carousel after the picker is already delivered. The current system records both provider IDs as one flat success and only recovers when the provider repeats text/media metadata. Production therefore left a customer with a picker but no car images. The public website image proxy was separately repaired so every active fleet image now returns `200 image/jpeg`.

## Why This Approach

Treat the carousel and picker as independently deliverable parts, validate every server-owned image URL before submission, and persist the outbound recommendation snapshot with each part ID. A late failure can then be identified from our own record even when the webhook is empty. Retry the validated carousel once; if that part fails again, deliver each image independently while retaining the one existing picker. This preserves the natural discovery flow and makes duplicate webhooks/restarts harmless.

## Instructions

1. Preflight every carousel card through the strict Ali HTTPS JPEG proxy before sending it. Reject redirects, unsupported MIME, oversized bodies, non-200 responses, and any URL outside the configured Ali origin and `/api/v1/vehicle-media/` route.
2. Return and persist provider IDs by part (`carousel`, `picker`, `individual_images`, or fallback), together with a bounded server-owned recommendation snapshot, state hash, action ID, and vehicle IDs. Keep the existing flat ID list for compatibility.
3. Match late failures by persisted provider ID and part. Do not depend on webhook text, attachments, media flags, or provider error details. Unknown failures must not be mistaken for Ali recommendation failures.
4. Claim recovery transactionally. Duplicate callbacks and process restarts must not repeat work. Retry a failed carousel once using the current published catalog and validated proxy URLs under a deterministic idempotency key.
5. If the retry is rejected or later fails, send the current car images as individual image messages. Preserve or resend exactly one picker only when no picker was already accepted. Do not duplicate a customer selection.
6. If all media recovery fails, send one concise text fallback and create one visible hard operator escalation. Record a provider reason when present, but never require it.
7. Preserve single-car images, selection postbacks, Send my quote, the three-minute customer quote boundary, tenant isolation, and non-Ali workflows.

## Tests

1. Preflight: valid JPEG, wrong origin/path, redirect, non-200, wrong MIME, oversized response.
2. Normal carousel result and commit persist distinct carousel/picker IDs and a bounded recovery snapshot.
3. Sparse known-carousel failure retries without webhook text/media/account metadata; account ID falls back to persisted server state.
4. A retry failure sends individual images, retains exactly one picker, and records every recovery part.
5. Duplicate initial or retry failure webhooks and restart/replay are idempotent.
6. Unrecoverable media sends one text fallback and creates one hard operator alert.
7. Run focused Ali vehicle/Zernio suites and the full test suite.

## Success Condition

For a controlled Ali test conversation, every displayed option has a delivered image and exactly one working picker. A sparse late carousel failure recovers automatically without duplicate customer messages, while unrecoverable media becomes visible operator work.

## Rollback

Revert the Brief 286 merge and deploy the previous agent image. The change uses bounded JSON flags only and adds no destructive migration; older code ignores the new part/recovery fields.
