# OUTPUT 251 — Upgrade `/ai-editor` style prompts to per-style distinct instructions

## What was done

P1 fix for issue #21 — Calvin's Agent Editor `style` tool produced near-identical outputs across all 5 values (`professional` / `warmer` / `shorter` / `friendlier` / `direct`) because the backend used a single template `"Rewrite ... in a more {style} style"` with the style adjective swapped in. Per-step shipped:

1. **Replaced the single-template style branch** at `wtyj/dashboard/api.py:2813-2820` with a `_STYLE_INSTRUCTIONS` lookup. New module-level dictionary above `_build_ai_editor_prompt` (around line 2792) maps each of the 5 styles to its own goal-shaped multi-line instruction. Instructions are verbatim from issue #21's spec with light formatting (Calvin chose the wording; brief preserved it). Each instruction includes: tone goal, what to avoid, "preserve full meaning", "do not add information not in original", "do not use em dashes", "return only the rewritten message" — distinct GOAL per style, common globals.
2. **Added a defensive raise** in the style branch: `_STYLE_INSTRUCTIONS.get(style)` returns None for unknown values; if None, raise `ValueError(f"unknown style: {style}")`. The endpoint validator at `api.py:2836-2838` already rejects unknown styles with 400 — the defensive raise protects against future internal callers that bypass the validator.
3. **5 new tests appended to `wtyj/tests/social/test_212_dashboard_endpoint_polish.py`** (extending the existing per-module file for `/ai-editor` per Brief 236). Each test calls `_build_ai_editor_prompt(action="style", style=X, ...)` directly and asserts BOTH positive markers (distinctive phrases for THIS style) AND negative markers (phrases from OTHER styles that must NOT appear) — guards regression where two style instructions might converge in the future.

**Brief-reviewer:** PASS round 1 zero issues. Anchors verified, test pattern matches Brief 236 rules (function-output testing, not source-file grepping), defensive raise pattern correct.

**Output-reviewer:** pending.

## Tests

1078 passing / 0 failures (1073 baseline + 5 new = 1078). Targeted file `wtyj/tests/social/test_212_dashboard_endpoint_polish.py` runs 11/11 (was 6; added 5).

## Test examples — what each prompt now distinctly contains

For Calvin's example input `"all good. ,thank you , was a pleasure , next time again ."`:

**`professional` prompt** contains:
> Rewrite this customer service message in a professional tone. Keep it concise and clear. Remove filler words and grammar errors. Do not make it overly stiff or corporate if the original is informal.

**`warmer` prompt** contains:
> Rewrite this customer service message to sound warmer and more human. Show genuine appreciation. Avoid corporate language. It should feel personal, like it was written by a real person who cares.

**`shorter` prompt** contains:
> Rewrite this message using as few words as possible while preserving the full meaning. The output must be shorter than the input. Remove all filler, redundancy, and unnecessary phrasing.

**`friendlier` prompt** contains:
> Rewrite this customer service message in a friendly, approachable tone. Keep it professional enough for customer service but make it feel conversational and relaxed, not stiff.

**`direct` prompt** contains:
> Rewrite this customer service message as directly and plainly as possible. Use simple language. No filler. Keep only what is necessary to be polite and convey the meaning. The result should feel crisp and efficient.

All 5 share the global suffixes: "Preserve the full meaning. Do not add any information not in the original. Do not use em dashes. Return only the rewritten message. No preamble, no explanation."

**Real Claude before/after samples are not collected by CI** (no real Anthropic calls in test runs). Production verification by Calvin: hit each style on the same example input via the dashboard's Agent Editor; the 5 outputs should now be distinctly different rewrites with the expected tone goals (professional = clean, warmer = personal, shorter = fewer words, friendlier = conversational, direct = crisp).

## Deployment

Source commit pending. Will deploy via the standard CI pipeline. **Pure prompt change** — no schema migration, no new endpoints, no behavioral change to `fix` or `translate` actions. Briefs 238-250 all preserved.

## Out-of-scope (deferred per brief Step 3)

- Server-side enforcement of `shorter`'s "output must be shorter than input" hard rule — Python length check + retry. Defer until Claude's compliance rate is measured.
- Channel-context-aware adaptation (WhatsApp vs email tone). Defer.
- System-prompt + user-prompt two-message API call shape. Defer.
- Em-dash strip on AI editor server response. Defer; Brief 244's on-send strip catches anything Claude doesn't follow.
- Token cost reduction via Haiku for some styles. Defer; Sonnet stays for `style` (operator-authored draft quality).
