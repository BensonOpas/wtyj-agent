# BRIEF 219 — Marina actually USES the approved learnings
**Status:** Draft | **Files:** `wtyj/shared/state_registry.py`, `wtyj/agents/marina/marina_agent.py`, `wtyj/tests/marina/test_219_marina_uses_learnings.py` | **Depends on:** Brief 215 (escalation_learnings storage) | **Blocks:** TASK-021 Section 3 — "Marina/dm_agent should learn from operator answers and use them in future similar situations"

## Context

Brief 215 shipped the storage half: every operator answer in a hard or soft escalation is auto-saved as an `escalation_learnings` row with `status='approved'` and `aiMayUseAutomatically=true` by default. SR's frontend `Learning Entries` panel can list, approve, save, delete.

The READ half was deferred. Today those rows just sit in SQLite — Marina never sees them. So when an operator coaches Marina ("answer dietary questions by saying we accommodate gluten-free with 24h notice"), the next customer who asks the same dietary question gets a fresh, possibly-different answer. The system isn't learning.

This brief closes the loop: when Marina builds her system prompt, inject an `APPROVED ANSWERS` block listing the most recent operator-curated learnings for the channel. Marina reads them as authoritative context.

The deferral was deliberate: `_build_system_prompt` is the most sensitive code in the project. The prompt is a giant f-string with seven distinct structural blocks (persona, customer file, writing style, language rules, booking behavior, escalation behavior, JSON schema). Adding a new block at the wrong place could break Marina's existing behavior in subtle ways (e.g. injection at the top "outshouts" the persona; injection inside the JSON schema breaks parsing). It needs a feature flag for opt-in tenant rollout.

## Why This Approach

**Considered:** load every approved learning into the prompt. Rejected: prompts have token limits and operators answer dozens of escalations per week. Unbounded growth would eventually blow Sonnet's context window or cost a fortune. Cap at 20 most-recent rows per channel — enough for a useful knowledge base, bounded for cost.

**Considered:** include suggested + approved + saved learnings. Rejected: `suggested` is "draft, not yet approved by operator"; including those would teach Marina from un-vetted text. Only `approved` and `saved` represent operator-vetted authority. Brief 215 also has a per-row `aiMayUseAutomatically` flag — when set to false the operator explicitly opted that row OUT of automatic AI use. Filter to status IN ('approved', 'saved') AND ai_may_use_automatically = 1.

**Considered:** ship for both Marina and dm_agent in this brief. Rejected: Marina (`marina_agent.py:_build_system_prompt`) and dm_agent (`dm_agent.py:_build_dm_system_prompt`) are two different prompt builders with different shapes and risk profiles. Marina is higher stakes (email + WhatsApp customer-facing, full booking flow); dm_agent is Q&A on IG/FB DMs with a simpler prompt. Ship Marina first, validate in production for a few days, then a follow-up brief extends dm_agent (cheap once the helper exists). Single-agent scope keeps the test surface focused.

**Considered:** include the learning in the system prompt unconditionally once stored. Rejected: tenant-level opt-in is the safer rollout. Use `client.json::features.approved_learnings_in_prompt` (default `false`). Per-tenant we can flip on for unboks (where SR is actively coaching Marina), leave off for BlueMarlin/Adamus/Consulta (where the learnings table may have noisy or stale rows).

**Chosen:** new helper `state_registry.get_approved_learnings_for_prompt(channel, limit=20)` filters by channel + status + ai_may_use flag, returns the N most-recent rows newest-first. New "APPROVED ANSWERS" block injected into the system prompt template AFTER `_customer_file_block` and BEFORE `writing_style_block` (sits among the "factual context" zone, not the "voice/style" zone). Block is gated by `client.json::features.approved_learnings_in_prompt`. When the flag is off OR the helper returns zero rows, the block is omitted entirely (no empty header, no token waste).

