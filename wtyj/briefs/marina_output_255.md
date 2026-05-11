# OUTPUT 255 — Email poller reloads email_thread_state per iteration

## What was done

P0 hotfix for issues #23 + #26 after Calvin's two HARD FAIL live verifications. `wtyj/agents/marina/email_poller.py:430` loaded `email_thread_state.json` once at process startup; the `while True:` loop mutated `state` in memory and wrote the whole snapshot back to disk via 14 `save_json` call sites. Every external disk write — Brief 254's `email_clear_fully_escalated_flag`, dashboard archive/delete endpoints, the j2-26 operator wipe — was silently overwritten on the very next inbound. Shipped a 5-line per-iteration reload at the top of the loop body so disk is the single source of truth. No other writers (`state_registry.py:2811` reads fresh; `dashboard/api.py` does not read this file) caused the bug; single fix point.

## Tests

1090 passing / 0 failures (1087 baseline + 3 new). Targeted file `wtyj/tests/marina/test_162_email_thread_persistence.py` runs 12/12 (was 9; added 3). Test 1 is a real behavioral regression guard — runs `main()` for 2 iterations with mocked IMAP/cleanup hooks, external writer empties disk between iterations, asserts iteration 2's captured state matches the externally-emptied disk content. If a future commit deletes the in-loop reload line, the test fails.

## Unexpected findings

Brief-reviewer round 1 caught three real issues that would have shipped a half-broken hotfix: (a) the brief proposed extending `test_171_email_dashboard.py` but that file covers `state_registry` email helpers, not `email_poller` — the canonical per-module file is `test_162_email_thread_persistence.py`. (b) The original three tests only exercised `load_json` (a 5-line stdlib wrapper) — none of them would have caught a regression of the change being shipped. Replaced test 1 with the integration test described above. (c) The rollback block used `git pull && docker compose restart`, which does not rebuild the image and only restarts one of the four containers sharing `wtyj-agent`. Replaced with the canonical `bash /root/wtyj/scripts/rollback.sh all` per `infra.md:188`. Round 2 PASS with one cosmetic line-citation note.

## Deployment

Source commit `5400e41`. [HOTFIX] subject so the CI pipeline bypasses the off-hours queue. All 4 containers healthy post-deploy. After deploy: restarted `wtyj-unboks`, re-executed the j2-26 wipe — disk wipe now stays applied across continuous polling because the poller picks up the empty disk state on each iteration.
