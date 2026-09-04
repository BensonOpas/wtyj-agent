# Mermaid reservation demo release hardening

## Context

Calvin explicitly authorized deployment and activation on the dedicated Mermaid
WhatsApp number. Preflight found that the synthetic tests bypassed the live
debounced sender and supplied complete facts instead of normal short replies.
The live sender forced attachments to image, and the deterministic fixture
parser could not interpret an answer such as a bare number or weekday.

## Why this approach

Keep pricing, reservation state, quote creation and payment authorization in
Python. Use the existing single-call Marina engine with a Mermaid-specific
structured contract to understand natural conversation, as Ali does. Reject
another keyword patch: it would still fail ordinary multilingual replies and
violate the repository's language-understanding boundary.

## Scope

- Incorporate the hardened PR324 foundation before any runtime switch.
- Add one-call Mermaid language understanding and server-validated intake.
- Preserve canonical confirmation and never let model output set money or paid state.
- Correct the live WhatsApp PDF attachment type, stable delivery key and audit.
- Persist outbound quote payload for idempotent delivery recovery.
- Fail closed for missing signing configuration and disabled demo payment.
- Preserve all provider credentials and exact allowlist during deployment.

## Verification

Test ordinary short-answer collection, correction/confirmation separation,
invalid model values, signed public downloads, live debounce PDF transport,
replay safety and payment runtime controls. Run the full backend release suite.
Use a private isolated synthetic canary on the deployed image, then one
authorized same-chat demonstration to Calvin if the verified live conversation
is still inside the WhatsApp service window.

## Rollback

Restore only Mermaid's saved compose image and config/env backup; preserve its
database and delivery audit. Other tenant images and bindings must not change.
