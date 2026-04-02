# OUTPUT 094 — Auto Poster + CLI Review

**Brief:** marina_brief_094_auto_poster_cli.md
**Status:** Complete
**Date:** 2026-03-16

## What Was Done

1. **auto_poster.py** created in agents/social/ — CLI entry point for the entire content pipeline. Five commands:
   - `--generate [--count N]` — calls content_agent.generate_drafts(), prints summaries
   - `--review` — interactive review of pending drafts (approve/reject with reason/skip)
   - `--publish` — stub-publishes approved drafts (logs + marks as published in SQLite)
   - `--distill` — calls content_agent.distill_learnings(), prints new rules
   - `--status` — shows pipeline counts (pending/approved/rejected/published/learnings)

2. **Full pipeline runnable from command line:**
   ```
   python3 agents/social/auto_poster.py --generate --count 5
   python3 agents/social/auto_poster.py --review
   python3 agents/social/auto_poster.py --publish
   python3 agents/social/auto_poster.py --distill
   python3 agents/social/auto_poster.py --status
   ```

## Test Results
```
auto poster tests: 10/10 PASSED
social regression: 143/143 PASSED
```

## Unexpected
Nothing unexpected.
