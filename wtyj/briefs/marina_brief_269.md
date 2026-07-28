# BRIEF 269 — Complete Consulta Despertares prospect card data

## Goal

Expose the complete structured prospect file required by the Consulta Despertares
follow-up dashboard and its operator copy action.

## Data contract

Each prospect response must include:

- first name
- surnames
- phone number
- preferred appointment/session schedule
- session type
- reason for consultation (optional)
- preferred time for the secretary to call

## Implementation

- Add `appointment_preference` to Marina's structured field schema.
- For this tenant, use `service_name` for the requested therapy/session type.
- Use `appointment_preference` for the desired appointment schedule.
- Keep `callback_preference` exclusively for when the secretary may call.
- Enrich follow-up API rows from the existing WhatsApp structured-state record;
  do not duplicate these fields in the follow-up table.
- For historical conversations, fall back to `date + slot_time` when
  `appointment_preference` is absent.
- Never infer a session type from the reason for consultation.
- Missing optional values must remain empty so the dashboard can label them
  honestly.

## Acceptance criteria

- List and single-record follow-up responses expose `session_type` and
  `appointment_preference`.
- Explicit appointment preference wins over historical date/slot fields.
- Callback and appointment timing remain distinct.
- Existing follow-up status and workflow behavior is unchanged.
