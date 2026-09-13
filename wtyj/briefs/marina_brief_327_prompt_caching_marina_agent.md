# BRIEF 327 — Prompt caching for marina_agent (move CUSTOMER FILE to the user prompt)

**Status:** Draft | **Files:** `wtyj/agents/marina/marina_agent.py`, `wtyj/tests/marina/test_166_customer_file.py`, `wtyj/tests/marina/test_174_tool_use.py` | **Depends on:** Brief 166 (customer file), Brief 174 (tool-use migration), Brief 178 (cross-channel continuity rule) | **Blocks:** Brief 328 (cache-metrics logging)

## Context

Anthropic spend is running at roughly **$59/week (~$250/month)** against a **$200/month** organization cap. Measured over the last 7 days from the per-tenant `api_usage` records in `/root/clients/*/logs/agent.log`:

| Tenant | Calls | Avg input tokens/call | Cost |
|---|---:|---:|---:|
| consulta-despertares | 653 | 22,113 | $46.86 |
| ali-car-rental | 94 | 22,690 | $6.89 |
| mermaid | 136 | 9,378 | $5.13 |
| **total** | **883** | | **$58.89** |

Input is 98% of the bill (7-day totals: 17,848,392 input vs 356,011 output). The cost is not volume — 883 calls in a week is modest — it is that **every customer message re-sends the whole instruction set at full price**. Measured inside the live `wtyj-consulta-despertares` container:

```
MARINA_TOOL (json.dumps)   ~ 2,756 tokens
_build_system_prompt()     ~14,217 tokens
                            ───────
static per call            ~16,973 tokens   (of a ~22,113-token average call)
```

`git grep cache_control` returns nothing in repo source — prompt caching has never been used here. Anthropic cache reads cost ~0.1× the normal input price, so this is money discarded on every message.

**Why this needs a brief rather than a one-line change:** prompt caching is a *prefix* match. The cache key is the exact bytes from the start of the request (render order `tools` → `system` → `messages`) up to the `cache_control` breakpoint. Any byte that changes invalidates everything after it. `_build_system_prompt` interpolates volatile blocks near the **top** of the prompt at `marina_agent.py:1678`, ahead of the ~9,600 tokens of static booking rules, tool-field documentation and service aliases that follow. Adding `cache_control` without moving them would write the cache at the **1.25× write premium on nearly every call and almost never read it — a net cost increase of roughly 25%.**

Volatility audit of that block group, measured on the live despertares container:

| Block | Built at | Size | Changes |
|---|---|---:|---|
| `_customer_file_block` | `marina_agent.py:1597` | varies | **every message** — `recent_interactions` and the rolling summary are appended as the conversation progresses |
| `_info_updates_block` | `:1600` | 3,171 tok | operator edit / scheduled window |
| `_source_of_truth_block` | `:1599` | 707 tok | operator edit |
| `_knowledge_files_block` | `:1602` | 505 tok | operator upload |
| `relay_mode` / `fully_escalated` | rendered `:1674` | small | escalation event |

**Only `_customer_file_block` changes on a per-message basis.** `state_registry.customer_get_full` returns `recent_interactions` as an `ORDER BY created_at DESC LIMIT 5` window plus a rolling `summary`; on the WhatsApp path the file is re-fetched per message (`wtyj/agents/social/social_agent.py:1574`) and a new interaction row is written after every reply (`social_agent.py:1816`), so the block's bytes change every turn. The other blocks are operator-edit volatile — they change a handful of times per day, costing an occasional cache write, which is fine. Moving that single block out of the system prompt makes the prefix stable for the duration of a conversation, which is the window a 5-minute cache TTL covers.

The system prompt is otherwise clean: there is no `datetime.now()` in it. `TODAY (Curaçao time)` is already correctly placed in the user prompt at `marina_agent.py:1923` / rendered `:2013`.

## Why This Approach

The CUSTOMER FILE block is per-customer conversation *context*, not instruction — it belongs in the user turn on its own merits. The user prompt already carries the sibling continuity sections (`returning_customer_section`, `past_customer_bookings_section`, and THREAD CONTEXT at `:2022`), so this groups related material rather than splitting it across two prompts.

**Rejected: cache the `tools` array only.** `MARINA_TOOL` (`:71`) is a module-level constant, never mutated, and renders at prefix position 0, so a breakpoint on it is guaranteed-stable with zero prompt restructuring. But it is only ~2,756 of ~22,113 tokens — roughly an 11% saving, which does not bring a $250/month run rate under a $200 cap. Kept as the fallback if the approach here fails verification.

**Rejected: reorder every volatile block below the static body.** This would cache slightly more (the `:1904-1909` tail as well) but requires moving `relay_mode_section` and `fully_escalated_section` (`:1674`) to the bottom of the prompt. Those are the safety-critical escalation controls on a psychology-clinic tenant, and their position relative to the behavioural rules is not worth disturbing for a marginal token gain.

