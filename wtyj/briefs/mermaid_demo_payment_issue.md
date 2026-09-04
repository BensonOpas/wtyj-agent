# Mermaid simulated payment and WhatsApp receipt

## Scope

Create a payment-only demo checkout and signed completion callback. The page
must display the existing reservation summary and total, accept no real card
data, move no money and be clearly labeled as a simulation.

After one verified simulated-success callback:

- transition `demo_payment_pending -> demo_paid -> booked` atomically;
- assign or reuse the server-generated `MER-DEMO-*` booking code;
- generate one localized payment receipt PDF;
- send a warm same-conversation WhatsApp message with booking code, date,
  guests, paid demo amount, arrival time and what to bring;
- attach the receipt, not a second confirmation PDF.

The receipt must say `SIMULATED PAYMENT - DEMO ONLY` and include booking code,
payment reference, amount/currency, customer, trip date, guest counts and
payment timestamp.

## Acceptance

- Checkout contains no card-number, bank-account or credential fields.
- Callback is signed, expiry-bound, tenant-bound and replay safe.
- Refresh/double-click/retry produces one payment record, booking code, receipt
  and customer delivery.
- The system never trusts customer text such as `I paid` as payment evidence.
- Failure/cancel returns to WhatsApp with the reservation still pending.
- Six-language success copy is warm and factually grounded.
- No reminder is scheduled after payment or on failure.

## Rollback

Disable `mermaid_demo_payment`; pending reservations remain visible and no real
funds require reversal.
