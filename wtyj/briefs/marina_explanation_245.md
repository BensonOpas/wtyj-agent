# EXPLANATION 245 — Phase 1a Unboks QA/customer simulator (foundation + 10 seed scenarios + dry-run runner)

## In one sentence

A new standalone testing tool ships that lets an operator run a library of pretend customer messages against a structural checker and get back a printed and saved report — but it does not yet talk to Marina, send real messages, or touch any production data.

## What's changing and why

This is purely a tooling addition. Nothing in the live customer pipeline changes — Marina still answers the unboks tenant's messages exactly as before, the dashboard behaves the same, and the deploy scripts are untouched. What is new is a separate folder of operator tools that holds ten written-out "fake customer" scenarios (a polite booking request, a vague booking request, a price question, an hours question, an angry complaint, an explicit request for a human, a mid-thread context switch, an archive-test message, a Spanish-speaking customer, and a spam message) plus a small command-line program that can read those scenarios and confirm they are well-formed.

The reason it ships now is that seven changes landed against the unboks tenant in a single day — tenant guards, alert wording, the Zernio operator route, the appointment dispatcher, the operator confirm endpoint, dashboard deep-links, and the identity-leak fixes — and there was no scenario-by-scenario regression check that walked all of those flows from a customer's perspective. This brief lays the foundation. A later brief turns the foundation into a real end-to-end runner that actually sends the fake messages through Marina; the brief after that expands the scenario count from ten up to fifty.

## Step by step — what the code does now

THE TEN SAVED SCENARIOS

Each scenario is a small block of writing that names a test, picks a category (booking, faq, escalation, reply-thread, dashboard-action, or edge-case), picks a channel (email, WhatsApp, Instagram, Facebook, or Messenger), picks a persona label so a human can read it (for example "angry complaint customer" or "Spanish speaking customer"), supplies one or more pretend customer messages, and writes down what should and should not happen. Every pretend customer message starts with the literal text "[QA TEST]" so that if one ever leaks into production by accident, an operator can spot it immediately. Every scenario also writes down two things the customer reply must never contain — the internal sender mailbox address and the em-dash character — which are the identity rules that landed in Brief 244. Finally, each scenario carries a "Phase 2 notes" line that describes what a future live runner would need to verify (for example, that the reply is in Spanish, or that an alert row appears for the angry-complaint case, or that the archive button preserves the conversation row).

THE COMMAND-LINE RUNNER — DEFAULT MODE

When an operator runs the runner with no flags, the tool reads the scenarios file, parses it as JSON, and walks each scenario in turn. For each one it checks the shape: that the test ID exists and is in capitals, that the category is one of the six allowed values, that the channel is one of the five allowed values, that an email scenario also carries a sender mailbox, that the messages list is non-empty and every entry begins with the "[QA TEST]" prefix, that the expected-results block is present, and that the must-not-contain list includes both identity rules. A scenario that survives all of those checks is recorded as "passed dry-run." A scenario that fails any check is recorded as "failed dry-run" along with the exact reason. Every passed scenario is also recorded as "pending Phase 2," because the dry-run cannot yet verify the live behavior — only the shape of the test itself.

THE COMMAND-LINE RUNNER — REPORT WRITING

After walking the scenarios, the tool creates a fresh folder under "reports" stamped with the current date and time in UTC. Into that folder it writes three files. The first is a markdown summary that prints the total count, the passed count, the failed count, the pending-Phase-2 count, the count of failures broken down by severity (escalation and dashboard-action failures count as critical; booking and reply-thread count as high; FAQ counts as medium; edge-case counts as low), the list of any critical failures by name, the aggregated list of Phase-2 to-do notes, the count of passed scenarios per category, and a short note about the missing infrastructure that Phase 2 still needs. The second is a JSON file containing the full machine-readable result for every scenario. The third is a plain text file listing one failed scenario per line, or an empty file if everything passed. The tool prints a short summary to the screen and exits cleanly if everything passed structurally, or with an error code if any scenario failed.

THE COMMAND-LINE RUNNER — FILTER MODE

