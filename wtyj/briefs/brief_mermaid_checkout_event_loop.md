# BRIEF — Keep Mermaid checkout delivery off the web event loop

**Status:** Implemented; locally verified, pending review | **Files:** `wtyj/agents/social/webhook_server.py`, `wtyj/tests/agents/test_mermaid_checkout_concurrency.py` | **Depends on:** deployed commit `70decedc6883bc4d62670d303699b1bd7c582b8b` | **Blocks:** none

## Context

The checkout POST route is asynchronous but directly calls synchronous payment completion (`wtyj/agents/social/webhook_server.py:198`). Completion performs provider HTTP requests and delivery polling before returning (`wtyj/agents/social/mermaid_demo_payment.py:130`; `wtyj/agents/social/zernio_dm_client.py:1083`). The same server serves the signed receipt PDF (`wtyj/agents/social/webhook_server.py:185`), and `supervisord.conf:20` starts one Uvicorn worker. While delivery blocks the event loop, the provider cannot fetch that PDF and health checks and webhooks must wait.

Live monitoring observed one ambiguous receipt delivery followed by three HTTP 422 rejections. Subsequent read-only provider history confirmed that the exact receipt eventually delivered; the local receipt ledger was reconciled separately. Those events motivate the investigation but do not prove that event-loop blocking caused each provider result. The concurrency regression isolates the blocking defect without contacting any provider.

## Why This Approach

Offload the existing synchronous completion operation to Starlette's thread pool after parsing the request form. Acquire an async capacity limiter of one before submitting work: payment state is transactional, but receipt rendering and delivery do not have a concurrent claim. This preserves the previous serialized checkout behavior without blocking the event loop or filling worker threads with waiting callbacks. This preserves validation, operator controls, payment state transitions, receipt generation, response content, and delivery semantics. Adding multiple Uvicorn processes was rejected because the application has process-local buffering and recovery workers; it would broaden the operational change and would not remove blocking inside each worker. A queue or receipt retry redesign is outside this repair.

## Instructions

1. Import `CapacityLimiter` and `run_in_threadpool`, and serialize checkout submissions with a module-level limiter of one. Import `run_in_threadpool` in `wtyj/agents/social/webhook_server.py` and await it around the existing `complete_checkout` call at the checkout POST boundary.
2. Add an ASGI concurrency regression using an isolated SQLite database, real receipt generation and signed document route, and a provider stub held by threading events.
3. While the provider stub remains blocked, require successful GET and HEAD health checks and successful retrieval of the exact signed receipt PDF. Then release delivery and verify the checkout response and durable delivery status.

## Tests

Run the regression against the original route and record its failure. Run it again after the offload and then run the existing Mermaid payment, end-to-end, and signed-document tests. The event timeout is a failure bound, not a sleep that establishes ordering. No test message or provider request is sent.

## Success Condition

Health requests and the signed receipt download finish while checkout delivery is still waiting, and releasing delivery completes the same checkout successfully.

## Rollback

Revert the route offload and its import or restore the previous Mermaid image. This change adds no schema, configuration, or data migration.

## Verification

The regression failed against the original deployed route with `AssertionError: Checkout blocked the event loop until delivery timed out` (`1 failed in 6.39s`). After the offload, the regression plus existing Mermaid payment, end-to-end, and signed-document suites passed (`30 passed in 1.76s`).

Command: `python -m pytest wtyj/tests/agents/test_mermaid_checkout_concurrency.py wtyj/tests/agents/test_mermaid_demo_payment.py wtyj/tests/agents/test_mermaid_demo_e2e.py wtyj/tests/agents/test_mermaid_quote_pdf.py -q`.

Local Python version: 3.14.7. The ASGI test exercises concurrent requests in the same event loop, without starting the production lifespan or contacting external services. No commit, push, or production deployment is included in this bounded change.

The extended duplicate-callback regression failed before the limiter with `Duplicate checkout must queue before occupying a worker` (two submissions). With the limiter, both callbacks return 200, exactly one provider call occurs, and health/PDF requests complete while delivery is blocked. Final focused result: **30 passed in 1.65s**. The production AnyIO version is 4.12.1 and supports the import-time limiter adapter.
