# BRIEF 093 — Rejection Learning
**Status:** Draft | **Files:** `agents/social/content_agent.py`, `shared/state_registry.py`, `tests/social/test_093_rejection_learning.py` (NEW) | **Depends on:** Brief 092 (content agent core + draft store) | **Blocks:** None

## Context
Brief 092 built the content engine — Claude generates draft posts and stores them in SQLite. The `rejection_reason` column already exists, and the user prompt already includes raw rejection history. But raw rejections are noisy — "too salesy", "doesn't sound like us", "wrong timing" repeated across 20 drafts is hard for Claude to learn from. This brief adds the learning layer: a `distill_learnings()` function analyzes rejection patterns and produces persistent brand rules. These rules go into the system prompt so every future generation benefits. After 50 rejections, the bot KNOWS the brand.

## Why This Approach
We considered putting learnings in client.json (config-driven), but writing to config at runtime is fragile and config_loader caches. SQLite is the right store — same pattern as all other runtime state. We considered automatic distillation after every rejection, but that wastes Claude calls when there's only 1-2 rejections. Manual trigger (operator runs `distill_learnings()`) is simpler and cheaper — automate later if needed. The key design: raw rejections stay in the USER prompt (context for this generation), distilled learnings go in the SYSTEM prompt (persistent rules for all future generations). This mirrors how marina_agent works — thread context in user prompt, behavioral rules in system prompt.

## Source Material

### content_learnings table schema
```sql
CREATE TABLE IF NOT EXISTS content_learnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule TEXT NOT NULL,
    source_draft_ids TEXT DEFAULT '[]',
    active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
)
```

### distill_learnings response schema
```json
{
  "learnings": [
    {
      "rule": "Never use urgency language like 'last spots' or 'don't miss out' — the brand is premium, not desperate.",
      "source_pattern": "3 rejections cited 'too salesy' or 'urgency'"
    }
  ]
}
```

### System prompt injection format
```
BRAND LEARNINGS (from operator feedback — follow these strictly):
- Never use urgency language like 'last spots' or 'don't miss out'
- Keep sunset cruise posts focused on the experience, not the price
- Avoid mentioning specific guest counts or occupancy numbers
```

## Instructions

### Step 1 — Add content_learnings table to state_registry.py

**1a.** Add this table creation inside `_get_conn()`, after the `content_drafts` table creation:

```python
    conn.execute(
        "CREATE TABLE IF NOT EXISTS content_learnings ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "rule TEXT NOT NULL, "
        "source_draft_ids TEXT DEFAULT '[]', "
        "active INTEGER DEFAULT 1, "
        "created_at TEXT NOT NULL"
        ")"
    )
```

**1b.** Add these CRUD functions after `get_availability_summary()`, before the final `_get_conn().close()` line:

```python
def save_content_learning(rule: str, source_draft_ids: list = None) -> int:
    """Save a brand learning rule. Returns row id."""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO content_learnings (rule, source_draft_ids, active, created_at) "
        "VALUES (?, ?, 1, ?)",
        (rule, json.dumps(source_draft_ids or [], ensure_ascii=False),
         datetime.now(timezone.utc).isoformat())
    )
    learning_id = cur.lastrowid
    conn.commit()
    conn.close()
    return learning_id


def get_active_learnings() -> list:
    """Get all active brand learning rules. Oldest first (chronological order)."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, rule, source_draft_ids, created_at "
        "FROM content_learnings WHERE active = 1 ORDER BY created_at ASC"
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "rule": r[1],
         "source_draft_ids": json.loads(r[2] or "[]"), "created_at": r[3]}
        for r in rows
    ]


def deactivate_learning(learning_id: int) -> bool:
    """Deactivate a brand learning rule. Returns True if row updated."""
    conn = _get_conn()
    cur = conn.execute(
        "UPDATE content_learnings SET active = 0 WHERE id = ? AND active = 1",
        (learning_id,)
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed
```

**1c.** Update the file header to `# Last modified: Brief 093`.

### Step 2 — Add learnings to system prompt in content_agent.py

**2a.** In `_build_system_prompt(count)`, after loading config values (after line 87 `hashtag_style = ...`), add:

```python
    learnings = state_registry.get_active_learnings()
```

**2b.** In the system prompt f-string, insert a BRAND LEARNINGS section between the DEMAND-STATE RULES section and the RESPONSE FORMAT section. The section should only appear if learnings exist:

```python
    learnings_block = ""
    if learnings:
        rules = "\n".join(f"- {l['rule']}" for l in learnings)
        learnings_block = (
            f"\nBRAND LEARNINGS (from operator feedback — follow these strictly):\n"
            f"{rules}\n"
        )
```

Insert `{learnings_block}` in the f-string between the demand-state rules and the response format.

### Step 3 — Add distill_learnings() function to content_agent.py

