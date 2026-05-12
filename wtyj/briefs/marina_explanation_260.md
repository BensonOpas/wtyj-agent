# EXPLANATION 260 — Cloud knowledge connectors: backend status endpoint + frontend contract (Google/OneDrive/Dropbox; remove SharePoint/Box)

## In one sentence

The dashboard's cloud-knowledge area can finally tell Calvin the truth about each connector — whether it's fully wired, half-wired and waiting for someone to click Connect, or stuck waiting on Calvin to register an app at Microsoft or Dropbox — instead of showing the same "will be connected by the Unboks team" placeholder on every card.

## What's changing and why

Until now, the Source-of-Truth section of the dashboard had five connector cards (Google Drive, OneDrive, Dropbox, SharePoint, Box), and every single one of them was a fake. The frontend was reading from the browser's own scratchpad memory and forcing all five to look "not connected." Clicking Connect did nothing. There was no backend feeding the cards real information, so Calvin couldn't tell which connectors were already partially built versus which ones were vapor.

This change adds the missing backend voice. There is now a real endpoint the dashboard can ask: "for each cloud connector, what is your honest status right now?" The answer comes back as a list of three providers — Google Drive, OneDrive, Dropbox — with SharePoint and Box dropped entirely per Calvin's call. For each provider, the backend reports one of three states:

- **Connected** — the platform-level credentials are installed AND a token has been saved for this tenant, meaning the connector is fully live.
- **Setup required** — the platform-level credentials are installed but no one has clicked Connect yet for this tenant, so the OAuth dance hasn't run.
- **Not configured** — the platform-level credentials aren't even installed on this server, meaning Calvin first has to go register an app over at Microsoft or Dropbox before anyone can click Connect.

The deliberate non-choice here is just as important as what was built. We did NOT write OAuth flows for OneDrive or Dropbox. Pretending those flows exist would have meant inventing fake credentials, shipping code paths nobody could test, and giving Calvin connectors that look wired but break the first time anyone trusts them. Instead, the backend honestly reports "not configured" until Calvin does the external work, and the brief's output document spells out exactly which env vars and redirect URLs need to be set up at Microsoft and Dropbox before those connectors can light up.

## Step by step — what the code does now

**Endpoint: "What's the status of every cloud connector?"**

When the dashboard asks this endpoint, the system runs three checks back-to-back — one for Google Drive, one for OneDrive, one for Dropbox — and packs the answers into a fixed-order list. The order is fixed on purpose so the dashboard always renders the cards in the same sequence without having to sort them itself. The endpoint requires the same authentication as every other dashboard call, so an unauthenticated visitor can't poke it.

**Google Drive status check**

The system looks for two pieces of platform-level credentials in the server's environment. If either is missing, Google Drive is reported as not configured and flagged as needing Calvin to register an app first. If both credentials are present, the system then looks in its token store for a row keyed to "google_drive." If no token row exists, Google Drive is reported as setup required — meaning the credentials are in place but nobody has clicked Connect yet for this tenant. If a token row does exist, Google Drive is reported as connected. When connected, the system also reports the saved folder name (if a folder has been picked) and the timestamp of the last token update, so the dashboard can show "synced 4 hours ago" or similar. This reuses the same credentials and token row that the existing photos-OAuth flow uses — it is purely a read, nothing gets modified.

**OneDrive status check**

The system looks for two OneDrive-specific platform credentials in the environment. Today, on every live server, those credentials are missing, because Calvin has not yet registered an app in Azure Active Directory. So the answer is always: not configured, and flagged as needing app registration. The code is structured so that the moment Calvin adds the credentials, OneDrive will automatically flip to setup required — at which point a future piece of work would add the actual click-Connect-to-authorize flow. Until then, the dashboard should treat the OneDrive card as a disabled card with a "Setup pending" note.

**Dropbox status check**

Identical shape to OneDrive. The system looks for two Dropbox-specific platform credentials. They are missing everywhere today because Calvin has not yet registered an app in the Dropbox developer console. The status is always not configured today, and the card should be rendered as disabled. The moment Calvin sets up the Dropbox app and adds the credentials, the status will flip to setup required on its own.

**What the dashboard now receives**

Where it used to receive nothing (and fell back to a hardcoded "all five disconnected" stub in the browser), it now receives a three-item list. Each item carries: the provider's stable id (so the frontend can switch on it), a human-readable label like "Google Drive," a short subtitle blurb, the honest status, an optional folder name and last-synced timestamp when connected, and a flag the UI can use to decide whether the Connect button should be enabled or disabled.

## Edge cases

- If both Google Drive credentials are set but the token row was deleted (for example, after Calvin disconnects), the status flips back to setup required. The Connect button becomes live again. This matches the existing photos-OAuth disconnect behavior.

- If only one of the two Google Drive credentials is set (one half present, one missing), the system treats this as not configured. There's no half-credentials state — you need both or neither.

- If a Google Drive token row exists but has no folder selected yet, the status is still connected; the folder_name field is just omitted from the response. The dashboard should not assume folder_name is always present on connected providers.

- OneDrive and Dropbox will report not configured forever, on every server, until Calvin completes the external app registration. This is the deliberate trade-off documented in the brief — it's an honest "waiting on a human" state, not a bug.

- The endpoint does not check whether the tenant actually has the right to use a given connector, or whether the token has expired. If a token row exists, the status is connected — even if the token would fail on first use. Token refresh failures will surface through the existing OAuth flow, not through this status endpoint.

- The fixed provider order (Google, OneDrive, Dropbox) means if Calvin later asks to reorder the cards, that's a code change, not a dashboard preference.

## What SR needs to change in the Replit frontend

The browser-side stub that fakes everything from localStorage needs to be replaced by a real call to this new endpoint. The five-provider list in the frontend needs to be trimmed to three — SharePoint and Box cards go away entirely. The Connect button on the Google Drive card should be wired to the existing Google OAuth start URL when the status is setup required, and disabled with a "Setup pending — contact Unboks team" tooltip when the status is not configured. The OneDrive and Dropbox cards should render in their disabled state until those flip off not configured.

## What did NOT change

The existing Google Drive OAuth flow that powers the photos use case — the start, callback, status, folders, sync, and disconnect endpoints — was not touched. Customers' conversations, Marina's prompt, the booking flow, the agent's reply logic, the knowledge-files ingestion pipeline, and any tenant data are all unmodified. No OAuth flow code was added for OneDrive or Dropbox; the brief deliberately ships only the honest status surface and documents the external work Calvin still needs to do at Microsoft and Dropbox.
