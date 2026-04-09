# BRIEF 178 — Email identifier normalization + strengthened cross-channel rule
**Status:** Draft | **Files:** `wtyj/shared/state_registry.py`, `wtyj/agents/marina/marina_agent.py`, `wtyj/tests/marina/test_166_customer_file.py` (one assertion update), new `wtyj/scripts/repair_customer_email_case.py`, new `wtyj/tests/marina/test_178_email_normalization.py` | **Depends on:** Brief 166 (cross-channel customer file) | **Blocks:** Brief 179 (email signature pre-linking)

**Note on file scope:** `email_poller.py` and `social_agent.py` are NOT modified directly — they already call `customer_lookup_or_create` / `customer_add_identifier`, so normalizing inside those state_registry functions means every existing call site is automatically covered with no caller-side edit.

## Context

Benson tested Marina live from WhatsApp BlueMarlin Tours Curaçao. Flow:

1. Calvin sent an email from `calvin@gaimin.io` → `email_poller.py` created customer Row 5 with identifier `(email, calvin@gaimin.io)`.
2. ~1 minute later, Calvin messaged the same agent on WhatsApp ("Hi how are you?", then "I am trying to do a booking for monday, did you receive my email?") → `social_agent.py` created a NEW customer Row 6 with identifier `(wa_conversation_id, 69d41ae77d2c605d08114697)`. No link to Row 5.
3. Marina replied (circled by Benson as the bug): **"Still no access to the inbox from here, so I can't check emails. But let's get your Monday booking done right now — which trip are you looking at, and how many guests?"**
4. Calvin later typed `Calvin@gaimin.io` (capital C) directly in WhatsApp. `marina_agent.process_message` extracted it as `fields.email`, `social_agent.py:323` called `state_registry.customer_add_identifier(6, "email", "Calvin@gaimin.io")`. That function's merge path (state_registry.py:2135-2146) is supposed to detect "this email is already on another customer row, merge them" — but the lookup at line 2136 is case-sensitive, so `Calvin@gaimin.io` didn't match Row 5's `calvin@gaimin.io`, so **no merge happened**. Row 6 got a second email identifier and the two rows stayed split.

Production DB state verified on VPS at the time of writing:

```
customer_identifiers WHERE type='email':
  Row 2: ash9772@gmail.com
  Row 3: Ash9772@gmail.com    ← case dupe
  Row 5: calvin@gaimin.io
  Row 6: Calvin@gaimin.io     ← case dupe
```

Two case-dupe pairs in production, both silently split across two customer rows each.

**Root cause (primary):** email identifier case sensitivity. `customer_lookup`, `customer_lookup_or_create`, and `customer_add_identifier` all store and match email values byte-for-byte. Per RFC 5321 §2.3.11, the local-part of an email is technically case-sensitive but the domain is not; in practice every real mail system normalizes to lowercase for comparison. Our state_registry doesn't.

**Root cause (secondary):** Marina's `CROSS-CHANNEL REFERENCE RULE` at `marina_agent.py:291-298` says "Do NOT claim you have no access to other channels; you do" but Claude slipped through the wording — "still no access to the inbox from here, so I can't check emails" is technically a different phrasing than "no access to other channels". The rule needs explicit forbidden phrases AND a prominent placement.

**Root cause (tertiary):** the cross-channel rule is embedded inside the customer file block (`marina_agent.py:258-299`), so when `customer_file` has no id (first-ever contact, lookup failure), the rule is silently omitted from the prompt. A new customer asking "did you get my email?" on their very first WhatsApp message gets zero guidance.

**Why this matters:** the whole point of Brief 166 (cross-channel customer file) was so Marina could see the same customer across WhatsApp + email + DMs. Case sensitivity silently defeats that architecture — the data is there but siloed on the wrong row, and Marina's workaround phrasing makes it look like a bigger capability gap than it actually is. Benson saw Marina say "I can't check emails" and reasonably concluded the feature was broken.

## Why This Approach

Three fix options were considered:

