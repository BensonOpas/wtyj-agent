# EXPLANATION 216 — Your Info / Settings + Your Info Updates

## In one sentence

The operator can now edit basic business info (name, phone, location, hours, languages) directly from the dashboard, and can also post temporary or permanent notes that Marina treats as authoritative current context — without anyone touching the server.

## What's changing and why

Until today, every change to the business name, support email, phone number, or operating days required Benson to log into the server, edit the client config file by hand, and restart the container. SR (the operator-side dashboard) now has a Settings page with a "Your Info" panel where the operator types those values into a form and saves. The system writes those changes back to the same config file Marina has always read — so the dashboard becomes a friendlier face on the same source of truth, instead of a competing one.

The second half ships a separate concept called "Your Info Updates." This is a place for the operator to post short notes — a Valentine's Day promo, "we're closed Christmas Day," "new pickup location for the week" — that Marina should treat as authoritative current context when she replies to customers. Notes come in two flavors: permanent (stays until the operator deletes it) and scheduled (active only between a start date and end date). The scheduled flavor is the big win: the operator can write a Valentine's promo on January 1 with dates of February 13-14, and Marina will automatically use it those two days and stop using it on the 15th — no code change, no deploy.

This second feature is gated per-tenant behind an opt-in flag and is off by default, so existing tenants see no behavior change until someone flips it on.

## Step by step — what the code does now

WRITING A BUSINESS FIELD TO DISK

When the operator saves a change in the Your Info form, the system loads the current business config from disk, replaces the one field they edited, writes the whole thing to a temporary file in the same directory, then renames the temp file over the real one in a single all-or-nothing step. If anything fails before the rename, the original config file is untouched. After a successful write, the in-memory cache is cleared so the very next read picks up the new value. The system also confirms the field name is one of the eight approved editable fields; anything else is rejected.

LISTING WHAT'S EDITABLE

When the operator opens the Your Info page, the dashboard fetches just the eight whitelisted fields — name, email, support email, phone, WhatsApp, location, languages, operating days. Anything more sensitive (services, prices, FAQ, booking rules) is intentionally not exposed for editing, because a bad edit in those nested areas could break Marina's booking flow.

SAVING WHAT THE OPERATOR CHANGED

When the operator submits the form, the system only updates the fields they actually filled in. Fields left blank are left alone. If the operator submits something that isn't on the editable list, the form layer silently drops it before it ever reaches the file. If multiple fields update successfully but one fails to write, the system reports which ones failed.

CREATING AN INFO UPDATE

When the operator types a note in the Your Info Updates panel and saves, the system writes a new row in a small table with the text, a category tag (general, offer, holiday, hours, pricing, or other), an active flag, optional start and end dates, and timestamps. If they leave the dates blank, it's permanent. If they fill them in, it's scheduled.

LISTING ALL INFO UPDATES FOR THE OPERATOR

The dashboard's management list shows every info update — active or not, in-window or not — newest first, so the operator can see what's queued, what's running, and what's expired.

DELETING AN INFO UPDATE

When the operator clicks delete, the row is removed permanently. If the row doesn't exist, the system reports not-found instead of silently succeeding.

PICKING WHICH UPDATES MARINA SEES RIGHT NOW

Whenever Marina is about to reply to a customer, the system asks for the currently-active updates. An update counts as active if its active flag is on AND either it has no dates (permanent) or today falls inside its window. Half-open windows work too: "active from March 1" with no end date stays on forever once March 1 passes; "active until March 15" applies from now until March 15. Anything outside the window is filtered out before Marina ever sees it.

INJECTING UPDATES INTO MARINA'S CONTEXT

If the tenant has opted in to the feature flag, the system builds a labeled block titled "ACTIVE BUSINESS UPDATES" that lists each currently-active note as a bullet, tagged by its category. The block tells Marina to treat these as authoritative current context that overrides older default info when relevant. The block is slotted into Marina's prompt right next to the existing approved-answers block. When the feature is off or there's nothing active, the block is empty and the surrounding prompt spacing collapses cleanly — Marina's prompt looks identical to before.

## Edge cases

- If the disk write fails halfway through (power loss, full disk), the original config file is untouched because the rename is the last step. The cache stays valid because it's only cleared after a successful rename.
- If the operator submits an empty save form (no fields filled in), the system rejects it with a clear error rather than writing an empty change.
- If the operator types a category tag that isn't on the approved list (general, offer, holiday, hours, pricing, other), the system silently stores it as "other" instead of erroring.
- If the operator creates a scheduled update with start and end on the same day, the update is active that one day only. Date comparisons use today's UTC date as a string — operators working in other time zones may see updates flip on or off a few hours earlier or later than their local midnight.
- If the operator creates a scheduled update with end date BEFORE start date, the update will never appear active. The system does not warn about this.
- If the operator marks an update inactive (active flag off), it's hidden from Marina even if today is inside its window. The dashboard list still shows it so the operator can re-enable.
- If two saves to the Your Info page land at almost the same instant, one will overwrite the other. The atomic rename guarantees neither write is corrupted, but the later write wins. There is no merge.
- If the tenant feature flag for info updates is off, the operator can still create, list, and delete info updates from the dashboard. They simply don't reach Marina's prompt. This is intentional — the operator can stage updates before flipping the feature on.
- If something goes wrong reading the active updates from the database (locked file, missing table), the system returns an empty block rather than crashing Marina's reply.
- If an info update's text is blank or whitespace-only, it's skipped during prompt building so Marina doesn't see an empty bullet.

## What did NOT change

Marina's persona, her core writing style, the booking flow, the customer file block, the approved-answers block from Brief 219, and the way she calls the language model — none of these changed. The new updates block is added next to existing context blocks, not in place of them. Customers see no change in how Marina replies unless and until the operator both opts in to the feature flag AND posts an active note. The eight editable fields are flat business info only; the sensitive nested areas (services, payment, FAQ, booking rules) remain code-and-SSH-only on purpose.
