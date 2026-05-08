# OUTPUT 226 — Alternative email destination for escalation alerts

## What was done
Added `email_alternative_destination` column to `alert_settings` (idempotent ALTER, placed right after the `CREATE TABLE alert_settings` block). Updated `state_registry.get_alert_settings` to expose `channels.email.alternativeDestination` (always present; empty string when unset) and `save_alert_settings` to persist it. Added `alternativeDestination: str = ""` field with `field_validator` to `AlertChannelConfig` Pydantic model in `wtyj/dashboard/api.py` — empty allowed, missing `@` or domain-without-dot raises ValueError → 422 to caller. Updated `_fire_escalation_alerts` email block to build a recipient list (primary first, then alternative if set and ≠ primary) and loop, recording one `alert_deliveries` row per attempt — best-effort independent per Brief 217's pattern.

## Tests
1046 passing / 0 failures (baseline 1039 + 7 new).

## Deployment
Source committed and pushed; deploy still to fire.
