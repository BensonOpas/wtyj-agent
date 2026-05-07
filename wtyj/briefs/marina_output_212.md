# OUTPUT 212 — Dashboard endpoint polish

## What was done

Three additive changes to `wtyj/dashboard/api.py`. (1) Added singular-path aliases `GET /learning` and `DELETE /learning/:id` next to the existing plural `/learnings` handlers (matches SR's frontend, which calls singular). (2) Changed `PUT /schedule/slots` to accept a raw JSON array body via `slots: list = Body(...)` — SR's frontend posts the array directly, the prior `ScheduleSlotsRequest` wrapper rejected it with 422. (3) Added new `POST /ai-editor` endpoint — operator-facing Claude proxy for the reply composer's translate / style / fix buttons. Bounded action+language+style enums constrain free-form input; uses `claude-sonnet-4-6` (matches every other Claude call in the codebase). Imports updated to include `Body` from fastapi.

## Tests

955 passing / 0 failures (baseline 949 + 6 new).

## Unexpected findings

`wtyj/tests/social/test_111_scheduling.py::test_api_schedule_slots` was sending the old wrapped `{slots: [...]}` body and failed under the new contract. The brief's "no internal regression risk" claim missed this caller. One-line fix: changed the test's `json={"slots": [...]}` to `json=[...]` to match the new contract. Added a brief comment explaining the shape change. The change is intentional (the wrapped form was never reaching the dashboard frontend, only the test was using it), so updating the test is the correct response — not adding backwards compat that would be code clutter.

## Deployment

Pending — commit/push/deploy in step 16.
