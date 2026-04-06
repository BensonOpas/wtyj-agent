# OUTPUT 083 — Use WhatsApp Profile Name in Escalation Notifications

**Brief:** marina_brief_083_relay_customer_name.md
**Status:** Complete
**Date:** 2026-03-13

## What Was Done

Changed `_cname` fallback in both semi-escalation (line 500) and full escalation (line 545) handlers from `fields.get("customer_name", "Unknown")` to `fields.get("customer_name") or from_name or "Unknown"`. This uses the WhatsApp profile name when `customer_name` isn't in booking fields.

## Test Results
```
test_077 suite: 12/12 PASSED (11 existing + 1 new)
Full social regression: 104/104 PASSED
```

New test: `test_relay_notification_uses_profile_name` — triggers semi-escalation with `from_name="Jan de Vries"` and no `customer_name` in fields, asserts notification subject and body contain "Jan de Vries" instead of "Unknown".

## Unexpected
Nothing unexpected.
