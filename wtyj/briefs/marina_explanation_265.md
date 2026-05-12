# EXPLANATION 265 — Email alert multi-button row + WhatsApp Zernio interactive-button investigation

## In one sentence

Operator alert emails for escalations and appointments now show two clickable buttons (jump straight to the specific item, or jump to the dashboard home) instead of one, while WhatsApp alerts stay text-only because the messaging provider we use for WhatsApp does not currently support tappable buttons.

## What's changing and why

Calvin asked for operator alerts to be actionable from the moment they land, not just informational. Before today, when an escalation or appointment alert went out by email, the operator saw a single blue button labelled "Open escalation" or "Open appointment". If they wanted to look at anything else — another conversation, the overview, a different appointment — they had to dig the dashboard URL out of a bookmark or browser history.

Now those alert emails carry a second blue button labelled "Open dashboard" right next to the first one. The first button still takes the operator to the specific escalation or appointment that triggered the alert. The second button takes them to their tenant's dashboard home page, which is a universal landing spot that works no matter which alert type fired. Beneath the buttons, the small plain-text fallback section (for email clients that strip out fancy HTML, like some old desktop Outlook installs or text-only readers) now lists both web addresses one per line instead of just the one. Nothing visible changes for WhatsApp alerts — the compact text body from earlier briefs is unchanged.

The reason WhatsApp wasn't touched: Calvin asked the team to investigate whether the WhatsApp provider (Zernio) could send tappable buttons inside a WhatsApp message. The investigation came back with a clear answer: no. Zernio's send-message function only accepts plain text. There is no button parameter to pass. The other path — talking to Meta's WhatsApp API directly, bypassing Zernio — is blocked because the relevant Meta app was archived a long time ago and would need to be re-registered from scratch. So no WhatsApp change ships in this brief.

The brief also explicitly chose NOT to bolt on a "Reply 1 for escalation, Reply 2 for dashboard" numbered fallback in the WhatsApp body, even though that would have been the obvious-looking workaround. The reason: there is no code anywhere in the system that reads inbound operator replies, recognises "1" or "2" as a command, and routes them to a dashboard action. The operator would type "1", press send, and nothing would happen. Shipping the numbered text without the matching reply-handler would lie to the operator about what works. Building the reply-handler is a real piece of work that needs its own brief later. Rather than ship a decoration, the team shipped honesty.

## Step by step — what the code does now

DASHBOARD LINK BUILDER — what it returns now
The helper that builds dashboard URLs used to know two kinds of links: one for a specific escalation, and one for a specific appointment. A third kind is now recognised: a "dashboard" link, which returns the bare tenant home page web address (just the dashboard base plus the tenant's slug, with no item identifier tacked on). If the helper is asked for any other unknown link kind, it returns an empty string as before. This new branch is what powers the second button in the alert emails.

ALERT EMAIL BUILDER — handling one or many buttons
The function that turns the plain-text alert body into a styled HTML email used to take a single web address plus a single button label and render exactly one blue button at the bottom. It now also accepts a list of (web-address, button-label) pairs. When it receives a list, it renders each pair as its own blue button in a horizontal row, with a small gap between buttons so they don't visually collide. Older parts of the system that still call this function the old way (passing a single URL and label) keep working exactly as before — the function silently wraps the single pair into a one-item list and renders one button, matching the previous behaviour. The plain-text fallback at the bottom of the email — labelled "Plain link:" — used to list one web address; it now lists every web address that was supplied, one per line, separated by line breaks.

APPOINTMENT ALERT DISPATCH — what gets sent now
When an appointment alert fires, the code now asks the dashboard link builder for two URLs back-to-back: one pointing to the specific appointment, and one pointing to the dashboard home. Each URL that comes back non-empty gets bundled into the button list along with its label ("Open appointment" for the first, "Open dashboard" for the second). The button list is then handed to the email builder, which renders both buttons. If for some reason the tenant config is missing the dashboard base URL or the tenant slug (so the link builder returns empty strings), no buttons are added and the email goes out as plain text only, the same fallback behaviour the system has always had.

ESCALATION ALERT DISPATCH — same pattern as appointments
The escalation alert dispatch was updated the same way. It now requests an escalation-specific URL plus the dashboard home URL, bundles both into a button list with labels "Open escalation" and "Open dashboard", and hands the list to the email builder. The WhatsApp branch of the same dispatch function was deliberately left alone — the WhatsApp message still goes out using the compact text-only body from earlier work, with no buttons and no numbered-reply text.

WHY THE DASHBOARD-HOME BUTTON IS UNIVERSAL
A small architectural note worth surfacing: the second button is the same URL ("go to the dashboard home for this tenant") regardless of whether the alert was an escalation or an appointment. That means the operator always has a guaranteed-safe fallback action — even if the first button's deep link breaks for some reason (a stale escalation ID, a frontend route change), the second button always lands them somewhere useful. The dashboard home page is whatever the frontend currently treats as the tenant's landing page (today, that's the Inbox view). If the frontend team later adds a dedicated dashboard-overview page, only the link builder needs updating; the alert code itself doesn't change.

## Edge cases

- If the tenant config is missing either the dashboard base URL or the tenant slug, the link builder returns empty strings for both links, the button list ends up empty, and the email goes out as plain text only with no HTML wrapper. Same fallback the system has always had — operators still get the alert content, just without clickable buttons.

- If only one of the two URLs comes back valid (in practice this would mean a malformed tenant config), the email shows just that one button. The plain-text fallback shows only the URL that exists. Acceptable graceful degradation.

- Any old caller still using the previous one-button calling style continues to get a one-button email rendered exactly as before. This was tested directly and is what keeps the earlier brief's behaviour intact.

- WhatsApp operators get zero new functionality from this brief. They still get the compact text alert. There is no "Reply 1 / Reply 2" prompt because the system can't act on those replies even if the operator sent them. Known limitation, documented honestly rather than papered over.

- Email clients that strip HTML (rare today, but they exist) fall back to the plain-link section at the bottom, which now contains both URLs one per line. Operator can copy-paste either one.

- The dashboard-home button lands on whatever URL pattern the frontend treats as a tenant's landing page. If the frontend changes that pattern, the bare-slug URL might land somewhere unexpected for one deploy cycle until the link builder is updated. Low risk, known trade-off accepted in the brief.

## What did NOT change

The WhatsApp alert body, the alert subject line, and the alert plain-text body builder are all untouched. The Zernio WhatsApp sending code is untouched. No customer-facing message templates were modified — this only affects internal operator alerts. No new web addresses contain tokens or secrets; the URLs are built only from the tenant slug and the tenant dashboard base, both of which are non-sensitive configuration values already used elsewhere. Marina's customer-reply prompt, the booking flow, and all customer data handling are not part of this change in any way.