When an operator runs the tool with the filter flag, it first tries to match the supplied word against a scenario category (so "filter booking" runs only the two booking scenarios). If no scenario matches the category, it tries to match against a single test ID (so a specific test ID runs only that one scenario). Everything else works the same as default mode, including the report writing.

THE COMMAND-LINE RUNNER — VALIDATE-ONLY MODE

When an operator runs the tool with the validate-only flag, it walks the scenarios and prints any failures to the error stream, but does not create a report folder. This is the cheap fast check for an operator who has just edited the scenarios file and wants to confirm the shape is still correct before running the full report.

THE COMMAND-LINE RUNNER — LIVE MODE PLACEHOLDER

When an operator runs the tool with the live flag, it does not run anything live. It prints a short message saying "Phase 2 not implemented yet — live execution requires a safe message-injection endpoint that does not exist as of Brief 245" and exits with a distinct error code (two, not one) so that an automation script can tell the difference between "a scenario failed" and "you asked for a feature that does not exist yet."

THE README

A short documentation file ships alongside the tool that covers how to run it, what it does and does not do today, what the safety rules are (default is dry-run, every message carries the "[QA TEST]" prefix, the live flag is a placeholder), where the reports go, how to add a new scenario, and what the Phase 1b and Phase 2 roadmap items still need.

THE GITIGNORE

The reports folder is added to the project's gitignore list so that the timestamped report directories generated by each run never get checked into the repository.

THE FIVE NEW TESTS

Five new automated tests exercise this tool. The first opens the scenarios file, parses it, and confirms exactly ten entries are present (this number bumps to fifty when Phase 1b lands). The second walks every scenario and confirms every customer message starts with the "[QA TEST]" prefix. The third walks every scenario and confirms each must-not-contain list includes both identity rules. The fourth actually invokes the runner as a real subprocess command and confirms that the report folder, the summary file, and the JSON results file are all created and parseable. The fifth invokes the runner with the validate-only flag and confirms it exits cleanly. The full project test suite now stands at 1055 passing, zero failing.

## Edge cases

- The runner cannot import anything from the production agents folder or the dashboard folder. This is a deliberate structural decoupling — even if an operator accidentally adds bad code to the runner, it has no path to call Marina or trigger a real reply.
- If the scenarios file is missing or malformed JSON, the runner exits with an error before doing anything else.
- If the operator passes a filter word that matches neither a category nor a test ID, the runner produces a report covering zero scenarios. This is treated as a clean exit, not a failure.
- The "passed" count and the "pending Phase 2" count are always equal in this phase, because every scenario that passes the shape check still needs the live runner to verify the actual behavior. This is by design and the report makes it explicit.
- The live flag exits with code two, distinct from the code one used for "scenarios failed." Automation scripts that want to treat "feature not implemented" differently from "a test failed" can rely on this difference.
- The tool currently writes a fresh timestamped report folder on every run and never cleans up older folders. Disk usage is the operator's responsibility.
- Multilingual handling is represented by exactly one Spanish scenario in the seed set. A Dutch scenario was considered but not included; Phase 1b will broaden the multilingual coverage.
- The dashboard-action scenario only documents the expected shape of an archive test. The runner cannot actually click the dashboard archive button — that work belongs to Phase 2.
- The scenarios file uses JSON, not YAML. This means multi-line customer messages have to use the `\n` escape sequence rather than natural line breaks. If scenarios become unwieldy, a future brief may migrate to YAML.

## What did NOT change

Marina's prompt was not touched. The booking flow was not touched. The customer message handling pipeline, the dispatcher, the operator confirm endpoint, the alert wording, the Zernio route, the dashboard deep-links, and the identity-leak fixes from Briefs 238 through 244 are all preserved exactly as they were. No tenant configuration changed. No deploy script changed. No production database write happens when the runner is executed. The new tool sits in its own folder under "tools" alongside the existing operator CLI and the control panel, and has no path into the live customer pipeline. Briefs 246 and beyond will expand the scenario library from ten to fifty; a separate Phase 2 brief will add the live message-injection endpoint, the Marina mock harness, the dashboard action verifier, and a cleanup mode that purges QA conversations from the database after a run.
