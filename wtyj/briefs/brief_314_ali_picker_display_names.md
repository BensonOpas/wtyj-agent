# BRIEF 314 — Clean vehicle names in Ali's WhatsApp picker
**Status:** Executed | **Files:** `wtyj/agents/social/ali_vehicle_recommendations.py`, `wtyj/tests/agents/test_ali_vehicle_recommendations.py` | **Depends on:** Brief 313 and the catalog-grounded recommendation renderer | **Blocks:** None

## Context
Ali's WhatsApp vehicle picker rendered catalog names by blindly taking their first 24 characters. That transport limit changed `Kia Picanto 2024 or similar` into `Kia Picanto 2024 or simi` and `Volkswagen up! or similar` into `Volkswagen up! or simila`. These fragments look like malformed vehicle terminology even though the underlying catalog data is correct.

## Why This Approach
The picker is a compact selection control, so its title now omits only an exact trailing `or similar` disclaimer. The full official catalog name remains unchanged on the detailed vehicle card, numbered fallback, selection state, and quote. Any other title over 24 characters is shortened at a word boundary with an ellipsis.

Changing the catalog was rejected because `or similar` is valid rental-category wording and belongs in detailed customer-facing material. A larger title cannot be sent because WhatsApp limits picker row titles to 24 characters.

## Instructions
1. Normalize whitespace in picker-only display labels.
2. Remove an exact, case-insensitive trailing `or similar` suffix from the compact picker title.
3. Shorten any remaining title over 24 characters at a word boundary and append an ellipsis.
4. Preserve the full catalog name in recommendation options, detailed cards, fallback text, matching, and quotes.
5. Add regression coverage for the three malformed live labels and a long name without the suffix.

## Tests
- The reported Volkswagen and Kia names render as complete model names without `simi` or `simila` fragments.
- Every picker row title remains within WhatsApp's 24-character limit.
- A longer non-disclaimer name uses a word-boundary ellipsis.
- Full official catalog names and fallback text remain unchanged.

## Success Condition
Ali's vehicle picker never displays chopped `or similar` fragments, while detailed surfaces continue to use the complete official vehicle name.

## Rollback
Revert the Brief 314 commit and redeploy through the normal WTYJ pipeline. No data or schema migration is involved.
