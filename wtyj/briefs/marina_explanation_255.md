# EXPLANATION 255 — Email poller reloads email_thread_state.json at top of each poll iteration

## In one sentence
The email poller now re-reads its tracking file from disk every time it wakes up to check mail, so changes made by anything else on the system — the dashboard, operator wipes, the new flag-clearing helper — actually stick instead of being silently undone within a few minutes.

## What's changing and why

The email poller is the long-running background process that watches the inbox for new mail. To remember which email threads it has already seen, who has been escalated to a human, who has been archived, and so on, it keeps a tracking file on disk called the email thread state. Until this fix, the poller read that file exactly once when it first started up, kept a copy of it in its own memory, and then for the rest of its life only ever wrote that in-memory copy back to disk. Anything else on the machine that tried to edit the file directly — a dashboard button, a cleanup helper, a wipe script — would succeed for a moment, and then the very next time the poller saved, its stale memory would crush the change as if it had never happened.

Two real customer-visible problems came from this. First, when an operator resolved or deleted an escalated email thread on the dashboard, the "stuck in human-only mode" flag on that thread was supposed to be cleared by the helper added in the previous brief. The helper did its job correctly; the file on disk showed the flag was gone; but a few seconds later the poller would overwrite the file and the flag came back. Second, when the operator ran a full wipe of the email state file to start fresh, the file was empty on disk for about six minutes — until the next inbound email triggered the poller to save, which restored all nine old test threads from its in-memory copy. The fix makes the file on disk the single source of truth: every loop, the poller throws away its in-memory copy and reloads whatever is currently on disk before doing any work.

## Step by step — what the code does now

STEP: Top of each poll cycle, before anything else happens

Every time the poller wakes up to check the inbox (by default, every ten seconds), the very first thing it does now is open the tracking file from disk and load its contents into memory, replacing whatever it was holding from the previous cycle. If the file does not exist or is unreadable, it falls back to a clean empty structure. This happens before the poller reconnects to the mail server, before it scans for new messages, and before it runs its routine cleanup of stale threads.

STEP: Everything else in the loop, unchanged

After the reload, the poller does exactly what it did before — reconnects to IMAP if needed, fetches unread mail, processes each new message, updates the in-memory tracking structure, and saves the result back to disk. None of those steps were touched.

STEP: External edits now survive

Because the poller starts each cycle by reading disk, any change made between cycles by the dashboard's archive button, the dashboard's delete button, the flag-clearing helper from the previous brief, or an operator running a wipe script is the state the poller picks up. Its next save writes that picked-up state plus whatever new mail arrived this cycle — not a stale copy from minutes or hours ago.

STEP: The regression test

A new automated test runs the poller for exactly two cycles with a fake inbox. It seeds the tracking file with one thread that has a "stuck in human-only mode" flag. After the first cycle finishes, the test reaches in and rewrites the file from the outside to make it empty — simulating what the dashboard or a wipe would do. It then checks what the poller sees on cycle two. If the fix is in place, cycle two sees an empty file. If a future change ever deletes the reload line, cycle two will still see the original thread sitting in the poller's stale memory, and the test will fail loudly with a message pointing back to this brief.

STEP: Two more safety-net tests

The test file also gains two small tests that cover the rare cases where the tracking file is missing entirely or contains corrupted text at the moment the poller tries to reload it. In both cases the poller now falls back to an empty structure instead of crashing. These guard against the new reload step introducing a new crash mode if an operator deletes the file mid-wipe.

## Edge cases

- If the dashboard writes to disk during the same cycle as the poller — that is, after the poller's reload but before its save — the dashboard write is lost. The window is small (the poller only saves when a new email actually arrives, and the default cycle is ten seconds) but it is real. A proper fix would require file locking. The brief acknowledges this as a known limit and out of scope.

- If an operator wipes the tracking file in the middle of a cycle, the poller will not crash; the load returns an empty structure and the cycle proceeds normally. The next save writes that empty structure plus any new email seen this cycle.

- If the tracking file is briefly corrupt — for example mid-write from some future tool that doesn't use the safe atomic-rename pattern — the poller falls back to empty rather than crashing. On the next cycle it will reload again and pick up the file once it's whole.

- The poller's routine cleanup of stale threads runs inside each cycle. If a cleanup's deletions haven't been saved yet by the end of that cycle and the next cycle reloads disk, those deletions are dropped. This is acceptable because cleanup is idempotent — it will redo the same deletions on the next cycle against the fresh disk state.

- The fix adds one small file read per cycle (default every ten seconds). The tracking file is a few kilobytes today, so the overhead is negligible.

## What did NOT change

The poller's logic for reading email, generating replies, deciding what to escalate, and what to send to the customer was not touched. The save logic, the cleanup logic, the IMAP reconnect logic, and the atomic file-write mechanics are all unchanged. The previous brief's flag-clearing helper is unchanged — this fix is what makes that helper's writes survive. The dashboard's archive and delete endpoints are unchanged — this fix is what makes their writes survive too. The customer-facing reply behavior, the booking flow, and Marina's prompt are completely untouched.