1. **(CHOSEN) Fix the root cause + the symptom + the prompt structure.** Normalize emails at the state_registry layer (lowercase before storage and lookup), repair existing dupes via a one-shot migration script, move the cross-channel rule out of the customer file block into a more prominent always-on location with explicit forbidden phrases.

2. **Fix only the symptom (prompt rewording).** Strengthen Marina's rule so she asks to link instead of explaining limitations. Rejected — the underlying data silo would still exist. When Calvin provided his email in message 4, the merge would STILL fail because of case sensitivity. Marina would ask correctly, but the merge would silently drop the link and she'd never see the full history.

3. **Add active email extraction from message text before Claude call + email signature parsing in email_poller.** The "pre-linking" path — so Marina would already know about the email before Calvin even mentions it. Rejected FOR THIS BRIEF — it's real work (regex-based contact info extraction has false positives, email signature formats vary wildly), needs empirical testing against real inbound email corpus, and Benson asked me to ship a narrow root-cause fix. Parked as Brief 179 candidate.

**Tradeoff carried:** this fix does NOT make Marina "magically already know" about the customer's email on their first WhatsApp hello. It makes her ASK for the email address to link, and once they provide it, the merge works correctly and she has full history on the next turn. One round-trip ask, not zero. The pre-linking zero-ask experience is Brief 179.

**Why normalize at the state_registry layer and not higher up:** it's the single chokepoint. Both `email_poller.py` and `social_agent.py` call `customer_lookup_or_create` and `customer_add_identifier`, plus any future channel handlers (IG DM, FB DM, Twitter DM) will too. Normalizing inside the state_registry functions means every caller is automatically covered with zero caller-side discipline. If I normalized at the caller layer, I'd need to add the same `.lower()` dance to every call site in every agent and every future agent.

## Instructions

### Step 1: Add a normalization helper to `state_registry.py`

Add a module-level helper function near the top of the customer-file section (around `state_registry.py:2003`, just under the `# ==================== Brief 166: Cross-channel customer file ====================` header):

```python
def _normalize_identifier_value(type_: str, value: str) -> str:
    """Brief 178: normalize identifier values for storage and lookup so case
    variants don't create silos. Email is case-insensitive per RFC 5321 in
    practice. Phone is stripped. Other identifier types are stripped only.
    Returns the normalized value. Idempotent."""
    if not value:
        return ""
    normalized = value.strip()
    if type_ == "email":
        normalized = normalized.lower()
    return normalized
```

No other identifier types need normalization in this brief. `wa_conversation_id` is already canonical hex from Zernio. `phone` values arriving from Zernio are already normalized to digits. Future identifier types (IG user id, FB user id, Twitter handle) can add their own normalization here as they're added.

### Step 2: Wire the helper into the three lookup/create/add functions

**`customer_lookup` at `state_registry.py:2005`:** add normalization before the SQL query.

```python
def customer_lookup(type_: str, value: str):
    """Brief 166: look up a customer by an identifier. Returns None if not found.
    Brief 178: normalizes value (e.g. lowercases email) before lookup."""
    if not type_ or not value:
        return None
    value = _normalize_identifier_value(type_, value)
    if not value:
        return None
    conn = _get_conn()
    # ... rest unchanged, but the query now uses the normalized value
```

Remove the inline `value.strip()` from the SQL parameter (line 2016) since `_normalize_identifier_value` already strips.

**`customer_lookup_or_create` at `state_registry.py:2027`:** add normalization before the existing lookup and insert.

```python
def customer_lookup_or_create(type_: str, value: str, display_name: str = "") -> dict:
    """Brief 166: look up a customer by identifier, or create a new row if not found.
    Brief 178: normalizes value (e.g. lowercases email) before lookup/insert."""
    if not type_ or not value:
        raise ValueError("type and value required")
    value = _normalize_identifier_value(type_, value)
    if not value:
        raise ValueError("normalized value empty")
    existing = customer_lookup(type_, value)
    # ... rest unchanged; value is already normalized so the INSERT at line 2056 is safe
```

Remove the inline `value.strip()` from line 2056 — already normalized.

**`customer_add_identifier` at `state_registry.py:2126`:** add normalization at the top so both the dupe-detection lookup AND the insert use the normalized form.