**Rejected for this brief: adding `cache_read_input_tokens` / `cache_creation_input_tokens` to the `api_usage` log.** It belongs in the same area and was drafted here, but `bm_logger.log` serialises kwargs with `json.dumps` (`wtyj/shared/bm_logger.py:23`) and `getattr` on a `MagicMock` auto-creates a child mock rather than returning the default. Seven existing mock sites across five test files construct a bare `MagicMock` usage object and flow into `process_message`; one (`wtyj/tests/social/test_069_whatsapp_agent.py:100`) would turn CI red, and two (`wtyj/tests/marina/test_174_tool_use.py:167`, `wtyj/tests/marina/test_marina_tone.py:101`) would *silently pass for the wrong reason* — receiving the fallback from a swallowed `TypeError` at `:2323` instead of exercising the guards they exist to test. That is a worse outcome than a red build and deserves its own brief where fixing those mocks is the subject rather than a side-effect. Deferred to **Brief 328**. Cache effectiveness is verifiable in the meantime from the Anthropic Console usage view, which reports cache read and write tokens directly.

**Tradeoff carried:** the customer file moves from the system prompt to the user turn. The rendered block text is unchanged and it still precedes the inbound message, but this is not a pure no-op: the CROSS-CHANNEL CONTINUITY rule at `marina_agent.py:1715` currently tells the model "The CUSTOMER FILE block **above** (if present)…", and after the move that positional claim is false. Step 7 corrects the wording. That rule drives cross-channel continuity behaviour on the clinic tenant, so it is the one genuinely behavioural edge in this brief and the reason it is not a quick fix. Precedent for the corrected phrasing already exists at `:1694`, where a system-prompt rule refers to "TODAY (shown in the user prompt)".

**TTL:** the 5-minute default. WhatsApp messages in a live conversation arrive seconds apart and stay inside the window. The 1-hour TTL costs 2× to write and needs three or more reads to break even, which does not fit this traffic shape.

`anthropic==0.84.0` is pinned in `requirements.txt:1` and its usage object already exposes the cache fields — no dependency change required.

## Instructions

1. In `wtyj/agents/marina/marina_agent.py:1597`, delete the `_customer_file_block` assignment. Leave `_build_customer_file_block` (`:768`) untouched — it is still the renderer, just called from elsewhere.

2. In the system prompt f-string at `marina_agent.py:1678`, remove the `{_customer_file_block}` interpolation. The remaining blocks on that line (`_approved_answers_block`, `_info_updates_block`, `_knowledge_files_block`, `_icp_sot_block`, `_consulta_reference_facts`) stay exactly where they are.

3. Keep the `customer_file` parameter in the `_build_system_prompt` signature (`:1443`) with its `None` default, and keep the function returning `str`. Twenty-two test files call this function, `_build_prompt` (`def` at `:2029`) concatenates its result with `+`, and `wtyj/shared/runtime_prompt_manifest.py:112,122` passes it through `str()` inside `_sanitize` (`runtime_prompt_manifest.py:33`) — changing the return type would break all three, one of them silently.

4. Add a `customer_file=None` keyword parameter to `_build_user_prompt` (`:1912-1921`), call `_build_customer_file_block(customer_file)` inside it, and render the result in the returned f-string (`:2012`) immediately before the `THREAD CONTEXT` section (`:2022`), keeping it grouped with the other customer-continuity sections.

5. At the call site in `process_message` (`:2245-2247`), stop passing `customer_file` to `_build_system_prompt` and pass it to `_build_user_prompt` instead.

6. At `marina_agent.py:2252`, change `system=system_prompt` to a single-element content-block list carrying `cache_control`. The exact payload shape required by the Messages API is:

   ```python
   system=[{"type": "text", "text": system_prompt,
            "cache_control": {"type": "ephemeral"}}],
   ```

   Leave `tools`, `tool_choice`, `model`, `max_tokens` and `messages` unchanged — the breakpoint on the system block covers the preceding `tools` array as well.

7. In the CROSS-CHANNEL CONTINUITY rule at `marina_agent.py:1715`, remove the word `above` from "The CUSTOMER FILE block above (if present)" so the instruction no longer asserts a position that is no longer true. Change nothing else in that rule: the following paragraph (`:1717`) refers to "their CUSTOMER FILE" without a positional claim and stays as-is.

8. Directly above the `system=` argument, add a comment stating that no per-request or per-message value may be added to the system prompt because it silently destroys caching, naming `TODAY` (`:1923`, correctly in the user prompt) as the reference example.

9. Do not touch the `bm_logger.log("api_usage", ...)` call (`:2261`) in this brief — see Why This Approach. Leave `_correct_reply_language` (`def` at `:2134`, call at `:2153`) alone as well: its system prompt is roughly 60 tokens, far below the 1,024-token minimum cacheable prefix for `claude-sonnet-4-6`, so a breakpoint there would never create an entry.

