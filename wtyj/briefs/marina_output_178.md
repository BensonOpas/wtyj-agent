# OUTPUT 178 — Email normalization + strengthened cross-channel rule

## What was done

Fixed two chained bugs surfaced by Benson's live WhatsApp test with Calvin. Calvin emailed from `calvin@gaimin.io` (lowercase SMTP envelope), then WhatsApped and asked "did you receive my email?" — Marina replied "Still no access to the inbox from here, so I can't check emails" (the bug Benson circled). Traced two distinct root causes in prod DB state before touching code.

**Fix 1 — Case-insensitive email normalization at the state_registry layer.** Added `_normalize_identifier_value(type_, value)` helper in `state_registry.py` that lowercases email values (only — phone, wa_conversation_id, and future identifier types are stripped but not lowercased). Wired into `customer_lookup`, `customer_lookup_or_create`, and `customer_add_identifier` so every caller is covered automatically — no edit needed in `email_poller.py`, `social_agent.py`, or any future channel handler. The merge-detection path at `customer_add_identifier` (lines 2135-2146) now correctly finds a case-variant email on another customer row and triggers the merge instead of silently inserting a duplicate identifier.

**Fix 2 — Strengthened cross-channel rule, moved out of the customer file block.** Removed the `CROSS-CHANNEL REFERENCE RULE` from `_build_customer_file_block` (where it was silently omitted for empty/new customer files) and added a new `CROSS-CHANNEL CONTINUITY` block directly into the main system prompt f-string, pasted between `STATE MANAGEMENT` and `DATE AMBIGUITY RESOLUTION`. Same literal-text-in-template mechanism Brief 175 used for its date block. The new version has explicit forbidden phrases ("no access to the inbox", "I can't check emails", etc.) but scopes the ban to the cross-channel reference context — Marina is still allowed to say "I'll need to check with the team" for chef schedules, supplier details, legal questions, etc. Added a WRONG/RIGHT example using the exact phrasing from Benson's screenshot.

**Data repair script.** `wtyj/scripts/repair_customer_email_case.py` — standalone, idempotent. Iterates every email identifier, lowercases in place if no collision, or deletes + re-adds via `customer_add_identifier` if a case-variant already exists on another row (triggering the merge path). Ran via `docker exec` after deploy against production — merged Calvin rows 5/6 and Ash rows 2/3.

**Stale test cleanup.** `test_166_customer_file.py:218` asserted `"CROSS-CHANNEL REFERENCE RULE" in block` — that text is no longer in the customer file block after Fix 2. Deleted that one line with a comment pointing at the replacement assertion in `test_178_email_normalization.py`. The surrounding test function still has 4 other assertions; pytest still counts it as 1 test.

## Tests

**842 passing / 0 failures** (833 baseline + 9 new tests in `test_178_email_normalization.py`; the deleted assertion inside test_166's existing function does not change pytest's test count).

The 9 tests cover: normalization helper lowercases emails but not phones, idempotent, case-insensitive `customer_lookup`, case-insensitive `customer_lookup_or_create` returns the same row, `customer_add_identifier` merges case-variants (reconstructs Calvin's scenario), `CROSS-CHANNEL CONTINUITY` is in the prompt with a populated customer_file, `CROSS-CHANNEL CONTINUITY` is in the prompt EVEN when `customer_file=None` (the brand-new-customer case that the Brief 166 placement silently broke), and the repair script `main()` merges a reconstructed pre-fix buggy state AND is idempotent (second run is a no-op).

**Note:** the brief predicted 841 passing with 8 new tests. The actual count is 842 with 9 new tests because the output-reviewer caught that my first draft had silently swapped the brief's Test 8 (repair script idempotency) for a second normalization helper test. Added the missing test as a follow-up commit `dae1837` — refactored `repair_customer_email_case.main()` to accept an optional `db_path` parameter so the test can point at the state_registry's DB instead of the hardcoded container path.

## Deployment

Source committed `7baecd9` pushed to main. Background deploy rebuilds and restarts all three containers. Data repair script run after deploy via `docker exec wtyj-bluemarlin python3 /app/scripts/repair_customer_email_case.py` — merged the two existing prod dupe pairs.

## Unexpected

Three surprises during execution:

1. **Brief-reviewer caught the stale test assertion I missed.** I had NOT initially listed `test_166_customer_file.py` in the Files header, and my Step 4 (move the rule out of `_build_customer_file_block`) would have silently broken the existing `assert "CROSS-CHANNEL REFERENCE RULE" in block` at line 218. Reviewer flagged it as the top blocker. Patched in round 2 — added the file to the header, added Step 4b with explicit "delete line 218" instruction. **Principle reinforced:** any refactor that moves or deletes prompt-content text MUST grep the test suite for that exact string before shipping. Adding this to my pre-brief checklist.

2. **Brief-reviewer also caught a scope error in the forbidden-phrase ban.** My first draft banned "I don't have access to" as an absolute rule, but that legitimately applies to chef schedules, supplier details, legal questions, etc. — non-cross-channel contexts where "I'll need to check with the team" is the right answer. Patched round 2 to scope the ban: "FORBIDDEN ONLY in the cross-channel reference context". **Principle:** hard prompt bans should always be scoped to the specific context they're meant to prevent, never absolute.

3. **My test fixture assumed a `state_registry.init_db()` function that doesn't exist.** First test run failed 3/8 on `AttributeError: module 'shared.state_registry' has no attribute 'init_db'`. Check: `test_166_customer_file.py` uses a targeted `_cleanup(ids)` helper on the default DB instead of swapping DBs. Rewrote the Brief 178 fixture to match the same pattern (unique test-prefixed identifiers, try/finally cleanup). **Principle:** when a test file is the Nth for a given module, mirror the existing test file's fixture pattern instead of inventing a new one from memory.

4. **Silently swapped the brief's Test 8 and the output-reviewer caught it.** My first draft of `test_178_email_normalization.py` had 8 tests, but one of them was a second normalization helper test instead of the brief's specified Test 8 (repair script idempotency). The count matched (8) so I thought I was done, but the coverage set diverged — the repair script would have shipped to production without a single automated test. Output-reviewer caught it in the review. Added the missing test as follow-up commit `dae1837`, which also required refactoring `repair_customer_email_case.main()` to accept an optional `db_path` parameter so the test can point at the state_registry's DB instead of the hardcoded container path. **Principle:** reviewer agents are not just checking counts — they're checking that the specific items in the brief exist. When a brief lists N tests, the N new tests must match the brief's test descriptions item-by-item, not just be "N total tests". Adding this to my self-check: before saying "all tests in" compare the test function names against the brief's numbered list.

**What this fix does NOT solve (deferred to Brief 179 candidate):** Marina can't "magically already know" about Calvin's email on the very first WhatsApp hello. The customer file only contains what's been linked, and the link happens when Calvin mentions his email (explicit) or when some other signal creates the merge. Pre-linking via email signature phone extraction would close the gap — planned as a follow-up brief when Benson wants it.

## Calvin's flow, after this fix

- Calvin: "did you receive my email?"
- Marina: "Absolutely — what's the email address you sent from? I'll pull it up right now, and in the meantime — which trip were you looking at, and how many guests?"
- Calvin: "calvin@gaimin.io"
- Backend: `customer_add_identifier` lowercases → finds existing Row 5 → merges Row 6 into Row 5 → the next `customer_get_full` call sees the full history (email thread + WhatsApp thread)
- Marina (next turn): "Got it — I see your email about the Monday booking for [service + guests + date]. Want to confirm?"

One round-trip ask, then full history. Not zero-ask ("she already knows") but honest and architecturally correct.
