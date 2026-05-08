# OUTPUT 229 — Data retention settings (storage + endpoints, cleanup deferred)

## What was done
New `data_retention_settings` table (singleton row at id=1, mirrors Brief 217's `alert_settings` pattern). Two helpers added next to Brief 228's appointments helpers: `get_data_retention_settings()` returns SR's exact `DEFAULT_DATA_RETENTION` shape (camelCase) when no row exists, with a hardcoded `status: {policyActive: false}` until cleanup automation ships; `save_data_retention_settings(...)` UPSERTs at id=1. New Pydantic model `DataRetentionUpdate` uses `Literal[...]` types to enforce SR's discrete value sets — invalid values return 422 with field-level errors. GET + PUT endpoints round-trip cleanly. Three action endpoints (archive-now, export, delete-customer-data) return 501 with explicit "not implemented yet" messages per SR's "No silent fail / No fake success" rule. Cleanup logic (cron + actual data destruction) deferred to a follow-up brief.

## Tests
1066 passing / 0 failures (baseline 1059 + 7 new).

## Deployment
Source committed and pushed; deploy still to fire.