```python
def customer_add_identifier(customer_id: int, type_: str, value: str) -> dict:
    """Brief 166: add a new identifier to an existing customer. Handles the cross-channel
    merge case: if the (type, value) already belongs to a DIFFERENT customer, merge them.
    Brief 178: normalizes value (e.g. lowercases email) before lookup/insert.
    Returns {"action": "added" | "merged" | "already_linked" | "noop", "customer_id": int}."""
    if not customer_id or not type_ or not value:
        return {"action": "noop", "customer_id": customer_id}
    value = _normalize_identifier_value(type_, value)
    if not value:
        return {"action": "noop", "customer_id": customer_id}
    now = datetime.now(timezone.utc).isoformat()
    # ... rest unchanged; the value is normalized so the dupe-lookup at line 2137 and
    # the INSERT at line 2151 both use the same normalized form
```

Remove the inline `value = value.strip()` on line 2132 — redundant, handled by the helper.

### Step 3: Data repair migration script

Create `wtyj/scripts/repair_customer_email_case.py`. Standalone script meant to be run once via `docker exec` after the new code deploys. Idempotent — can be re-run safely.

```python
#!/usr/bin/env python3
"""Brief 178: repair existing case-variant email identifiers in customer_identifiers.

Safe to run multiple times. Reads every email identifier, lowercases it, and calls
customer_add_identifier with the lowercased value — which triggers the Brief 178
merge path if a case-variant already exists on another row. After the sweep,
the `display_name` field on the surviving row is preserved; absorbed rows are
marked active=0 by the existing customer_merge function."""

import sqlite3
import sys
import os

# Add /app to path so we can import state_registry
sys.path.insert(0, "/app")

from shared import state_registry


def main():
    conn = sqlite3.connect("/app/data/state_registry.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, customer_id, value FROM customer_identifiers WHERE type='email' ORDER BY id"
    ).fetchall()
    conn.close()

    print(f"Found {len(rows)} email identifiers to inspect")
    changed = 0
    merged = 0
    for r in rows:
        original = r["value"]
        normalized = original.strip().lower()
        if original == normalized:
            continue
        # This row has a mixed-case email. Two cases:
        #   (a) The lowercased form doesn't exist anywhere else → we just need to
        #       UPDATE this row's value to lowercase. Safe, no merge.
        #   (b) The lowercased form exists on ANOTHER customer row → deleting this
        #       row's mixed-case identifier and calling customer_add_identifier on
        #       the lowercased form will trigger the merge path.
        conn = sqlite3.connect("/app/data/state_registry.db")
        other = conn.execute(
            "SELECT customer_id FROM customer_identifiers WHERE type='email' AND value = ?",
            (normalized,)
        ).fetchone()
        conn.close()
        if other is None:
            # Case (a): no collision, just lowercase in place
            conn = sqlite3.connect("/app/data/state_registry.db")
            conn.execute(
                "UPDATE customer_identifiers SET value = ? WHERE id = ?",
                (normalized, r["id"])
            )
            conn.commit()
            conn.close()
            changed += 1
            print(f"  row.id={r['id']} customer_id={r['customer_id']} lowercased in place: {original} -> {normalized}")
        else:
            # Case (b): collision. Delete this mixed-case identifier, then call
            # customer_add_identifier with the lowercased form on the same customer.
            # That triggers the merge path in customer_add_identifier.
            conn = sqlite3.connect("/app/data/state_registry.db")
            conn.execute("DELETE FROM customer_identifiers WHERE id = ?", (r["id"],))
            conn.commit()
            conn.close()
            result = state_registry.customer_add_identifier(
                r["customer_id"], "email", normalized
            )
            if result.get("action") == "merged":
                merged += 1
                print(f"  row.id={r['id']} customer_id={r['customer_id']} MERGED via {normalized}: {result}")
            else:
                print(f"  row.id={r['id']} customer_id={r['customer_id']} re-added {normalized}: {result}")

    print(f"\nDone. lowercased={changed} merged={merged}")


if __name__ == "__main__":
    main()
```

