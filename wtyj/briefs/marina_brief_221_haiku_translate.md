# BRIEF 221 — Haiku for /ai-editor translate path
**Status:** Draft | **Files:** `wtyj/dashboard/api.py`, `wtyj/tests/social/test_221_haiku_translate.py` | **Depends on:** Brief 212 (AI Editor endpoint), Brief 217 (current Sonnet usage shape) | **Blocks:** SR's translation feature being economical at scale

## Context

Brief 212 shipped `POST /ai-editor` as a single endpoint serving three operator-facing actions: `translate`, `style`, `fix`. All three currently call `claude-sonnet-4-6`:

```python
# wtyj/dashboard/api.py:1923-1927 (current state, post-Brief-217)
client = anthropic.Anthropic()
resp = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=2048,
    messages=[{"role": "user", "content": prompt}],
)
```

That made sense at design time when AI Editor only ran on operator-authored draft replies in the escalation composer (translate the draft TO the customer's language; restyle the draft; fix the draft's grammar). Sonnet was justified for `style` + `fix` because those need to preserve nuance, register, and brand voice — Marina's voice is hard to keep consistent with a smaller model.

What changed: SR shipped a separate frontend feature today — **operator message translation** — that lets the operator click "Translate" on any inbound customer message bubble in the conversation pane and read it in English. The frontend wires this through the existing `/ai-editor` endpoint with `action: "translate"` (verified at `unboks-dashboard-api/artifacts/unboks/src/lib/api.ts:583-599` — `translateMessage()` calls `aiEditorEdit({action: "translate", ...})`).

This shifts the cost profile materially. `translate` becomes the dominant action by call count: every operator opening any non-English conversation will hit it potentially several times per message bubble. `style` + `fix` are intentional draft-revision actions that get used a fraction as often.

Sonnet for translation is overkill in two ways:
1. **Quality:** Haiku 4.5 handles the 6 v1 languages (English, Dutch, Spanish, Papiamento, Swedish, Portuguese) at human-readable quality for the "operator wants to read what the customer said" use case. We're not generating publication copy; we're decoding intent.
2. **Cost:** Sonnet input is $3/M tokens, output $15/M; Haiku input is ~$0.80/M, output ~$4/M. Translation prompts are small (~50 tokens of system instructions + the message text). Per call, Haiku is ~75% cheaper. At expected SR-scale (operator translates 50-200 messages/day across tenants), this saves real money.

Per Benson's directive (today's session): "to translate text I genuinely don't want to use Claude or if we use Claude I want to use Haiku or something cheap." Haiku is the cheapest path that keeps the existing codepath, no new dependencies, no new API keys.

## Why This Approach

**Considered:** swap to Google Translate or DeepL. Both have free tiers (500K chars/month). Higher translation quality on language pairs Haiku is mediocre at. Rejected: adds an external dependency + API key + a new error/timeout path + provider lock-in. The acceptable-quality threshold for "operator reads what customer said" is low; Haiku clears it. Free providers stay on the table as a Phase 2 swap if Haiku quality issues surface.

**Considered:** route translation to a separate endpoint (`/messages/translate`) so the model selection is forced by URL. Rejected: SR's frontend already routes through `/ai-editor` with `action: "translate"` and the frontend code explicitly comments that path is intentional ("V1 reuses the AI Editor endpoint with `action: 'translate'`"). Adding a parallel endpoint requires SR to change `lib/api.ts:583`, then wait for Replit to redeploy, before our backend change matters — extra coordination for zero benefit.

**Chosen:** conditional model selection inside the existing handler. `action == "translate"` → `claude-haiku-4-5-20251001`; everything else → `claude-sonnet-4-6` unchanged. One-line diff. Zero contract change. No new endpoint, no new env var. Bonus: the SAME endpoint serves both AI Editor's translate-the-draft case AND operator's read-the-customer case; both get cheaper.

**Tradeoff:** if translation quality is materially worse for one of the 6 languages, operator-side translations will look weaker than they did 24h ago. Mitigation: the brief leaves Sonnet for `style`/`fix` so the user-facing draft-quality path is unchanged, and any quality complaint is a one-line config rollback.

## Instructions

### Step 1: Add per-action model selection

In `wtyj/dashboard/api.py`, before the `client.messages.create(...)` call inside `ai_editor()` (around line 1922), select the model based on `req.action`:

```python
# Brief 221: translate uses Haiku for cost (used heavily by operator
# message-read translation; quality is more than adequate for decoding
# intent across the 6 v1 languages). Style + fix stay on Sonnet because
# they touch operator-authored drafts where brand voice matters.
model_id = (
    "claude-haiku-4-5-20251001"
    if req.action == "translate"
    else "claude-sonnet-4-6"
)
```

Then thread `model=model_id` through the existing `client.messages.create(...)` call — replacing the literal `"claude-sonnet-4-6"`.

### Step 2: Log the model in the success log line

Update the existing `bm_logger.log("ai_editor_used", ...)` call at the end of the handler to include the model used:

```python
bm_logger.log("ai_editor_used", action=req.action, length=len(req.text), model=model_id)
```

This gives us per-call visibility on which model handled which action — useful for cost auditing and quality regression triage.

### Step 3: Test file `wtyj/tests/social/test_221_haiku_translate.py`

Mirror the test pattern at `wtyj/tests/social/test_212_dashboard_endpoint_polish.py:107-125` (existing Sonnet-era ai-editor test). Use `@patch("dashboard.api.anthropic")` to capture the `client.messages.create(...)` call kwargs and assert the `model=` argument.

Required tests (3):

1. **`test_ai_editor_translate_uses_haiku`**: POST `/ai-editor` with `action: "translate"`, `text: "Hola amigo"`, `targetLanguage: "English"`. Assert response 200 + `mock_client.messages.create.call_args.kwargs["model"] == "claude-haiku-4-5-20251001"`.
2. **`test_ai_editor_fix_still_uses_sonnet`**: POST with `action: "fix"`. Regression guard — Sonnet must remain on the draft-revision path. Assert `model == "claude-sonnet-4-6"`.
3. **`test_ai_editor_style_still_uses_sonnet`**: POST with `action: "style"`, `style: "warmer"`. Same regression intent — assert `model == "claude-sonnet-4-6"`.

For all three: use the test harness pattern from `test_212_dashboard_endpoint_polish.py` top-of-file (login helper + `_auth(token)` header + `client = TestClient(app)`).

## Tests

3 tests covering the model-selection branch (translate → Haiku; fix + style → Sonnet). Assert on the `model=` kwarg of the mocked `client.messages.create(...)` call. No source-string guards.

## Success Condition

`python3 -m pytest wtyj/tests/ -q` passes at **1001 / 0** (998 baseline + 3 new). Live verification post-deploy: hit `POST /api/unboks/dashboard/api/ai-editor` with `{"action":"translate","text":"Hola","targetLanguage":"English"}` → 200 with translated text. `bm_logger.log("ai_editor_used", ...)` line in container logs shows `model=claude-haiku-4-5-20251001`.

## Rollback

`git revert <commit>` and redeploy. Restores `claude-sonnet-4-6` on all three actions. Single-file revert, no schema or contract change to undo.
