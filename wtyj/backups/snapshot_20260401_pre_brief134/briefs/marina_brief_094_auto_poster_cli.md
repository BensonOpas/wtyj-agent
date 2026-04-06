# BRIEF 094 — Auto Poster + CLI Review
**Status:** Draft | **Files:** `agents/social/auto_poster.py` (NEW), `tests/social/test_094_auto_poster.py` (NEW) | **Depends on:** Brief 092 (content agent core), Brief 093 (rejection learning) | **Blocks:** Brief 095+ (real publishing integration)

## Context
Briefs 092-093 built the content engine (generate drafts) and learning system (distill rejections). But there's no way to run any of this outside of a Python shell. For the demo with SR, we need an operational entry point: generate drafts, review them, approve/reject, and "publish" (stub for now — real Instagram/Facebook integration comes in a later brief when the publishing account is set up). This brief creates `auto_poster.py` — the command-line tool that ties the content pipeline together.

## Why This Approach
We considered building the publishing integration (Late/Buffer API) in this brief, but we don't have an account set up yet and the Meta permissions may take days. A stub publisher delivers the same demo value — SR sees the full flow (generate → review → approve → publish) working end-to-end, with "publish" logging to console and marking drafts as published in SQLite. When the real API is ready, we swap the stub for a real publisher in one brief. We chose CLI flags over a web dashboard because: no new infrastructure needed, runs anywhere Python runs, and the operator can see exactly what happened. The review mode is interactive (stdin) for human approval, matching SR's requirement that every post needs human green light.

## Source Material

### CLI interface
```
python3 agents/social/auto_poster.py --generate [--count N]
python3 agents/social/auto_poster.py --review
python3 agents/social/auto_poster.py --publish
python3 agents/social/auto_poster.py --distill
python3 agents/social/auto_poster.py --status
```

### --generate
Calls `content_agent.generate_drafts(count=N)` (default 3). Prints each generated draft summary to stdout.

### --review
Lists all pending drafts. For each draft, shows:
```
--- Draft #42 [Class A] ---
IG: Crystal-clear waters and white sand. Klein Curaçao is waiting.
FB: There's a small uninhabited island off the coast...
Tags: #KleinCuracao #BlueFinnCharters
Visual: aerial shot of Klein Curaçao beach
Reason: Class A evergreen — showcases flagship experience

[a]pprove / [r]eject / [s]kip?
```
- `a` → marks as approved
- `r` → prompts for rejection reason, marks as rejected with reason
- `s` → skips (stays pending)

### --publish
Takes all approved drafts and "publishes" them:
- Prints the caption + hashtags that would be posted
- Logs `bm_logger.log("content_published_stub", draft_id=..., platform="instagram")`
- Calls `state_registry.update_draft_status(draft_id, "published")`
- Prints confirmation

### --distill
Calls `content_agent.distill_learnings()`. Prints any new learnings discovered.

### --status
Prints counts: N pending, N approved, N rejected, N published, N active learnings.

## Instructions

### Step 1 — Create auto_poster.py

Create `agents/social/auto_poster.py`:

**File header:**
```python
# bluemarlin/agents/social/auto_poster.py
# Created: Brief 094
# Last modified: Brief 094
# Purpose: CLI entry point for content pipeline — generate, review, publish, distill.
```

**Imports:**
```python
import argparse
import sys
import os

# Ensure bluemarlin package root is on sys.path
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

from agents.social import content_agent
from shared import state_registry, bm_logger
```

**`cmd_generate(count)` function:**
1. Call `content_agent.generate_drafts(count=count)`
2. If empty result, print "No drafts generated (check API key or logs)." and return
3. For each draft, print a one-line summary: `"  #{id} [{content_class}] {instagram_caption[:70]}..."`
4. Print total: `"Generated {N} drafts."`

**`cmd_review()` function:**
1. Call `state_registry.get_content_drafts(status="pending")`
2. If empty, print "No pending drafts." and return
3. For each draft:
   - Print the full draft block (from Source Material `--review` format above)
   - Read input from stdin: `choice = input("[a]pprove / [r]eject / [s]kip? ").strip().lower()`
   - If `choice` starts with `"a"`: call `state_registry.update_draft_status(draft["id"], "approved")`, print "Approved."
   - If `choice` starts with `"r"`: prompt `reason = input("Rejection reason: ").strip()`, call `state_registry.update_draft_status(draft["id"], "rejected", rejection_reason=reason)`, print "Rejected."
   - Otherwise: print "Skipped."
4. Print summary: `"Review complete. {approved} approved, {rejected} rejected, {skipped} skipped."`

**`cmd_publish()` function:**
1. Call `state_registry.get_content_drafts(status="approved")`
2. If empty, print "No approved drafts to publish." and return
3. For each draft:
   - Print: `"Publishing #{id} [{content_class}]..."`
   - Print: `"  IG: {instagram_caption[:100]}"`
   - Print: `"  FB: {facebook_caption[:100]}"`
   - Print: `"  Tags: {' '.join(hashtags)}"`
   - Log: `bm_logger.log("content_published_stub", draft_id=draft["id"], platform="instagram+facebook")`
   - Call: `state_registry.update_draft_status(draft["id"], "published")`
   - Print: `"  → Published (stub)."`
4. Print total: `"Published {N} drafts (stub mode)."`

**`cmd_distill()` function:**
1. Call `content_agent.distill_learnings()`
2. If empty result, print "No new learnings (need more rejections with reasons)."
3. For each learning, print: `"  NEW RULE: {rule}"`
4. Print total: `"Distilled {N} new brand learnings."`

