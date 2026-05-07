# EXPLANATION 212 — Dashboard endpoint polish

Plain-English explanation of commit `4129cc2` for an operator who doesn't read code.

## What was broken

Three small things on the dashboard backend didn't quite line up with what SR's frontend was sending or expecting:

1. **Learning entries panel** — SR's frontend asks for `/learning` (no s). My backend serves `/learnings` (with s). Different word, same meaning. Backend returned 404, frontend showed an empty list.

2. **Schedule slots** — SR's frontend posts the slots as a plain JSON array (`[{...}, {...}]`). My backend was expecting it wrapped in an object (`{"slots": [{...}, {...}]}`). Backend rejected SR's request with a 422 error.

3. **AI Editor button** — SR's reply composer has a small AI Editor with three tabs: Translate (into another language), Style (rewrite as more professional / warmer / shorter / friendlier / direct), and Fix (clean grammar). Clicking any of them calls `/ai-editor`. My backend had no such endpoint at all. Frontend showed "AI Editor not available."

## What changed

**1. Added two aliases for the learning-entries endpoints.**

`/learning` (singular) now works alongside `/learnings` (plural). Same for `DELETE /learning/:id`. Both paths route to the same handler — they read from the same database table and return the same data. SR's frontend sees a real response now instead of a 404.

The other two learning endpoints SR's frontend uses — "approve" and "save" — were deliberately NOT added in this brief. They're new features (they create or update state), not aliases, and getting their semantics wrong would silently corrupt learnings data. Those are queued for a separate Tier 2 brief once we can confirm what each is supposed to do.

**2. Fixed the schedule-slots body shape.**

Changed the PUT endpoint to accept a raw JSON array directly. The old wrapped form (`{"slots": [...]}`) is no longer accepted — the brief deliberately picked one shape rather than supporting both, to keep the contract clean. One existing test (`test_111_scheduling.py`) was using the old wrapped form; updated it to match the new contract.

**3. Added the AI Editor endpoint.**

A small new endpoint at `POST /ai-editor` that takes:
- `action`: must be `"translate"`, `"style"`, or `"fix"`
- `text`: the operator's draft (the thing they want fixed/translated/restyled)
- `targetLanguage`: required when action is `"translate"` — must be one of: English, Dutch, Spanish, Papiamento, Swedish, Portuguese
- `style`: required when action is `"style"` — must be one of: professional, warmer, shorter, friendlier, direct

It builds a tight prompt for the chosen action, sends it to Claude, and returns the rewritten text in the response. The model used is `claude-sonnet-4-6` — same one Marina uses for everything else.

This is an operator tool. It's not in the "Marina answers a customer" code path. The operator sees the result in their composer and decides whether to use it before clicking Send. So even though it adds another Claude call to the system, it doesn't break the rule that says one Claude call per inbound customer message.

## What it does now

- **Learning entries panel** in the dashboard reaches a real backend handler when it loads.
- **Schedule slots** in Settings save without a 422 error.
- **AI Editor** tab in the reply composer actually returns rewritten text. Operator types a draft → clicks Fix → gets a cleaned-up version they can edit further or send.

## What it doesn't do (still pending Tier 2)

- Approving or saving a learning entry as a permanent rule. The buttons SR built for those actions still hit non-existent endpoints; frontend's graceful fallback shows them as inert.
- Soft / hard escalation mode toggle, takeover, handback, guidance flow. All Tier 2.

## Files changed

- `wtyj/dashboard/api.py` — added `Body` to the FastAPI imports; added two `/learning` alias handlers; rewrote `PUT /schedule/slots` to accept a raw array; added the `AIEditorRequest` model + `_build_ai_editor_prompt` helper + `/ai-editor` POST handler.
- `wtyj/tests/social/test_212_dashboard_endpoint_polish.py` — six new tests (two for the aliases, one for the new schedule body, three for the AI Editor variants).
- `wtyj/tests/social/test_111_scheduling.py` — one-line update so the existing schedule-slots test posts the new raw-array body shape instead of the old wrapped form.