**Channel filter semantics:** rows are written with the channel that produced them ("whatsapp" / "email" / "instagram" / etc). When building Marina's prompt for an email conversation, pull email rows; for WhatsApp, pull whatsapp rows. Cross-channel sharing (an email learning teaching Marina how to answer the same question on WhatsApp) is a future enhancement — for v1, keep channel discipline so the operator's coaching context stays semantically consistent (a long email answer isn't appropriate for a WhatsApp reply).

## Instructions

### Step 1: Add `get_approved_learnings_for_prompt` helper to state_registry

Insert in `wtyj/shared/state_registry.py` near the existing escalation_learnings helpers, around line 2570+ (after `get_learning_status_for_conversation` from Brief 222):

```python
def get_approved_learnings_for_prompt(channel: str, limit: int = 20) -> list:
    """Brief 219: return the N most-recent approved escalation learnings
    that Marina is allowed to use automatically. Filters: channel match,
    status IN ('approved', 'saved'), ai_may_use_automatically=1.
    Returns newest first. Used by marina_agent._build_system_prompt to
    inject an APPROVED ANSWERS block when the tenant opts in via
    client.json::features.approved_learnings_in_prompt."""
    if not channel or limit <= 0:
        return []
    conn = _get_conn()
    rows = conn.execute(
        "SELECT source_question, human_answer FROM escalation_learnings "
        "WHERE channel = ? "
        "AND status IN ('approved', 'saved') "
        "AND ai_may_use_automatically = 1 "
        "ORDER BY created_at DESC LIMIT ?",
        (channel, limit)).fetchall()
    conn.close()
    return [{"question": r[0] or "", "answer": r[1] or ""} for r in rows]
```

### Step 2: Build the APPROVED ANSWERS block in marina_agent

In `wtyj/agents/marina/marina_agent.py`, add a private helper near the other `_build_*` helpers (around line 296 — just before `_build_system_prompt`):

```python
def _build_approved_answers_block(channel: str) -> str:
    """Brief 219: return an APPROVED ANSWERS prompt block listing recent
    operator-curated learnings for this channel, or '' when the tenant
    hasn't opted in or no learnings match. Empty-string return is
    important: it lets _build_system_prompt drop the block from the
    f-string without leaving a dangling header."""
    features = config_loader.get_raw().get("features", {}) or {}
    if not features.get("approved_learnings_in_prompt"):
        return ""
    try:
        from shared import state_registry
        rows = state_registry.get_approved_learnings_for_prompt(channel, limit=20)
    except Exception:
        return ""
    if not rows:
        return ""
    pairs = []
    for r in rows:
        q = (r.get("question") or "").strip()
        a = (r.get("answer") or "").strip()
        if not a:
            continue
        if q:
            pairs.append(f"Q: {q}\nA: {a}")
        else:
            pairs.append(f"A: {a}")
    if not pairs:
        return ""
    return (
        "APPROVED ANSWERS (operator-curated knowledge):\n"
        "The team has previously answered similar customer questions on this "
        "channel. Use these as authoritative context — they reflect how the "
        "human team wants you to handle these situations going forward. Match "
        "the spirit; do not copy verbatim if the customer phrasing differs.\n\n"
        + "\n\n".join(pairs)
    )
```

### Step 3: Inject the block into `_build_system_prompt`

In `_build_system_prompt` at `marina_agent.py:297-672`, compute the block right before the final `return f"""..."""` (around line 451 where `_customer_file_block` is built):

```python
_customer_file_block = _build_customer_file_block(customer_file)
_approved_answers_block = _build_approved_answers_block(channel)
```

Then in the f-string itself (around line 452+), insert the block immediately AFTER `{_customer_file_block}` and BEFORE the blank line that precedes `{writing_style_block}`. If the block is empty (`""`), the f-string interpolation drops it cleanly — no dangling header, no extra whitespace because adjacent blank lines collapse via the `.strip()` Marina's user prompt already does. Specifically, change:

```python
{_customer_file_block}

{writing_style_block}
```

to:

```python
{_customer_file_block}
{_approved_answers_block}

{writing_style_block}
```

The single blank line between `_customer_file_block` and `_approved_answers_block` is INTENTIONALLY ABSENT — when `_approved_answers_block` is empty, the result is `{_customer_file_block}\n\n{writing_style_block}` (current behavior preserved); when non-empty, it's `{_customer_file_block}\n<APPROVED ANSWERS BLOCK>\n\n{writing_style_block}` (one blank line between block and writing style, consistent spacing).

### Step 4: Test file `wtyj/tests/marina/test_219_marina_uses_learnings.py`

Mirror the test harness pattern at `wtyj/tests/marina/` (existing marina tests; check for the conftest setup in that directory). For tests that build the system prompt, use `marina_agent._build_system_prompt(thread_flags={}, channel="whatsapp")` (or "email") and assert on substring presence/absence in the returned string.

Required tests (6):

1. **`test_helper_returns_empty_when_no_rows`** — ensure `state_registry.get_approved_learnings_for_prompt("whatsapp")` returns `[]` when no escalation_learnings rows exist.
2. **`test_helper_filters_by_channel`** — seed 2 rows with channel="whatsapp" + 1 with channel="email". Helper called with `channel="whatsapp"` returns 2 rows; with `channel="email"` returns 1.
3. **`test_helper_excludes_unapproved_and_opt_out`** — seed rows with status='suggested', status='deleted', and one with status='approved' but `ai_may_use_automatically=0`. Helper returns 0 rows. Then add an `approved + ai_may_use=1` row; helper returns 1 row.
4. **`test_helper_respects_limit`** — seed 25 approved rows. Helper called with `limit=5` returns 5 rows. Default `limit=20` returns 20.
5. **`test_prompt_omits_block_when_feature_flag_off`** — with `features.approved_learnings_in_prompt=false` (default for test config), `_build_system_prompt(thread_flags={}, channel="whatsapp")` does NOT contain the substring "APPROVED ANSWERS". Seed approved rows to ensure it would otherwise show.
6. **`test_prompt_includes_block_when_flag_on_with_entries`** — monkeypatch `config_loader.get_raw` to return `{"features": {"approved_learnings_in_prompt": True}, ...}`, seed 2 approved learnings for `channel="whatsapp"`, call `_build_system_prompt(thread_flags={}, channel="whatsapp")`. Result contains "APPROVED ANSWERS", contains both seeded answers, AND comes BEFORE "WRITING STYLE" in the output (verifies position).

Cleanup pattern: each test wraps in try/finally that DELETEs from escalation_learnings WHERE conversation_id LIKE '219_%'.

## Tests

6 tests covering the helper (filter by channel/status/limit) + the prompt assembly (flag off/on + position). All assertions check real return values and substring positions in the actual rendered prompt.

## Success Condition

`python3 -m pytest wtyj/tests/ -q` passes at **1016 / 0** (1010 baseline + 6 new). Live verification post-deploy (manual): toggle `features.approved_learnings_in_prompt` to `true` in `clients/unboks/config/client.json`, restart the unboks container, watch the next inbound customer message — the rendered system prompt should contain the APPROVED ANSWERS block (visible by adding a temporary `bm_logger.log("system_prompt_len", ...)` or by inspection of marina's reasoning).

## Rollback

`git revert <commit>` and redeploy. The new helper becomes dead code; the prompt loses the new block. Tenant `client.json` `features.approved_learnings_in_prompt` becomes a no-op flag. Schema/storage unchanged — Brief 215's `escalation_learnings` table stays. No data loss, no migration to undo.
