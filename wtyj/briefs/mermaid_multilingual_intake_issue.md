# Mermaid multilingual natural reservation intake

## Scope

Add a Mermaid-specific structured intake that reuses Ali's natural quote-led
principles without copying car-rental fields or wording.

Required fields:

- trip date;
- adult count;
- child count age 4-12;
- infant count age 0-3;
- customer full name;
- pickup preference (`pier` or `pickup_requested`);
- pickup/hotel text when pickup is requested;
- conversation language.

Optional fields:

- dietary requirements;
- mobility, medical or accessibility notes volunteered by the customer;
- special requests.

Behavior:

- Answer the customer's newest question first.
- Use facts already supplied; never ask twice.
- Ask one short next question.
- Explain early that TRACY will prepare an official quote in WhatsApp.
- Support Dutch, German, English, Spanish, Papiamentu and Portuguese.
- Present one deterministic first-person summary and require explicit
  confirmation before creating the quote.
- A correction updates only the changed field.
- A question, hesitation, emoji or ambiguous reply is not confirmation.
- A human request pauses automation without losing progress.

## Acceptance

- Six-language tests cover opening, partial intake, summary, correction,
  explicit confirmation, cancellation and human takeover.
- `three people` triggers one concise adult/children clarification, not three
  separate questions.
- Unsupported or mixed language defaults safely to English while preserving
  the customer's supplied names and places.
- Prompt output cannot set prices, payment status, booking code or availability.
- Duplicate inbound delivery does not advance the state twice or send a
  duplicate reply.

## Rollback

Disable `mermaid_reservation_demo`; normal Mermaid informational replies remain
available through the existing tenant path.