Add this function after `generate_drafts()`:

```python
def distill_learnings() -> list:
    """Analyze rejected drafts and propose brand learning rules.
    Separate Claude call — not part of the generation flow.
    Returns list of saved learning dicts (with id from SQLite)."""
    rejected = state_registry.get_content_drafts(status="rejected", limit=50)
    rejections_with_reasons = [d for d in rejected if d.get("rejection_reason")]

    if not rejections_with_reasons:
        bm_logger.log("distill_no_rejections")
        return []

    # Build rejection summary for Claude
    rej_lines = []
    for d in rejections_with_reasons:
        cap = (d.get("instagram_caption") or "")[:100]
        rej_lines.append(
            f'  Draft #{d["id"]} [{d["content_class"]}]: "{cap}..."\n'
            f'  Rejection reason: {d["rejection_reason"]}'
        )
    rejection_summary = "\n\n".join(rej_lines)

    business = config_loader.get_business()
    business_name = business.get("name", "the business")

    # Existing learnings to avoid duplicates
    existing = state_registry.get_active_learnings()
    existing_block = ""
    if existing:
        existing_rules = "\n".join(f"- {l['rule']}" for l in existing)
        existing_block = (
            f"\nEXISTING RULES (already learned — do NOT duplicate these):\n"
            f"{existing_rules}\n"
        )

    system_prompt = (
        f"You analyze rejected social media draft posts for {business_name} and identify patterns.\n"
        f"Your job is to propose brand rules that will prevent similar rejections.\n"
        f"Each rule must be actionable and specific — not vague.\n"
        f"Only propose rules if you see a clear pattern across multiple rejections.\n"
        f"A single rejection is not enough to create a rule unless the reason is very specific.\n"
        f"{existing_block}\n"
        f"Return ONLY a JSON object. No explanation. No markdown. No code fences.\n"
        f'{{"learnings": [{{"rule": "<specific actionable rule>", '
        f'"source_pattern": "<what rejections led to this rule>"}}]}}'
    )

    user_prompt = (
        f"REJECTED DRAFTS ({len(rejections_with_reasons)} total):\n\n"
        f"{rejection_summary}\n\n"
        f"Analyze these rejections. Identify patterns. Propose brand rules."
    )

    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        client = anthropic.Anthropic(api_key=api_key)

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text.strip()

        _usage = getattr(response, "usage", None)
        if _usage:
            bm_logger.log("api_usage",
                          input_tokens=_usage.input_tokens,
                          output_tokens=_usage.output_tokens,
                          model="claude-sonnet-4-6",
                          channel="distill")

        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw.strip())

        result = json.loads(raw)
        if not isinstance(result, dict) or "learnings" not in result:
            bm_logger.log("distill_response_invalid", reason="missing_learnings_key")
            return []

        saved = []
        for item in result["learnings"]:
            if not isinstance(item, dict) or not item.get("rule"):
                continue
            # Collect source draft IDs from rejections that match this pattern
            source_ids = [d["id"] for d in rejections_with_reasons]
            learning_id = state_registry.save_content_learning(
                rule=item["rule"],
                source_draft_ids=source_ids,
            )
            learning = {"id": learning_id, "rule": item["rule"],
                        "source_draft_ids": source_ids,
                        "created_at": datetime.now(timezone.utc).isoformat()}
            saved.append(learning)

        bm_logger.log("distill_learnings_saved", count=len(saved))
        return saved

    except Exception as exc:
        bm_logger.log("distill_api_error", error=str(exc)[:200])
        return []
```

**3b.** Update the file header to `# Last modified: Brief 093`.

### Step 4 — Create test file

Create `tests/social/test_093_rejection_learning.py`:

**File header:**
```python
# bluemarlin/tests/social/test_093_rejection_learning.py
# Created: Brief 093
# Purpose: Tests for rejection learning system
```

**Setup:** Same pattern as test_092 — sys.path insert, set env vars.

**Imports (explicit):**
```python
from agents.social.content_agent import (
    _build_system_prompt,
    generate_drafts,
    distill_learnings,
)
from shared import state_registry
```

**Helpers:**
- `_cleanup_drafts()` — deletes all content_drafts rows
- `_cleanup_learnings()` — deletes all content_learnings rows
- `_cleanup_all()` — calls both

**Mock distill response:**
```python
MOCK_DISTILL_RESPONSE = json.dumps({
    "learnings": [
        {
            "rule": "Never use urgency language like 'last spots' or 'don't miss out'",
            "source_pattern": "3 rejections cited 'too salesy'"
        },
        {
            "rule": "Keep sunset cruise posts focused on the experience, not the price",
            "source_pattern": "2 rejections about sunset cruise pricing"
        }
    ]
})
```

**Tests (12 total):**

