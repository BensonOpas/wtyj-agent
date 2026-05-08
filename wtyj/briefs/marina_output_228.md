# OUTPUT 228 — Appointments backend (thread-based, derived from escalation summaries)

## What was done
New `appointments` SQLite table with `conversation_id UNIQUE` (one row per conversation), columns covering customer/title/dateTimeLabel/proposedTimes JSON/status/timestamps. Two helpers added next to Brief 227's `get_active_escalation_summary_for`: `appointment_upsert` (UPSERT keyed on conversation_id, picks first proposed time as headline `date_time_label`) and `appointments_list` (returns list in SR's camelCase shape with parsed proposedTimes). The Brief 227 `_generate_escalation_summary` wrapper now writes an appointment row when the summary's `extractedDetails.intent == "scheduling"` — `pending_team_confirmation` if any proposed times exist, `detected` otherwise. Email channel escalations get `email::<thread_key>` as the conversationId so the frontend's `/messages/conversations/:phone` routing matches what /escalations returns. New `GET /appointments` endpoint returns the list under both `items` and `appointments` keys for envelope flexibility (matches SR's normalizer at `lib/api.ts:266-268`).

## Tests
1059 passing / 0 failures (baseline 1053 + 6 new).

## Deployment
Source committed and pushed; deploy still to fire.
