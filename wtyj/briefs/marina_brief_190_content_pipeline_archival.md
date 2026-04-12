# BRIEF 190 — Content pipeline archival: feature-gate the scheduler
**Status:** Draft | **Files:** `wtyj/agents/social/webhook_server.py` | **Depends on:** — | **Blocks:** —

## Context

The content pipeline (draft generation → image compositing → multi-platform publishing via Zernio) runs via a background scheduler thread started at webhook server boot (`webhook_server.py:25`, called from the `lifespan` handler at line 24-27). The scheduler checks every 60s for scheduled posts and publishes them (`scheduler.py:24-31`). It runs for ALL clients regardless of whether they use the content pipeline — BlueMarlin, Adamus, and Roberto all start the scheduler thread on every container boot.

The content pipeline is being archived per the roadmap: the feature is not needed for the current client focus (customer support + booking), and running it adds unnecessary Claude API calls (draft generation) and Zernio API calls (publishing) for clients that don't want social media auto-posting.

No code is being deleted. The scheduler, content_agent, graphics_engine, auto_poster, and social_publisher modules stay intact. The dashboard's Content Pipeline page stays accessible (it just shows empty/stale data). The archive is a clean shutdown via a feature flag — flip the flag back to `true` to reactivate.

## Why This Approach

**Feature gate, not code deletion.** The content pipeline is production-proven code (~800 lines across 4 files, 5+ briefs of work). Deleting it saves zero runtime cost (the scheduler thread is cheap when idle) and destroys future optionality. A boolean check at the entry point is the minimum-cost archive that preserves full reactivation.

**Default to `false`.** New clients should NOT get the content pipeline unless explicitly opted in. Setting `features.content_pipeline` to default `false` means only clients whose `client.json` explicitly sets it to `true` will run the scheduler. Currently, no client.json has this key — so after this change, all three containers stop running the scheduler.

### Rejected alternatives

1. **Delete the scheduler files.** Rejected: destroys ~800 lines of working code. The pipeline may be reactivated for future clients (HD Azure, or a marketing-focused client). Deletion is permanent; a feature gate is reversible.
2. **Disable per-client via client.json only (no code change).** Rejected: there's no existing feature check around `start_scheduler()`. Without a code change, every client runs the scheduler regardless of config.

## Instructions

### Step 1 — Add feature gate in `webhook_server.py` lifespan handler

At `webhook_server.py:23-27`, the current lifespan handler:

```python
@asynccontextmanager
async def lifespan(app):
    from agents.social.scheduler import start_scheduler
    start_scheduler()
    yield
```

Replace with:

```python
@asynccontextmanager
async def lifespan(app):
    if config_loader.get_raw().get("features", {}).get("content_pipeline", False):
        from agents.social.scheduler import start_scheduler
        start_scheduler()
    yield
```

`config_loader` is already imported at `webhook_server.py:16`. The `start_scheduler` import moves inside the `if` block so the scheduler module isn't even loaded when the pipeline is off (avoids importing `social_publisher`, `graphics_engine`, etc. unnecessarily).

### Step 2 — Do NOT touch

- `scheduler.py`, `content_agent.py`, `graphics_engine.py`, `auto_poster.py`, `social_publisher.py` — untouched, preserved for future reactivation
- Dashboard API content pipeline endpoints — untouched (return empty/existing data)
- Any client.json file — no `content_pipeline` key is added; the absence of the key + default `False` means the pipeline is off
- Any test file — no existing tests exercise the scheduler startup path in a way that depends on it being called unconditionally

## Tests

Create `wtyj/tests/social/test_190_content_pipeline_gate.py` with 2 tests:

### Test 1 — Scheduler does NOT start when `content_pipeline` is false/absent

Mock `agents.social.webhook_server.config_loader.get_raw` to return `{"features": {}}` (no `content_pipeline` key). Mock `agents.social.scheduler.start_scheduler`. Enter the lifespan async context manager using `asyncio.run()`:

```python
import asyncio
from unittest.mock import patch, MagicMock

@patch("agents.social.scheduler.start_scheduler")
@patch("agents.social.webhook_server.config_loader")
def test_scheduler_not_started_when_pipeline_off(mock_config, mock_start):
    mock_config.get_raw.return_value = {"features": {}}
    from agents.social.webhook_server import lifespan
    async def _run():
        async with lifespan(MagicMock()):
            pass
    asyncio.run(_run())
    mock_start.assert_not_called()
```

The `lifespan` function is an `@asynccontextmanager` async generator — it MUST be entered via `async with`, not called directly.

### Test 2 — Scheduler DOES start when `content_pipeline` is true

Same pattern but with `content_pipeline: True`:

```python
@patch("agents.social.scheduler.start_scheduler")
@patch("agents.social.webhook_server.config_loader")
def test_scheduler_started_when_pipeline_on(mock_config, mock_start):
    mock_config.get_raw.return_value = {"features": {"content_pipeline": True}}
    from agents.social.webhook_server import lifespan
    async def _run():
        async with lifespan(MagicMock()):
            pass
    asyncio.run(_run())
    mock_start.assert_called_once()
```

## Success Condition

`python3 -m pytest wtyj/tests/ -q` reports **891 passed / 0 failed** (889 baseline + 2 new). After deploy, `docker logs wtyj-bluemarlin 2>&1 | grep scheduler` shows NO "scheduler_started" log line (confirming the scheduler is not running).

## Rollback

`git revert <commit>`. Removes the `if` wrapper — scheduler starts unconditionally again. Or: set `features.content_pipeline: true` in client.json for any client that needs it re-enabled.