1. **`test_save_and_get_learning`** — Save a learning via `state_registry.save_content_learning("test rule")`. Call `state_registry.get_active_learnings()`. Assert returns 1 item with `rule == "test rule"` and `active` implied by appearing in results. Cleanup after.

2. **`test_deactivate_learning`** — Save a learning. Call `state_registry.deactivate_learning(learning_id)`. Assert returns True. Call `get_active_learnings()`. Assert returns 0 items. Cleanup after.

3. **`test_deactivate_already_inactive`** — Save a learning, deactivate it, deactivate again. Assert second deactivate returns False. Cleanup after.

4. **`test_system_prompt_includes_learnings`** — Save 2 learnings ("rule one", "rule two"). Call `_build_system_prompt(3)`. Assert prompt contains "BRAND LEARNINGS", "rule one", "rule two". Cleanup after.

5. **`test_system_prompt_no_learnings_section_when_empty`** — Ensure no learnings exist. Call `_build_system_prompt(3)`. Assert "BRAND LEARNINGS" NOT in prompt. Cleanup after.

6. **`test_system_prompt_excludes_inactive_learnings`** — Save 2 learnings. Deactivate one. Call `_build_system_prompt(3)`. Assert prompt contains the active rule but NOT the deactivated rule. Cleanup after.

7. **`test_distill_no_rejections_returns_empty`** — Ensure no rejected drafts exist. Call `distill_learnings()`. Assert returns empty list. Assert no learnings in DB. Cleanup after.

8. **`test_distill_saves_learnings`** — Create 3 rejected drafts:
```python
d1 = state_registry.save_content_draft("B", "Book now! Last spots!", "", [], "", "")
state_registry.update_draft_status(d1, "rejected", rejection_reason="too salesy")
d2 = state_registry.save_content_draft("B", "Hurry! Don't miss out!", "", [], "", "")
state_registry.update_draft_status(d2, "rejected", rejection_reason="wrong tone")
d3 = state_registry.save_content_draft("A", "We do boat trips.", "", [], "", "")
state_registry.update_draft_status(d3, "rejected", rejection_reason="too generic")
```
Mock Claude API to return `MOCK_DISTILL_RESPONSE`. Call `distill_learnings()`. Assert returns 2 learnings. Assert `get_active_learnings()` returns 2 items. Assert first learning rule contains "urgency". Cleanup after.

9. **`test_distill_includes_existing_learnings_in_prompt`** — Save a learning via `state_registry.save_content_learning("existing rule")`. Create 2 rejected drafts (same pattern as test 8, any captions/reasons). Mock Claude API to return `MOCK_DISTILL_RESPONSE`. Call `distill_learnings()`. Verify the mock was called. Extract the system prompt arg from `mock_client.messages.create.call_args`. Assert "EXISTING RULES" and "existing rule" appear in the system prompt (the `system` kwarg). Cleanup after.

10. **`test_distill_api_error_returns_empty`** — Create 2 rejected drafts (save + update_draft_status with any reason). Mock Claude API to raise exception. Call `distill_learnings()`. Assert returns empty list. Assert `get_active_learnings()` returns 0 items. Cleanup after.

11. **`test_learning_source_draft_ids`** — Save 2 drafts, capture their IDs:
```python
d1 = state_registry.save_content_draft("A", "Caption one", "", [], "", "")
state_registry.update_draft_status(d1, "rejected", rejection_reason="off-brand")
d2 = state_registry.save_content_draft("A", "Caption two", "", [], "", "")
state_registry.update_draft_status(d2, "rejected", rejection_reason="off-brand")
```
Mock Claude API to return a single-learning response. Call `distill_learnings()`. Assert saved learning has `source_draft_ids` containing both `d1` and `d2`. Cleanup after.

12. **`test_generate_drafts_uses_learnings`** — Save a learning "Never mention turtle petting". Mock Claude API for `generate_drafts()`. Call `generate_drafts(count=1)`. Extract the system prompt from the mock call args. Assert "Never mention turtle petting" appears in the system prompt. Cleanup after.

## Tests
Run: `cd bluemarlin && python3 -m pytest tests/social/test_093_rejection_learning.py -v`

All 12 tests must pass. Tests verify: learning CRUD, system prompt injection (present when active, absent when empty, excluded when inactive), distillation from rejections, existing learnings in distill prompt, error handling, source tracking, and integration with generate_drafts.

## Success Condition
Active brand learnings appear in the content agent's system prompt. `distill_learnings()` analyzes rejected drafts and produces actionable rules. Deactivated learnings disappear from the prompt. The learning loop is complete: reject → distill → learn → generate better.

## Rollback
1. Revert `agents/social/content_agent.py` to Brief 092 version
2. Revert `shared/state_registry.py` to Brief 092 version
3. Delete `tests/social/test_093_rejection_learning.py`
