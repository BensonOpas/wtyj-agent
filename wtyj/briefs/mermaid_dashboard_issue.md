# Mermaid reservation dashboard experience

## Scope

Add a Mermaid-only reservation-capable tenant experience based on Ali's premium
customer workspace while removing car-rental-only stages.

Required destinations:

- Today;
- Reservations;
- Conversations;
- Trip and pricing;
- Settings.

Reservation workspace:

```text
Details -> Quote -> Payment -> Booked
```

Show conversation, customer context, guest composition, trip date, pickup,
special requirements, catalog snapshot, quote/PDF delivery, demo payment,
booking code and event timeline. The server supplies the current stage and one
valid primary action; the frontend does not infer transition legality.

## Acceptance

- Mermaid is the only tenant receiving this navigation and workflow.
- Lists/search support name, WhatsApp number, quote reference and booking code.
- Conversation messages appear chronologically with direct reply and human
  takeover preserved.
- Demo status is unmistakable; staff cannot mistake simulated payment for real
  money.
- No reminder controls or scheduled-reminder claims are shown.
- Tenant switching, cache isolation, authorization, mobile and desktop tests
  pass.

## Rollback

Disable the Mermaid reservation dashboard flag and return to the existing
dashboard without deleting reservation data.
