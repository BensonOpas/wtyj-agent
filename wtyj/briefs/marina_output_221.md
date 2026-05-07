# OUTPUT 221 — Haiku for /ai-editor translate path

## What was done

Single-file behavioral change in `wtyj/dashboard/api.py` inside the `ai_editor()` handler at lines 1919-1944. Added a per-action model selector: `model_id = "claude-haiku-4-5-20251001" if req.action == "translate" else "claude-sonnet-4-6"`. Threaded `model_id` through the existing `client.messages.create(...)` call and added `model=model_id` to the existing `bm_logger.log("ai_editor_used", ...)` line for per-call cost auditing. Translate requests (which became the dominant action by call count after SR's frontend wired operator message-read translation through the same endpoint earlier today) now route to Haiku; style + fix continue using Sonnet because they touch operator-authored drafts where brand voice matters. Zero contract change — same endpoint, same request body, same response shape, same enums.

## Tests

1001 passing / 0 failures (998 baseline + 3 new).

## Deployment

Pending — commit/push/deploy in step 16.
