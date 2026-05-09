# EXPLANATION 236 — Test Suite Triage

## In one sentence
The test suite was cleaned up to remove tests that couldn't actually catch bugs — the live system behaves exactly the same.

## What's changing and why

The system has a large suite of automated checks that run before every deploy to catch broken code. An audit found that about a quarter of those checks were "fake" — they didn't actually test whether anything worked, they just searched the source files for specific words. A check that confirms the word "BlueFinn" doesn't appear in a file isn't really protecting anything; it just gives a green tick. Worse, a recent real bug slipped through eight days of green test runs because the test setup happened to share the same wrong assumption as the bug itself.

This cleanup deletes ten test files entirely, trims out specific fake checks from sixteen others, and updates the internal rulebook so future work doesn't re-create the same noise. No customer-facing code was touched. None of the agents (Marina or the social agent), no booking flow, no email handling, no prompts, no client data — none of it was modified.

## What an operator would notice
Nothing. Conversations, bookings, emails, and dashboards behave identically. The only visible difference is internal: when developers run the test suite, it now runs slightly leaner and the green checkmarks mean a little more than they did before.

## What did NOT change
Marina's prompt, the booking flow, customer data handling, the dashboard, email polling, and every production code path are completely untouched. This was a housekeeping pass on the developer-side test files only.