10. Preserve these invariants: Rule 1 (still exactly one Claude call per inbound message — none added or removed), the `MARINA_TOOL` schema is not edited, `_build_customer_file_block` output is not reworded, and the escalation/relay sections stay at their current position in the system prompt.

## Tests

Boundary-mock the Anthropic client only, following the existing pattern in `wtyj/tests/marina/test_174_tool_use.py:86` (`@patch("agents.marina.marina_agent.anthropic.Anthropic")` plus a `_mock_tool_use_response()` helper). No existing mock helper needs modifying, because this brief adds no new field to the logged record.

1. In `test_166_customer_file.py`, `test_system_prompt_includes_customer_file_when_passed` (`:223`) is rewritten in place as its replacement: passing a populated `customer_file` to `_build_user_prompt` renders the display name and the recent-interaction summary in the user prompt. Net new test functions: 0.

2. In `test_166_customer_file.py`, a new test: passing a populated `customer_file` to `_build_system_prompt` no longer renders the CUSTOMER FILE block. **Assert on the precise marker `"CUSTOMER FILE — use this context"`, not the bare string `"CUSTOMER FILE"`** — the bare string still legitimately appears in the system prompt at `marina_agent.py:1715` and `:1717` in the CROSS-CHANNEL CONTINUITY rule, which instruction 7 keeps, so a naive `not in` assertion would fail. `test_system_prompt_without_customer_file_has_no_block` at `:236` already uses the correct marker and stays as-is.

3. In `test_174_tool_use.py`, `process_message` sends `system` as a list whose first block carries `cache_control == {"type": "ephemeral"}`.

4. In `test_174_tool_use.py`, that same system block's `text` contains real constructed prompt content — assert on `BOOKING VALIDATION` (`marina_agent.py:1692`, unconditional static text outside any tenant conditional), proving genuine prompt construction flows into the cached block rather than an empty or stubbed string.

5. In `test_174_tool_use.py`, `process_message` called with a populated `customer_file` returns the mocked reply rather than the fallback text — the end-to-end guard over the `try:` block at `:2242-2321`, exercising the `customer_file` kwarg path that instruction 5 changes.

6. Run the focused marina tests, then the full backend suite.

Baseline is **2,114 passing**, confirmed empirically by running the suite at `c42adcb` (not merely quoted from `marina_brief_326_despertares_pricing_knowledge.md:65`). `system_state.md`'s latest entry still reports 1137 — it has not been appended since Brief 267 while briefs reached 326, so it is stale. Items 2-5 add four test functions and item 1 is an in-place rewrite, so expect **2,114 + 4 = 2,118, 0 failures**.

The suite cannot be run on Windows (missing `reportlab`, Unix-only `fcntl`) or against the VPS system Python (missing `reportlab`). Run it inside the runtime image, which carries the full dependency set:

```
docker run --rm --cpus=1 -v <scratch-clone>:/work -w /work -e PYTHONPATH=/work/wtyj \
  -e CLIENT_CONFIG_PATH=clients/bluemarlin/config/client.json \
  wtyj-agent sh -c "pip install -q pytest && python3 -m pytest wtyj/tests/ -q"
```

Use a scratch clone, never `/root/wtyj-agent-source`, which the live containers run from.

## Success Condition

The full suite is green at 2,118; the Anthropic Console usage view shows non-zero cache-read tokens after deploy (any non-zero value is attributable to this change, since `git grep cache_control` returns nothing in repo source today); and the cross-channel continuity check below passes.

**Continuity check (this is the verification for instruction 7, the one behavioural edit).** On the `consulta-despertares` tenant, send a WhatsApp message from a number with existing history — for example "¿recibieron mi correo?" or "te escribí por Instagram" — and confirm the reply does not claim the customer is unknown and follows the CROSS-CHANNEL CONTINUITY rule at `marina_agent.py:1715-1730`: it acknowledges, then asks one short question to link the missing channel. Then confirm the agent still has the customer's history by checking that `_build_user_prompt` received the block — `grep '"event": "api_usage"' /root/clients/consulta-despertares/logs/agent.log | tail -1` should sit alongside a normal `whatsapp_agent_reply` rather than the fallback marker. If the reply instead behaves as though the customer has no history, instruction 7 regressed and the rollback below applies.

## Rollback

Revert the Brief 327 commit and redeploy — the change is confined to prompt assembly and one request argument, so reverting restores previous behaviour immediately. No schema change, no data migration, and no stored state is written by this brief, so nothing needs undoing outside git. If caching proves ineffective but the prompt move is sound, the narrower fallback is to keep the CUSTOMER FILE relocation and move the `cache_control` breakpoint onto `tools=[MARINA_TOOL]` instead, which is stable without any prompt restructuring.