Run after deploy via:
```
ssh root@108.61.192.52 "docker exec wtyj-bluemarlin python3 /app/scripts/repair_customer_email_case.py"
```

### Step 4: Move the cross-channel rule out of the customer file block into the main system prompt

**Current state:** `marina_agent.py:291-298` has the `CROSS-CHANNEL REFERENCE RULE` nested inside `_build_customer_file_block` as a literal appended to the `lines` list. This means it's only emitted when the customer file has an id (line 263 early-return). New customers on their first message never see the rule.

**Change summary:** delete the rule from `_build_customer_file_block`; insert a stronger version directly into the triple-quoted f-string literal returned by `_build_system_prompt` at `marina_agent.py:454-...`. The new text is pasted AS LITERAL TEXT between the existing `STATE MANAGEMENT` paragraph (line 490) and the `DATE AMBIGUITY RESOLUTION` heading (line 492). No new f-string variable, no refactor — just a text insert inside the existing template string, same mechanism Brief 175 used for its DATE AMBIGUITY block.

**Exact edit A — delete from `_build_customer_file_block`:**

In `_build_customer_file_block` (lines 258-299), remove the trailing `lines.append(...)` that inserts the CROSS-CHANNEL REFERENCE RULE. Specifically, delete lines 291-298:

```python
    lines.append(
        "\nCROSS-CHANNEL REFERENCE RULE: if the customer references a channel or interaction "
        "you do NOT see in the CUSTOMER FILE above (e.g. 'did you get my email?', 'I booked "
        "last week'), ask ONE short question to link them — 'sure, what's your email or booking "
        "reference?' — and wait for their next reply. Do NOT claim you have no access to other "
        "channels; you do. Once they share an identifier you can look up, you will have their "
        "full history."
    )
```

The function should now end with the `summary` block and `return "\n".join(lines)` directly.

**Exact edit B — insert into the system prompt template string:**

In `_build_system_prompt`'s return f-string, find the existing literal:

```
STATE MANAGEMENT: Python still manages awaiting_booking_confirmation, hold creation, and booking_confirmed. Do not set these flags yourself unless an ACTION instruction in the user prompt explicitly tells you to.

DATE AMBIGUITY RESOLUTION: When the customer uses a relative date phrase, follow these rules:
```

Insert the new CROSS-CHANNEL CONTINUITY block as literal text between those two paragraphs — NOT as a Python variable, just text pasted inside the triple-quoted string. The new text to paste:

```
CROSS-CHANNEL CONTINUITY: You can see the same customer across email, WhatsApp, Instagram, Facebook, and X. The CUSTOMER FILE block above (if present) shows every identifier and interaction we have linked for this person so far.

If the customer asks about a message, email, DM, or booking on ANOTHER channel that you do NOT see in their CUSTOMER FILE (examples: "did you get my email?", "I messaged you on Instagram last week", "I booked yesterday", "check the email I just sent"), you MUST:

1. Acknowledge warmly and pivot to helping them right now.
2. Ask ONE short question to link the missing channel. Example phrasings:
   - "Absolutely — what's the email address you sent from? I'll pull it up."
   - "Happy to help — do you have the booking reference handy?"
   - "Got it — what's the name or email you used when you messaged us?"
3. Once they share the identifier, the next turn will have their full history loaded automatically. Do NOT try to look it up yourself mid-reply.

WHEN REPLYING TO A CROSS-CHANNEL REFERENCE QUESTION (e.g. "did you get my email?", "I messaged you before"), you MUST NEVER use any of these phrasings — they leak internal architecture and make the business look broken:
  - "I don't have access to the inbox / email / messages / system"
  - "I can't check emails from here"
  - "I can't see your email / message"
  - "no access to the inbox"
  - "from here I can't"
  - "my system doesn't show"
  - "I'm not able to access"
  - "unfortunately I can't see that"

These phrases are FORBIDDEN ONLY in the cross-channel reference context. In other contexts (e.g. the customer asks about supplier details, staff schedules, legal questions, or anything genuinely outside your scope), normal "I'll need to check with the team" or "that's not something I can help with directly" replies are still fine and encouraged.

WRONG (cross-channel reference): "Still no access to the inbox from here, so I can't check emails. But let's get your booking done — which trip?"
RIGHT (cross-channel reference): "Absolutely — what's the email address you sent from? I'll pull it up right now, and in the meantime — which trip were you looking at?"
```

