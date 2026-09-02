# TRACY Monday demo script

Target length: 8 to 10 minutes. Use only the dedicated tester and the demo
number `+599 9 686 5665`.

## Pre-room check

- Mermaid health and dashboard tenant identity are green.
- Nr3 shows the exact normalized number `+59996865665` and one strict Zernio
  account.
- Ali, Roberto, and Unboks health checks are green.
- Facebook and WhatsApp native instant replies are off.
- The Mermaid inbox contains no rehearsal customer data.
- Keep Nr3's AI switch off for the first inbound isolation check. After that
  message is visible only in Mermaid, turn AI on deliberately and send a new
  identity message.

## Live story

1. **Show the real tenant.** Open the Mermaid workspace in the normal Unboks
   dashboard. Point out the tenant identity, empty/clean inbox, channel status,
   and pause control.
2. **Prove inbox isolation.** With AI still off, send `Channel check` from the
   tester phone to `+599 9 686 5665`. Confirm it appears only in Mermaid and
   receives no automated reply. Turn AI on, then send `Hi, who are you?` as a
   new message. TRACY should identify herself as a virtual assistant in the
   demo without claiming that the fictional Facebook Page is Mermaid's
   official Page.
3. **Show grounded sales help.** Send `What is the price for two adults and a
   seven-year-old?` The answer should use only the published price bands and
   avoid claiming availability.
4. **Show the booking boundary.** Send `Do you have four seats this Sunday?`
   TRACY should explain that she cannot see live seats and give the official
   reservation path.
5. **Show judgment and escalation.** Send `Can I cancel tomorrow and get a
   refund?` TRACY should not invent a cancellation promise. The dashboard
   should show the escalation; the guest must not see `[ESCALATE]`.
6. **Show human control.** Take over in the dashboard, send one operator reply,
   and send another guest question. Confirm TRACY stays muted. Hand back, ask a
   routine published-fact question, and confirm she resumes.
7. **Close on deployment reality.** Show that the same tenant can be kept and
   moved from the dedicated demo number to an approved production number later
   without rebuilding TRACY or the Unboks workspace.

## Abort conditions

Pause Mermaid immediately if any of these occurs:

- the channel number is not exactly `+59996865665`;
- a provider account outside Mermaid's strict allowlist appears;
- a single message receives more than one automated reply;
- a Mermaid message appears in another tenant;
- an internal marker, secret, prompt, or customer record is exposed;
- the model invents availability, payment, cancellation, refund, safety, or
  accessibility facts.

Do not switch to Mermaid's public number as a fallback. If the dedicated channel
is unavailable, show the live tenant and dashboard while keeping outbound
messaging paused.
