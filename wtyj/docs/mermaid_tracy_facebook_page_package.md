# Klein Curaçao Trip Desk Demo Facebook Page package

This package is for a fictional, clearly disclosed demonstration Page. It must
not replace, rename, claim, or connect Mermaid Boat Trips Curaçao's existing
public Page.

## Current Facebook demo state

The fictional Page was created on 2026-09-02 by an authorized administrator.
This records the resulting public demo surface; it does not claim that Meta,
WhatsApp, Zernio, or the Unboks production channel is connected.

| Item | Recorded state |
|---|---|
| Page | `Klein Curaçao Trip Desk Demo` |
| URL | https://www.facebook.com/profile.php?id=61593777912590 |
| Facebook profile ID | `61593777912590` |
| Created | `2026-09-02` |
| Profile and cover | Generic original demo artwork uploaded. |
| Disclosure | Published as the first post and pinned. |
| Public phone | `+599 9 686 5665` (`+59996865665`), the only real contact datum on the fictional Page. |
| WhatsApp | Disconnected. Meta's connection screen is prefilled with `+599 9 686 5665`; no verification code has been sent. |
| Action button | Disconnected. |
| Demo contact fields | Fictional address `DEMO LOCATION - Harbor Desk 12 (fictional), Willemstad, Curaçao`; reserved email `tracy-demo@example.com`; reserved non-live link `https://tracy-demo.example`. Hours left empty. |
| Marketing emails | Off. |
| Page notifications | On. |

The Page is real, but its assistant/channel behavior remains a demo until the
owner completes the explicit cutover steps below.

## Page settings

| Field | Value |
|---|---|
| Page name | `Klein Curaçao Trip Desk Demo` |
| Category | `Travel service` |
| Secondary category | Not set; `Product/service` is optional after owner review. |
| Bio | `Private demo of TRACY, an AI-assisted guest-service concept for Klein Curaçao trips. Not an official Mermaid social Page.` |
| Public phone | `+599 9 686 5665` (`+59996865665`). |
| WhatsApp | Owner cutover target: `+599 9 686 5665` (`+59996865665`); prefilled in Meta but not verified or connected. |
| Website | `TRACY Demo Website (fictional)` → `https://tracy-demo.example`. The reserved `.example` domain is intentionally non-live; no website was created. |
| Email | `tracy-demo@example.com`. The reserved `example.com` address is fictional and is not monitored. |
| Address | `DEMO LOCATION - Harbor Desk 12 (fictional), Willemstad, Curaçao`. This is not a pickup point or operating address. |
| Hours | Leave empty; the Page does not advertise real operating hours. |
| Action button | Leave disconnected until the dedicated number is verified. Then configure `Send WhatsApp message`. |
| Messaging greeting | `Hi, I’m TRACY, a virtual assistant in a private demo. I can answer published Klein Curaçao trip questions. For live availability, payment, changes, cancellations, safety, accessibility, or anything uncertain, I’ll involve a person.` |
| Instant reply | Off. Zernio and Unboks must be the single automated reply path. |

Suggested username, if available: `@kleincuracaotripdesk.demo`. Username
availability is not an activation dependency.

## Required disclosure

Place this text in the About section and pin it as the first post:

> **PRIVATE DEMO**
>
> This Page demonstrates TRACY, an AI-assisted guest-service concept for a
> Klein Curaçao trip operator. It is not Mermaid Boat Trips Curaçao's existing
> public Facebook Page. TRACY answers from published information and cannot
> confirm availability, take payment, change a booking, or decide a refund.
> Messages that need judgment are handed to a person.

## Visual assets

- Profile: `assets/mermaid-tracy/facebook-profile-generic-v2.png`
- Cover: `assets/mermaid-tracy/facebook-cover-generic-v2.png`

Both are original demo artwork. They deliberately omit Mermaid's name and logo.
The v2 cover also contains no text, so the Page's visible name and pinned
disclosure remain the authoritative identification.

## Launch posts

### 1. Pinned disclosure

Use the required disclosure above. Do not boost or advertise it.

### 2. Meet TRACY

> Meet TRACY, the virtual assistant in this private demonstration. Ask about
> published trip times, prices, inclusions, food options, what to bring, or the
> official booking path. TRACY will say when a question needs a person and will
> never invent availability or a booking.

### 3. Example trip information

> Planning a Klein Curaçao day trip? Published rates currently start at USD
> 150 / EUR 130 / XCG 270 per adult, with separate child and resident bands.
> Live dates and the final payable total are confirmed only in the official
> Mermaid reservation system: https://reservations.mermaidboattrips.com/Reservations/
>
> This is a private demonstration Page, not Mermaid's existing public Page.

## Connection rule

During Meta/Zernio authorization, select only the number that normalizes to
`+59996865665`. If it is absent, if Meta presents Mermaid's public number
`+59995601530`, or if the selected account identity cannot be proven, stop the
connection and leave the tenant paused with a strict empty allowlist.

Facebook native instant replies and other automated-message rules must remain
off so a guest can receive at most one automated response.

Accepting further Meta terms, completing MFA or business ownership checks,
assigning production assets, and verifying the phone number are owner-only
actions. The operator must record only a sanitized pass/fail result. Never copy
a login, verification code, token, callback URL, provider account ID, or Meta
business document into Git or demo evidence.

After authorization, keep `facebook_dms` off until Facebook messaging itself
has a separate tenant-ownership check, strict account binding, inbox-only
isolation test, and one-message/one-reply canary. A WhatsApp connection or a
Page action button does not prove that Facebook DMs are connected.
