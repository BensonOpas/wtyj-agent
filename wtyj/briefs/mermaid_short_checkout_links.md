# Short customer checkout links
**Status:** In progress | **Files:** Mermaid payment, reservation store, workflow, webhook routes, tenant catalog, checkout tests, deployment routing | **Depends on:** live status and introduction release | **Blocks:** readable checkout link

## Context
The customer-facing WhatsApp link exposes a long internal reservation path plus expiry and HMAC query parameters. The user requested a shorter, more human-readable link.

## Why This Approach
Serve checkout directly at the existing branded origin under `/mermaid/pay/` with a 128-bit opaque private code. Store only a keyed hash of the code with its reservation and one-hour expiry. Reject a generic external URL shortener, which adds a dependency and can still redirect guests to the long internal URL. Existing signed URLs remain valid.

## Instructions
- Add tenant-scoped expiring checkout-code storage with cascading removal when the reservation is removed.
- Resolve the code server-side and reuse the existing payment authorization and idempotency behavior. Keep the browser on the short URL for GET and POST; do not expose the original query string in the form.
- Use a concise translated checkout invitation from tenant configuration. Route only the new Mermaid checkout prefix on the existing public host to its current tenant runtime.
- Deploy from the current image so the status/cache and introduction changes remain intact. Preserve customer data and existing links.

## Tests
Short path and expiry, invalid/tampered/rotated-secret links, tenant isolation, deletion, no database plaintext tokens, rendered form URLs, repeated callbacks and the existing nonblocking checkout test. Verify the public route using read-only checkout requests; customer sends stay disabled in isolated tests.

## Success Condition
WhatsApp displays a compact `unboks.org/mermaid/pay/…` link with a friendly invitation, and checkout remains on that link with unchanged security and payment semantics.

## Rollback
Restore the prior Mermaid image, catalog and public-host nginx configuration from the release backup. Preserve the live database and prior signed links. New link rows are additive and harmless to the prior runtime.
