# EXPLANATION 243 — HTML CTA buttons + dashboard deep-links in alert emails

## In one sentence
Alert emails now include a clickable blue "Open escalation" or "Open appointment" button that takes the operator straight to the right item in the dashboard, instead of just a plain-text line saying "open the dashboard."

## What's changing and why

Before today, when Marina escalated a conversation or flagged an appointment, the alert email Calvin received ended with a flat sentence like "Open the dashboard to reply." There was no link. He had to open the dashboard manually, find the right tab, and hunt for the matching item. With dozens of escalations a week, that wastes time and adds friction every single ping.

Now each alert email arrives with two things: the same plain-text body as before, and a richer HTML version layered on top. The HTML version shows the same content but adds a blue button labelled "Open escalation" or "Open appointment" that links directly to that specific item in the dashboard. Underneath the button there's also a "Plain link" line showing the full URL in case the button doesn't render. Email clients that strip HTML (rare, but possible) just see the original plain-text body — nothing breaks for them. WhatsApp, Telegram, and Messenger alerts are untouched; only email gets the upgrade.

The dashboard URL the button points to has the shape `https://dashboard.unboks.org/<tenant>/escalations/<id>` (or `/appointments/<id>`). The system builds this from two new pieces of tenant identity: a short slug name and the dashboard's base address, both stored in each tenant's configuration file. The frontend team needs to add route handlers that match those URL paths — until they do, clicking the button will land the operator on the dashboard's home page rather than the specific item, but the link itself stays valid (no 404).

## Step by step — what the code does now

STEP: Tenant identity gets two new fields

Every tenant's configuration file now carries two extra pieces of information about itself: a short slug name (`unboks`, `adamus`, `bluemarlin`, or `consultadespertares`) and the dashboard's web address (`https://dashboard.unboks.org`). All four tenants share the same dashboard, but each one identifies itself with its own slug so the URL points to the right tenant's section. BlueMarlin gets the fields too even though it doesn't fire alerts anymore — this keeps the configuration shape consistent across all tenants.

STEP: The email-sending function learns to send HTML alongside text

The system's single email-sending function gained an optional second body parameter for HTML content. When only the plain text is given (the way every other email-sending caller still uses it), the function behaves exactly as it did before — single-part plain-text email. When the caller also passes HTML, the function builds a multi-part email containing both versions. The text version goes first, the HTML version goes second. The receiving email client picks whichever it prefers — Gmail, Outlook, Apple Mail, and mobile clients render the HTML; text-only readers fall back to the plain version. Both copies always go out together; it's the receiving end that chooses.

STEP: Build the deep-link URL for a specific item

A new helper takes two inputs — the kind of item ("escalation" or "appointment") and its numeric ID — and returns a full URL pointing at it in the dashboard. It pulls the slug and dashboard address from the tenant's configuration, normalises away any trailing slashes, and assembles a path-style URL like `https://dashboard.unboks.org/unboks/escalations/42`. If either the slug or the dashboard address is missing or the item kind is unrecognised, the helper returns an empty string instead of a half-broken link. Anything unexpected during the lookup (a configuration read failure) also produces an empty string, never an error.

STEP: Wrap the plain-text alert into a styled HTML version

A second new helper takes the existing plain-text alert body, the URL to the item, and a button label, and returns an HTML document. The text body is shown inside a preformatted block so the visual layout the operator scans (customer name, reason, recommended actions) is preserved exactly. Below the text sits a blue button — Google's signature `#1a73e8` blue, white text, rounded corners, padded — that links to the deep-link URL. Below the button sits a smaller grey "Plain link:" line showing the full URL as text, in case the button doesn't render or the operator wants to copy the address. Every piece of dynamic text (the body, the URL, the button label) is HTML-escaped, so customer names containing characters like `<` or `&` cannot break the page or inject markup.

STEP: Escalation alerts use the new helpers

When the system fires an escalation alert by email, it now does one extra thing before sending: it asks the link helper for a URL pointing at this specific escalation. If the helper returns a real URL, the system builds an HTML body labelled "Open escalation" and passes both the text and HTML versions to the email-sending function. If the helper returns an empty string (because the tenant's configuration is missing the slug or dashboard address), the system passes only plain text — exactly what every operator received before this change. Link building happens once per alert, not once per recipient, since every recipient gets the same link.

STEP: Appointment alerts use the new helpers the same way

The appointment alert path mirrors the escalation path. It builds a URL pointing at the specific appointment, wraps the alert text in HTML with an "Open appointment" button, and passes both versions to the email-sending function. If the link can't be built, it falls back to plain text. The per-recipient deduplication that already prevents the same operator from receiving the same appointment alert twice is preserved unchanged.

STEP: Other channels stay plain

WhatsApp, Telegram, and Messenger alert paths inside both dispatchers were not touched. Those channels continue to send the same plain-text alert they always have. WhatsApp doesn't render HTML buttons, and adding deep-links into Zernio-routed messages is a separate question for another day.

## Edge cases

- If a tenant's configuration is missing either the slug or the dashboard address, the link helper returns an empty string and the alert email goes out as plain text only. The operator gets the same email they received before this brief — slightly less convenient, no broken UI. This is the deliberate fallback, not a bug.
- If the configured dashboard address has a trailing slash, the helper trims it before assembling the URL, so the result still has exactly one slash between the address and the slug.
- If the item kind passed to the helper is anything other than "escalation" or "appointment", the helper returns an empty string. No URL with an unknown path segment ever escapes.
- If the configuration read itself throws an error for any reason, the helper catches the error and returns an empty string. The alert still sends as plain text. An alert never fails to deliver because the link couldn't be built.
- Customer names, alert text, and URLs are all HTML-escaped before being placed in the HTML body. A customer named `<Calvin>` or message text containing `&` won't break the page or be misread by the email client.
- The frontend dashboard does not yet have route handlers for the deep-link paths. Until SR ships those routes, clicking the button lands the operator on the dashboard home page (still valid — the URL doesn't 404, the React app just doesn't recognise the deeper path and falls through to the root). The operator then has to navigate manually, exactly as they do today. This is a known and accepted gap; the link is documented as the contract for the frontend follow-up.
- Operators must already be logged into the dashboard for the link to take them anywhere useful. There is no auth token in the URL — clicking when logged out triggers the dashboard's normal login flow. Whether the dashboard then redirects back to the requested item after login is a frontend decision, not a backend one.
- The text part of the email is attached first and the HTML part second. RFC 2046 says HTML clients should prefer the last acceptable part, which is why HTML clients pick HTML. Text-only clients ignore the HTML and pick the text. Both clients land on the right thing.
- The BlueMarlin tenant has the new slug and dashboard URL fields in its config, but BlueMarlin no longer fires alerts (deprecated since Brief 238). The fields sit unused but keep BlueMarlin's config shape consistent with the active tenants.
- Pre-existing test mocks of the email-sending function had to accept the new optional HTML parameter to keep working. Seven older fakes were updated to accept any extra keyword arguments, so future additions to the email function won't silently break those tests either.

## What did NOT change

Marina's prompt, the booking flow, customer-facing replies, and the WhatsApp / Instagram / Messenger alert paths were not touched. The plain-text email body that Calvin reads at a glance is byte-for-byte the same as the body Brief 239 (escalation rich body) and Brief 241 (appointment body) shipped — the new HTML simply wraps that text and appends a button below it. The deduplication that prevents duplicate appointment alerts and the email destination logic from Brief 226 are both preserved. No customer data flow changed; the only new outbound payload is the HTML body next to the existing text body in the same alert email.