**`cmd_status()` function:**
1. Query counts:
   - `pending = len(state_registry.get_content_drafts(status="pending"))`
   - `approved = len(state_registry.get_content_drafts(status="approved"))`
   - `rejected = len(state_registry.get_content_drafts(status="rejected"))`
   - `published = len(state_registry.get_content_drafts(status="published"))`
   - `learnings = len(state_registry.get_active_learnings())`
2. Print:
```
Content Pipeline Status:
  Pending:    {pending}
  Approved:   {approved}
  Rejected:   {rejected}
  Published:  {published}
  Learnings:  {learnings} active
```

**`main()` function + argparse:**
```python
def main():
    parser = argparse.ArgumentParser(description="BluMarlin Content Pipeline")
    parser.add_argument("--generate", action="store_true", help="Generate new draft posts")
    parser.add_argument("--count", type=int, default=3, help="Number of drafts to generate (default: 3)")
    parser.add_argument("--review", action="store_true", help="Review pending drafts interactively")
    parser.add_argument("--publish", action="store_true", help="Publish approved drafts (stub)")
    parser.add_argument("--distill", action="store_true", help="Distill brand learnings from rejections")
    parser.add_argument("--status", action="store_true", help="Show pipeline status counts")
    args = parser.parse_args()

    if not any([args.generate, args.review, args.publish, args.distill, args.status]):
        parser.print_help()
        return

    if args.status:
        cmd_status()
    if args.generate:
        cmd_generate(args.count)
    if args.review:
        cmd_review()
    if args.publish:
        cmd_publish()
    if args.distill:
        cmd_distill()


if __name__ == "__main__":
    main()
```

### Step 2 — Create test file

Create `tests/social/test_094_auto_poster.py`:

**File header:**
```python
# bluemarlin/tests/social/test_094_auto_poster.py
# Created: Brief 094
# Purpose: Tests for auto_poster CLI entry point
```

**Setup:** sys.path insert, set env vars (same pattern as test_092).

**Imports:**
```python
from agents.social.auto_poster import cmd_generate, cmd_review, cmd_publish, cmd_distill, cmd_status
from agents.social import content_agent
from shared import state_registry
```

**Helpers:**
- `_cleanup_all()` — deletes all content_drafts and content_learnings rows
- `_mock_claude_response(json_str)` — same helper as test_092

**Tests (10 total):**

1. **`test_cmd_generate_creates_drafts`** — Mock Claude API to return 2 drafts (use MOCK_CLAUDE_RESPONSE_2 from test_092 pattern). Call `cmd_generate(2)` with capsys. Assert `state_registry.get_content_drafts()` has 2 rows. Assert stdout contains "Generated 2 drafts". Cleanup after.

2. **`test_cmd_generate_no_api_key`** — Mock Claude API to raise exception. Call `cmd_generate(3)` with capsys. Assert stdout contains "No drafts generated". Cleanup after.

3. **`test_cmd_status_counts`** — Save 2 pending drafts, 1 approved, 1 rejected, 1 published (use `save_content_draft` + `update_draft_status`). Save 1 active learning. Call `cmd_status()` with capsys. Assert stdout contains "Pending:    2", "Approved:   1", "Rejected:   1", "Published:  1", "Learnings:  1 active". Cleanup after.

4. **`test_cmd_review_approve`** — Save 1 pending draft. Mock `builtins.input` to return `"a"`. Call `cmd_review()` with capsys. Assert draft status changed to "approved". Assert stdout contains "Approved". Cleanup after.

5. **`test_cmd_review_reject`** — Save 1 pending draft. Mock `builtins.input` to return `"r"` on first call, then `"too salesy"` on second call (rejection reason). Call `cmd_review()` with capsys. Assert draft status is "rejected" and rejection_reason is "too salesy". Assert stdout contains "Rejected". Cleanup after.

6. **`test_cmd_review_skip`** — Save 1 pending draft. Mock `builtins.input` to return `"s"`. Call `cmd_review()` with capsys. Assert draft status is still "pending". Assert stdout contains "Skipped". Cleanup after.

7. **`test_cmd_review_empty`** — No pending drafts. Call `cmd_review()` with capsys. Assert stdout contains "No pending drafts". Cleanup after.

8. **`test_cmd_publish_stub`** — Save 1 draft, approve it. Call `cmd_publish()` with capsys. Assert draft status changed to "published". Assert stdout contains "Published" and "stub". Cleanup after.

9. **`test_cmd_publish_empty`** — No approved drafts. Call `cmd_publish()` with capsys. Assert stdout contains "No approved drafts". Cleanup after.

10. **`test_cmd_distill_from_rejections`** — Save 2 drafts, reject with reasons. Mock Claude API for distill. Call `cmd_distill()` with capsys. Assert stdout contains "NEW RULE" or "Distilled". Assert `get_active_learnings()` has items. Cleanup after.

For capsys usage, tests should use pytest's `capsys` fixture:
```python
def test_cmd_status_counts(capsys):
    ...
    cmd_status()
    captured = capsys.readouterr()
    assert "Pending:" in captured.out
```

For mocking input, use `unittest.mock.patch("builtins.input")`.

## Tests
Run: `cd bluemarlin && python3 -m pytest tests/social/test_094_auto_poster.py -v`

All 10 tests must pass. Tests verify each CLI command works independently: generation stores drafts, review approve/reject/skip update status correctly, publish marks as published, distill creates learnings, status shows correct counts.

## Success Condition
`python3 agents/social/auto_poster.py --generate && python3 agents/social/auto_poster.py --review && python3 agents/social/auto_poster.py --publish` runs the full content pipeline end-to-end from command line. Each step works independently and updates SQLite state correctly.

## Rollback
1. Delete `agents/social/auto_poster.py`
2. Delete `tests/social/test_094_auto_poster.py`
