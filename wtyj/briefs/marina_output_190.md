# OUTPUT 190 — Content pipeline archival: feature-gate the scheduler

## What was done

Wrapped `start_scheduler()` in `webhook_server.py`'s lifespan handler with a `features.content_pipeline` check (default `false`). No client.json has this key, so all three containers now boot without starting the auto-posting scheduler thread. Zero code deleted — scheduler, content_agent, graphics_engine, and social_publisher modules stay intact for future reactivation. Set the flag to `true` in any client's `client.json` to re-enable.

## Tests

891 passing / 0 failures (889 baseline + 2 new).

## Deployment

Commit `ad70328`. All containers healthy. Confirmed: `docker logs wtyj-bluemarlin` shows no "scheduler_started" log line — the scheduler is successfully gated off.
