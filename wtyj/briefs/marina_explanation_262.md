# EXPLANATION 262 — Source of Truth server-side persistence: GET/PUT endpoints + tenant-scoped storage

## In one sentence
The Source of Truth blocks an operator edits in the dashboard Settings page now live on the server instead of in the browser, so the same edits follow that operator across phones, laptops, browsers, and teammates on the same tenant.

## What's changing and why

Until now, when Calvin (or any operator) opened the dashboard Settings page and edited a Source of Truth block — pricing rules, escalation policies, brand voice notes — those edits were saved inside that one browser only. The page even admitted this with a yellow banner: "Edits are saved on this device while we wire up sync across browsers and team members." So if Calvin edited from his laptop in the morning and then opened the dashboard from his phone in the afternoon, he saw none of his morning edits. If a teammate opened the dashboard, they saw the original defaults — not Calvin's tuned version. That made the editor a demo, not a real tool.

After this change, the Source of Truth is stored on the server, scoped to the tenant. Every operator on that tenant sees the same blocks, from any device, on any browser. The frontend can still draw the initial default content (so the defaults stay authored in one place rather than duplicated on the backend), but the moment that content is saved, the server takes over as the single source of truth. The backend also guards against a runaway paste blowing up the database, against tenants ever seeing each other's content, and against a buggy or hostile frontend trying to smuggle hidden fields into what gets saved.

## Step by step — what the code does now

LOADING THE SOURCE OF TRUTH ON PAGE OPEN

When an operator opens the dashboard Settings page, the browser asks the server for that tenant's Source of Truth. The server looks up the single row that holds this tenant's blocks, reads the saved JSON, and returns the list of blocks. If no row has ever been saved for this tenant (a fresh tenant), the server returns an empty list. The frontend treats an empty answer as the signal to seed its built-in default content and immediately save that back to the server. From then on, the server's copy is authoritative.

PROTECTING AGAINST A CORRUPTED OR BROKEN STORED VALUE

When the server reads the stored blocks, if for any reason the saved JSON is unreadable or the stored value is not the expected list shape, the server quietly returns an empty list instead of crashing. The Settings page stays usable; the operator can re-save and recover.

SAVING THE SOURCE OF TRUTH WHEN THE OPERATOR CLICKS SAVE

When the operator edits a block and saves, the browser sends the entire blocks list to the server. The server runs that list through a validator before anything is written. If the validator accepts the payload, the server writes the cleaned list as a single JSON blob in that tenant's row (replacing whatever was there) and stamps the save time. The server then reads the row back and returns the cleaned, saved blocks to the browser, so the frontend can see exactly what the server kept.

WHAT THE VALIDATOR CHECKS BEFORE A SAVE GOES THROUGH

The validator walks the incoming blocks one by one. It rejects the save with a clear error message if:

- More than fifty blocks were submitted.
- Any block is missing an id or title, or those are not strings.
- Any id or title is longer than two hundred characters.
- Any block content, items entry, subsection content, or subsection item is longer than roughly four kilobytes (4096 characters).
- A block has more than fifty items, or more than twenty subsections.
- A subsection is missing its title, or has more than fifty items.
- Anything that should be a string is something else (a number, a boolean, a nested object).

If everything passes, the validator builds a clean copy of each block from scratch, copying only the recognized fields: id, title, content, items, and subsections (and inside subsections, only title, content, and items). Anything else the browser sent — for example, fields named internal_prompt, debug_only, or _admin_field — is simply not copied into the clean version. The clean version is what gets saved and what gets returned. There is no way for an unknown field to round-trip through the save and reappear on a later load.

WHY EACH TENANT STAYS ISOLATED FROM EVERY OTHER TENANT

Each tenant runs in its own container, and each container has its own database file on disk. The "source of truth" table sits inside that database file. There is no shared store, no shared row, no shared key. BlueMarlin's container only ever reads BlueMarlin's database; unboks's container only ever reads unboks's. Cross-tenant leakage is not just blocked by code — there is no shared path that could leak in the first place.

REJECTED SAVES DO NOT WIPE THE PREVIOUS GOOD STATE

If the validator rejects a save (say, the operator pasted a 10 KB chunk into one block's content), the server returns a 400 error with the reason. Nothing is written to disk. A subsequent load returns whatever was already saved before the bad save attempt. The operator can adjust and try again without losing prior good work.

## Edge cases

- If two operators on the same tenant save at almost the same moment from different devices, the second save wins for the whole blocks list — the server does not merge per-block. This is the trade-off of storing the Source of Truth as one JSON blob; it matches how the frontend already works (load the whole array, edit, save the whole array). Operators coordinating on edits should expect last-save-wins.
- If a fresh tenant loads the page and the server returns an empty list, the frontend's default content fills the editor immediately, but those defaults are not actually saved on the server until the operator hits save (or until the frontend's seed-on-first-load logic posts them). Until that first save, a second device opening the same tenant will also see "empty from server, defaults from frontend" — which means both devices look identical because they pull the same defaults, not because the server has any state yet.
- If the database row ever holds invalid JSON (disk corruption, a manual edit gone wrong), the server returns an empty list rather than crashing. The operator's old content is effectively lost in that case, but the editor stays usable and a new save will overwrite the bad row.
- A save of more than fifty blocks, a block content over 4096 characters, a title over 200 characters, or more than twenty subsections in one block is rejected with a 400 error and a message describing which limit was hit. This prevents a runaway paste from filling the database, but it also means a legitimately large block must be split into smaller ones.
- Unknown fields the browser might send (internal_prompt, debug_only, _admin_field, anything else) are silently dropped without an error. A buggy frontend that thinks it's saving extra metadata will get back a response with those fields missing — which is the intended behavior; the operator should treat the response as the source of truth for what was actually saved.
- A rollback to the previous code leaves the new database table in place (it's harmless when the rolled-back code doesn't read it). Any blocks already saved by Brief 262 stay in the row; the browser's local-storage fallback continues to work during a rollback window.

## What did NOT change

Marina's prompt was not touched. The Source of Truth is being stored on the server, but nothing in the agent's reply path reads from this new table yet — that wiring is left for a future brief. The existing info-updates, brand-profile, and knowledge-files tables and the prompts that read them are unchanged. The default content of the Source of Truth still lives in one place (the frontend) rather than being duplicated on the backend, which means the editor's starting state stays consistent with what operators have always seen. No customer-facing message handling, no booking flow, no email or WhatsApp routing was changed by this commit.