The forbidden-phrase ban is **scoped to the cross-channel reference context only**. This prevents collision with legitimate "I don't know that thing outside my scope" replies (chef schedule, supplier info, legal questions, etc.) that Marina legitimately needs to be able to make.

### Step 4b: Update the stale test assertion

`wtyj/tests/marina/test_166_customer_file.py:218` asserts `"CROSS-CHANNEL REFERENCE RULE" in block` where `block` is the return of `_build_customer_file_block`. After Step 4 Edit A, that text is no longer in the block. Delete line 218. The new test 7 in `test_178_email_normalization.py` (Step 5) covers the replacement assertion by checking the full system prompt contains `"CROSS-CHANNEL CONTINUITY"` — so the coverage moves from the block-level to the prompt-level, which is where the rule now lives.

### Step 5: Tests

Create `wtyj/tests/marina/test_178_email_normalization.py` with these tests:

1. **Case-insensitive email lookup.** Create customer with `calvin@gaimin.io`, look up with `Calvin@gaimin.io` → returns the same row.
2. **Case-insensitive email create.** `customer_lookup_or_create("email", "calvin@gaimin.io")` then `customer_lookup_or_create("email", "CALVIN@gaimin.io")` returns the SAME id (no new row).
3. **Add-identifier merges case variants.** Create Row A with `calvin@gaimin.io`. Create Row B with `(phone, +34...)`. Call `customer_add_identifier(B_id, "email", "Calvin@gaimin.io")` → returned dict has `action == "merged"` and `customer_id == A_id` (the older row survives per `_customer_choose_merge_survivor`).
4. **Phone and non-email identifiers are NOT lowercased.** `customer_lookup_or_create("phone", "+34 123 456")` stores `+34 123 456` as-is (stripped, but not lowercased). Important for phones that have no case but might have significant whitespace.
5. **Normalization helper is idempotent.** `_normalize_identifier_value("email", "Calvin@gaimin.io")` → `calvin@gaimin.io`. Run it twice → same result.
6. **Cross-channel rule is in the system prompt.** Build a system prompt and assert it contains `"CROSS-CHANNEL CONTINUITY"` and at least two of the forbidden phrases from the NEVER-SAY list (e.g. `"I can't check emails"`, `"no access to the inbox"`).
7. **Cross-channel rule is present even when customer_file is empty.** Build a system prompt with `customer_file=None` → still contains `"CROSS-CHANNEL CONTINUITY"`. This is the "new customer's very first message" case that the old placement missed.
8. **Data repair script is idempotent.** Create two rows with `calvin@gaimin.io` and `Calvin@gaimin.io`. Run the repair logic inline (import and call the main function). Verify: one row survives, the other is merged, and no exception if run a second time.

Also verify the existing test suite still passes.

## Tests

See Step 5. Eight new tests in `wtyj/tests/marina/test_178_email_normalization.py`. Plus the full regression suite must stay at 833 passing (before new tests) → 841 passing (after).

## Success Condition

Two case-dupe pairs in production (Calvin rows 5/6, Ash rows 2/3) are merged after running the repair script. Any future WhatsApp inbound that references an email gets a "what's your email?" reply from Marina instead of "I can't check emails". Any future email poller run that creates a customer row uses the lowercased email, preventing new case-dupes. Full suite at 841 passing / 0 failures (833 baseline + 8 new tests; the deleted assertion inside test_166's existing test function does not change pytest's test count).

## Rollback

- Source rollback: `git revert <commit>` on backend repo, deploy.
- Data rollback: the repair script is idempotent and only lowercases + merges. To unwind a merge (unlikely needed), `customer_merges` table has the surviving_id → absorbed_id mapping and the absorbed row is still present with `active=0`. Manual SQL can reverse a specific merge if truly necessary.
- Prompt rollback: reverting the source commit also reverts the prompt. Old cross-channel rule inside the customer file block is restored.
