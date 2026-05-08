# EXPLANATION 229 — Data retention settings (storage + endpoints, cleanup deferred)

## In one sentence
Operators (through SR's dashboard) can now save and load data retention preferences against the real backend instead of the browser's local storage, but the actual cleanup that those preferences would drive is not running yet — and the backend says so honestly instead of pretending it works.

## What's changing and why

SR built a Data Retention & Archive settings page on the dashboard so operators can decide, per tenant, how long active conversations stay visible before being archived, how long archives stick around before being purged, what happens at the end of the retention window (anonymize, delete, or keep forever), whether AI-approved learning notes are spared, and how long audit logs are kept. Until now those choices lived only in the operator's browser — close the tab on a different machine and the values reset to defaults. There was no backend listening at all.

This change adds the backend storage and the two endpoints SR's frontend was already calling. Settings now persist on the server, survive browser refreshes, and travel with the tenant. What this change does NOT do is run the cleanup work those settings describe. Archiving conversations, deleting expired customer records, and exporting customer data are still not happening — those need a careful, separately-tested job that walks real customer data, and they are explicitly deferred to a future brief. The three "do it now" buttons on the settings page (Archive Now, Export, Delete Customer Data) hit the backend, get a clean "not implemented yet" answer, and the frontend already knows how to display that gracefully. Nothing in the system is silently failing or pretending to have done work it didn't do.

## Step by step — what the code does now

NEW STORAGE TABLE FOR RETENTION SETTINGS

The first time the system starts up after this change, it creates a fresh table inside its database called "data retention settings." That table is built to hold exactly one row — there is only ever one retention policy per tenant, and it lives in the row pinned to a fixed identifier of 1. The row has columns for the active-inbox archive threshold (in days), the archive retention window (in months), the end-of-retention action chosen (anonymize, delete, or keep), a yes/no flag for whether approved learnings should be kept regardless of the policy, an audit log retention window (in months), and a timestamp for when the row was last touched. The two duration columns can be left empty, which represents "never archive" or "never delete." If the table already existed from a previous run, the system leaves it alone.

LOADING THE CURRENT SETTINGS

When the dashboard asks the backend for the current retention settings, the system opens the database, reads the single row at identifier 1, and shapes the answer the way SR's frontend expects (camel-cased field names). If the row has never been written — fresh tenant, never visited the settings page — the system synthesizes a default answer instead: 90-day inbox archive, 24-month archive retention, anonymize at end of retention, keep approved learnings on, 24-month audit log. Those defaults match the constants SR ships in his frontend exactly, so the dashboard sees the same numbers whether it reads from server or falls back to its old behavior. The answer always includes a "policy active" flag, which is hardcoded to false. That flag tells the frontend "your settings are stored, but the automation that acts on them is not running yet" — and the frontend already has copy that says that to the operator.

SAVING NEW SETTINGS

When the operator changes values on the settings page and the dashboard sends them to the backend, the system first runs every value through a strict checklist before it even reaches the database. The active-inbox threshold has to be 30, 60, 90, 180, or empty; the archive retention has to be 12, 24, 36, 60, or empty; the end-of-retention action has to be one of "anonymize," "delete," or "keep"; the keep-approved-learnings flag has to be true or false; and the audit log retention has to be 12, 24, 36, or 60. Any value outside those allowed sets gets rejected with a clear 422 error before any database write happens — the operator's bad input never gets stored. If everything passes, the system either inserts a brand new row at identifier 1 or replaces the existing one, stamps it with the current time, and commits. It then re-reads the row and hands the saved values back so the dashboard can confirm what stuck.

THE THREE ACTION ENDPOINTS THAT DO NOTHING (HONESTLY)

The settings page also has three buttons that ask the backend to actually do retention work right now — archive-now, export, and delete-customer-data. All three are wired up to receive the click, but each one immediately responds with a 501 "not implemented" status and a plain-English message that explains the cleanup automation has not shipped yet, that the settings ARE being stored, and that this work will arrive in a future brief. SR's frontend was designed against the rule "no fake success" — so it sees the 501, reads the message, and shows the operator that the action isn't available rather than flashing a green checkmark for nothing.

## Edge cases

- If a tenant has never visited the settings page, the GET endpoint returns the default values without ever creating a database row. The first PUT is what materializes the row. This is intentional and matches how SR's frontend defaults work.
- If the operator picks an out-of-range value (say, 45 days for the inbox threshold), the save is rejected with a 422 error and nothing in the database changes. The previously-saved values stay intact.
- The "policy active" flag in every response is currently hardcoded to false. It will stay false until a future brief ships the real cleanup job. The frontend uses this flag to display honest copy to the operator. Anyone reading the API directly should not interpret saved settings as proof that retention is being enforced.
- If someone clicks Archive Now, Export, or Delete Customer Data, nothing happens to any customer data. The button hits the backend, the backend says "not implemented," the frontend tells the operator. No silent partial work, no half-cleaned data.
- The retention table is created with "if not exists" semantics, so reverting this commit does not drop the table. If the change is rolled back, the endpoints disappear and the frontend falls back to browser-local storage on its own. The empty table remains behind harmlessly.
- The save helper trusts its caller to validate values — the strict checklist lives at the API boundary. If a future caller bypasses that boundary and writes garbage directly through the helper, the database will accept it. Today there is only one caller, and it validates first.

## What did NOT change

Marina's prompt, the booking flow, customer data handling, the WhatsApp/email/DM pipelines, and the existing settings tables (alerts, info updates, approved learnings) are all untouched. No customer conversations are being archived, anonymized, deleted, or exported as a result of this change — none of those code paths exist yet. The only thing that runs differently is that the dashboard's Data Retention page now has a real backend it can read from and write to.
