# BRIEF 196 — Deploy queue: production-only off-hours gate + scheduled auto-deploy + control panel visualization

**Status:** Draft | **Files:** `wtyj/scripts/off_hours_check.py`, `wtyj/tests/scripts/test_off_hours_check.py`, `wtyj/shared/deploy_queue.py` (NEW), `wtyj/tests/shared/test_deploy_queue.py` (NEW), `wtyj/scripts/queue_enqueue.py` (NEW), `wtyj/scripts/process_deploy_queue.sh` (NEW), `.github/workflows/ci-deploy.yml`, `.github/workflows/scheduled-deploy.yml` (NEW), `tools/control-panel/server.js`, `tools/control-panel/src/App.tsx`, `tools/control-panel/src/pages/Deploys.tsx` (NEW), `tools/control-panel/src/styles.css`, `wtyj/briefs/infra.md` | **Depends on:** Brief 195 (canary pipeline) | **Blocks:** —

## Context

Brief 195 shipped the canary pipeline but with two design holes:

1. **Off-hours gate blocks the canary, not just production.** Per `project_live_preparations.md` the decided model is "production deploys blocked" — canary should always run because that's the test environment. As shipped, off-hours-check fails the WHOLE pipeline (canary included), so during business hours we can't even validate code on BlueMarlin.

2. **No queue mechanism — pushes during business hours just fail.** The CI shows red, you have to push another commit (or wait until off-hours and manually retrigger) to deploy. No visibility into what's pending.

Plus a small bug from Brief 195: the `[HOTFIX]` bypass uses naive substring match, so ANY mention of `[HOTFIX]` in the commit body (e.g., docs describing the bypass) accidentally bypasses. My own Brief 195 commit message accidentally bypassed for this reason.

This brief: drop Madrid (Curaçao only — decided), restructure the workflow so canary always runs and only production gates, add a deploy queue file on the VPS, add a scheduled workflow that drains the queue during off-hours, and add a "Deploys" tab to the control panel showing the queue + history.

## Why This Approach

**Canary always runs, only production gates.** Splits the workflow into `deploy-canary` (no off-hours condition) and `deploy-production` (gated by `off-hours-decide` job's output). You always learn within ~2 minutes of pushing whether your code works on BlueMarlin under real conditions, regardless of time of day.

**Queue lives on VPS as JSON, not in git.** State that mutates frequently (push enqueues, scheduled run dequeues) shouldn't be in git — would create commit-loop risk and pollute history. File at `/root/wtyj_deploy_queue.json` (host root, system-wide deploy state — not BlueMarlin-specific). Control panel reads via SSH from server.js. The Python module reads `DEPLOY_QUEUE_PATH` env var with fallback to that path; tests override via monkeypatch to a tmp file.

**One Python module owns queue I/O (`wtyj/shared/deploy_queue.py`).** Same pattern as `state_registry.py`. CLI script `queue_enqueue.py` and bash script `process_deploy_queue.sh` both delegate to this module. Single source of truth for the file format and atomic-write logic. Testable.

**fcntl.flock on a sidecar lock file for ALL queue mutations.** Concurrent writers (CI workflow's deploy-production + scheduled cron's process_deploy_queue.sh + a fresh push enqueueing) can collide otherwise. Single-writer assumption is not enough — both jobs CAN fire simultaneously near boundaries. Lock is held only during read-modify-write (microseconds), not for the entire deploy. Lock file: `/root/wtyj_deploy_queue.json.lock`.

**Snapshot acknowledged briefs at claim time, not complete time.** When `claim_for_deploy()` runs, it MOVES all queued entries into `in_progress.acknowledged_briefs` and clears `queued`. New pushes during the deploy land in the now-empty `queued` list and stay there. `complete_deploy()` only writes history for the entries it claimed. Prevents the "new push silently absorbed into in-flight deploy" race.

**Latest-SHA-deploys with multi-brief history.** When the scheduled workflow fires and there are 3 acknowledged briefs, it deploys the latest acknowledged SHA (which contains all 3 briefs' code — that's how linear git works) and writes 3 separate history entries (one per brief) all with the same `deployed_at` timestamp. User sees each brief acknowledged in the history; the actual deploy is one operation. This addresses Benson's concern that "latest doesn't cover the ones behind" — it does, but each brief still gets a visible history entry.

**`[HOTFIX]` bypass: subject-line only.** Currently `"[HOTFIX]" in commit_message` matches anywhere. New behavior: `"[HOTFIX]" in commit_message.split('\n', 1)[0]` — only the first line (subject) counts. Body text mentioning `[HOTFIX]` no longer bypasses.

**Subject passed via base64, not raw shell quoting.** A commit subject containing `"`, `` ` ``, `$`, or backslash breaks raw `python3 ... --subject "$SUBJECT"` shell interpolation. Workflow steps base64-encode subject, Python script base64-decodes. Bulletproof for any UTF-8 subject.

**SSH command in server.js relies on existing `~/.ssh/known_hosts` — no `StrictHostKeyChecking=no`.** Benson has SSH'd to the VPS already, host key is in known_hosts. Standard ssh works without flags.

**Madrid dropped entirely.** Per Benson 2026-04-14: "forget the madrid time, account for cur only." Removes the `MADRID` constants, the dual-timezone branch, and Madrid-specific tests.

**Control panel reads via SSH from server.js, not via a new dashboard API endpoint.** Adding `exec('ssh root@vps cat /root/wtyj_deploy_queue.json')` is 5 lines. A proper auth-required dashboard endpoint would need credential storage in the control panel + token caching — overkill for v1. If a second consumer ever needs the queue, add the endpoint then.

**Scheduled workflow runs every 30 min, every day (not just off-hours window).** Cron `0,30 * * * *`. The script's own off-hours check + queue-empty check + lock check makes it a no-op when nothing to do. Cheap, safe, simpler cron expression.

### Boundary skew (acknowledged limitation)

Off-hours-decide runs on GitHub Actions runner; process_deploy_queue.sh runs on VPS. Their clocks should agree (both use NTP) but in the rare ~1-second window near a transition, one might say "off-hours" and the other "business hours." Worst case: a push at exactly 20:00:00 AST gets queued (off-hours-decide says blocked) but the immediate cron run rejects it (process script says still business hours). Next cron at +30 min picks it up. Acceptable: 30-min latency at the edge case.

### Rejected alternatives

1. **Queue in git as `.github/deploy_state.json`.** Each enqueue would need a commit-back, triggering another workflow, infinite loop unless mitigated with `[skip ci]`. Brittle. VPS file is simpler.
2. **Per-brief separate production deploy (deploy 3 SHAs sequentially).** Each one rebuilds the same image (or pulls from `:<sha>` archive), restarts containers 3x, takes 9+ minutes. Wasteful when "latest" code already includes all 3. Collapse to one deploy + 3 history entries.
3. **Auth-required dashboard endpoint instead of SSH from server.js.** Cleaner long-term but doubles the brief size (Python endpoint + tests + token plumbing in control panel). Defer until needed.
4. **First-line-prefix-only `[HOTFIX]` (must be at start of subject).** Stricter but inconsistent with how trailers work. Subject-line `in` allows `[HOTFIX] Brief 200: fix auth` and `Brief 200: [HOTFIX] fix auth` — both natural. Subject-line scope is the right boundary.
5. **OS lock files (`os.O_EXCL`).** Doesn't work cleanly with stale-lock recovery (process killed mid-deploy → lock file orphaned). `fcntl.flock` releases on FD close (including process death) — robust.
6. **Hold lock for entire deploy duration.** Would block enqueues for 5+ min during deploy. Lock only during the read-modify-write of state, not during the deploy itself.

## Instructions

### Step 1 — Modify `wtyj/scripts/off_hours_check.py`

Replace contents with:

```python
#!/usr/bin/env python3
"""Off-hours enforcement for production deploys.
Blocks deploys during Curaçao business hours (05:30-20:00 AST, no DST).
Bypass: include [HOTFIX] in the commit SUBJECT LINE (first line only).
Exits 0 when deploy is allowed, 1 when blocked (reason printed to stdout).
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


CURACAO = ZoneInfo("America/Curacao")
CURACAO_START = 5 * 60 + 30   # 05:30
CURACAO_END   = 20 * 60       # 20:00 (exclusive)


def _hotfix_in_subject(commit_message: str) -> bool:
    """Only the first line (subject) counts. Body text mentions don't bypass."""
    subject = commit_message.split("\n", 1)[0]
    return "[HOTFIX]" in subject


def is_deploy_blocked(now_utc: datetime, commit_message: str) -> tuple[bool, str]:
    """Return (blocked, reason). blocked=True means refuse production deploy."""
    if _hotfix_in_subject(commit_message):
        return (False, "HOTFIX bypass — proceeding during business hours")
    cura = now_utc.astimezone(CURACAO)
    mod = cura.hour * 60 + cura.minute
    if CURACAO_START <= mod < CURACAO_END:
        return (True,
                f"Blocked: Curaçao business hours "
                f"({cura.strftime('%H:%M')} AST). "
                f"Bypass: [HOTFIX] in commit subject line.")
    return (False,
            f"Off-hours (Curaçao {cura.strftime('%H:%M')}) — proceeding")


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--commit-message", required=True)
    args = p.parse_args()
    blocked, reason = is_deploy_blocked(datetime.now(timezone.utc),
                                        args.commit_message)
    print(reason)
    sys.exit(1 if blocked else 0)


if __name__ == "__main__":
    main()
```

### Step 2 — Replace `wtyj/tests/scripts/test_off_hours_check.py`

Five tests:

```python
from datetime import datetime, timezone
from scripts.off_hours_check import is_deploy_blocked


def _utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 4, 14, hour, minute, tzinfo=timezone.utc)


def test_blocked_during_curacao_business_hours():
    blocked, reason = is_deploy_blocked(_utc(15, 0), "Brief 196: ship")
    assert blocked is True
    assert "Curaçao business hours" in reason


def test_not_blocked_outside_business_hours():
    blocked, reason = is_deploy_blocked(_utc(2, 0), "Brief 196: ship")
    assert blocked is False
    assert "Off-hours" in reason


def test_hotfix_in_subject_bypasses():
    blocked, reason = is_deploy_blocked(_utc(15, 0), "Brief 200: [HOTFIX] auth")
    assert blocked is False
    assert "HOTFIX bypass" in reason


def test_hotfix_only_in_body_does_not_bypass():
    msg = "Brief 196: ship feature\n\nThis adds [HOTFIX] bypass docs."
    blocked, reason = is_deploy_blocked(_utc(15, 0), msg)
    assert blocked is True
    assert "Curaçao business hours" in reason


def test_curacao_boundary_exit_allowed():
    blocked, _ = is_deploy_blocked(_utc(0, 0), "Brief 196: ship")
    assert blocked is False
```

### Step 3 — Create `wtyj/shared/deploy_queue.py`

Atomic file I/O with fcntl lock. State schema: `queued` (waiting), `in_progress` (currently deploying with `acknowledged_briefs` snapshot), `history` (last 30 deploys).

```python
"""Deploy queue: tracks pushes blocked from production deploy by off-hours.
Atomic file writes via temp + rename, locked with fcntl.flock on a sidecar
lock file. All read-modify-write operations go through _with_lock() to
prevent concurrent claim/enqueue/complete from racing."""
from __future__ import annotations
import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

QUEUE_PATH = os.environ.get("DEPLOY_QUEUE_PATH",
                             "/root/wtyj_deploy_queue.json")
HISTORY_MAX = 30
_BRIEF_RE = re.compile(r"\bBrief\s+(\d+)", re.IGNORECASE)


def _empty_state() -> dict:
    return {"queued": [], "in_progress": None, "history": []}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def extract_brief_number(commit_message: str) -> Optional[int]:
    m = _BRIEF_RE.search(commit_message or "")
    return int(m.group(1)) if m else None


@contextmanager
def _with_lock():
    """Acquire exclusive fcntl lock on a sidecar lock file. Released on FD
    close (including unclean process exit). Lock duration is microseconds —
    only the read-modify-write sequence."""
    lock_path = QUEUE_PATH + ".lock"
    os.makedirs(os.path.dirname(QUEUE_PATH) or ".", exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _read_unlocked() -> dict:
    try:
        with open(QUEUE_PATH, "r") as f:
            data = json.load(f)
        for k, default in (("queued", []), ("in_progress", None), ("history", [])):
            data.setdefault(k, default)
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return _empty_state()


def _write_unlocked(state: dict) -> None:
    target_dir = os.path.dirname(QUEUE_PATH) or "."
    os.makedirs(target_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".deploy_queue.", suffix=".json",
                                dir=target_dir)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, QUEUE_PATH)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def read_state() -> dict:
    """Read-only access (no lock needed for read-only consumers like the
    control panel)."""
    return _read_unlocked()


def enqueue(sha: str, short_sha: str, subject: str) -> dict:
    """Add to queue. Idempotent on (sha) — same SHA already queued or
    currently in_progress.acknowledged_briefs returns existing state."""
    with _with_lock():
        state = _read_unlocked()
        if any(e["sha"] == sha for e in state["queued"]):
            return state
        in_prog = state.get("in_progress") or {}
        ack = in_prog.get("acknowledged_briefs", [])
        if any(e["sha"] == sha for e in ack):
            return state
        state["queued"].append({
            "sha": sha,
            "short_sha": short_sha,
            "brief": extract_brief_number(subject),
            "subject": subject,
            "queued_at": _now_iso(),
        })
        _write_unlocked(state)
        return state


def claim_for_deploy() -> Optional[dict]:
    """Atomically: if in_progress is None and queue non-empty, MOVE all
    queued entries into in_progress.acknowledged_briefs, set deploy_sha to
    the latest queued entry, clear queued, and return the in_progress dict.
    New pushes that arrive during deploy land in queued (now empty) and
    are NOT swept by complete_deploy."""
    with _with_lock():
        state = _read_unlocked()
        if state.get("in_progress"):
            return None
        if not state["queued"]:
            return None
        latest = state["queued"][-1]
        in_progress = {
            "deploy_sha": latest["sha"],
            "deploy_short_sha": latest["short_sha"],
            "deploy_brief": latest["brief"],
            "deploy_subject": latest["subject"],
            "started_at": _now_iso(),
            "acknowledged_briefs": list(state["queued"]),
        }
        state["in_progress"] = in_progress
        state["queued"] = []
        _write_unlocked(state)
        return in_progress


def complete_deploy(status: str, duration_s: int) -> None:
    """Move in_progress.acknowledged_briefs to history with the same
    deployed_at timestamp + status. Clear in_progress. Queue is untouched
    (any pushes that arrived during the deploy stay in queued)."""
    with _with_lock():
        state = _read_unlocked()
        in_prog = state.get("in_progress")
        if not in_prog:
            return
        deployed_at = _now_iso()
        deploy_sha = in_prog["deploy_sha"]
        for entry in in_prog.get("acknowledged_briefs", []):
            state["history"].insert(0, {
                "sha": entry["sha"],
                "short_sha": entry["short_sha"],
                "brief": entry["brief"],
                "subject": entry["subject"],
                "deployed_at": deployed_at,
                "duration_s": duration_s,
                "status": status,
                "deployed_via_sha": deploy_sha,
            })
        state["history"] = state["history"][:HISTORY_MAX]
        state["in_progress"] = None
        _write_unlocked(state)
```

### Step 4 — Create `wtyj/tests/shared/test_deploy_queue.py`

Six tests:

```python
import json
import os
import pytest
from shared import deploy_queue


@pytest.fixture(autouse=True)
def isolated_queue(monkeypatch, tmp_path):
    qpath = str(tmp_path / "deploy_queue.json")
    monkeypatch.setattr(deploy_queue, "QUEUE_PATH", qpath)
    yield qpath


def test_extract_brief_number_from_various_messages():
    assert deploy_queue.extract_brief_number("Brief 196: foo") == 196
    assert deploy_queue.extract_brief_number("brief 12 — bar") == 12
    assert deploy_queue.extract_brief_number("CI: retry health check") is None
    assert deploy_queue.extract_brief_number("Brief: 196") is None  # no digit after Brief
    assert deploy_queue.extract_brief_number("") is None


def test_enqueue_appends_with_brief_extraction():
    state = deploy_queue.enqueue("abc123", "abc123", "Brief 196: ship queue")
    assert len(state["queued"]) == 1
    assert state["queued"][0]["brief"] == 196
    assert state["queued"][0]["sha"] == "abc123"
    assert state["queued"][0]["subject"] == "Brief 196: ship queue"


def test_enqueue_is_idempotent_on_same_sha():
    deploy_queue.enqueue("abc", "abc", "Brief 1")
    deploy_queue.enqueue("abc", "abc", "Brief 1")
    state = deploy_queue.enqueue("abc", "abc", "Brief 1")
    assert len(state["queued"]) == 1


def test_claim_moves_all_queued_to_in_progress_and_clears_queue():
    deploy_queue.enqueue("a", "a", "Brief 1")
    deploy_queue.enqueue("b", "b", "Brief 2")
    deploy_queue.enqueue("c", "c", "Brief 3")
    claimed = deploy_queue.claim_for_deploy()
    assert claimed["deploy_sha"] == "c"  # latest = freshest main
    assert len(claimed["acknowledged_briefs"]) == 3
    state = deploy_queue.read_state()
    assert state["queued"] == []
    assert state["in_progress"]["deploy_sha"] == "c"
    # Second claim while in_progress is set returns None
    assert deploy_queue.claim_for_deploy() is None


def test_enqueue_during_in_progress_lands_in_fresh_queue():
    """A push that arrives during a deploy must NOT be swept by complete_deploy."""
    deploy_queue.enqueue("a", "a", "Brief 1")
    deploy_queue.claim_for_deploy()  # acknowledges Brief 1
    # New push arrives mid-deploy
    deploy_queue.enqueue("b", "b", "Brief 2")
    state = deploy_queue.read_state()
    assert len(state["queued"]) == 1
    assert state["queued"][0]["sha"] == "b"
    assert len(state["in_progress"]["acknowledged_briefs"]) == 1
    # Complete the in-flight deploy
    deploy_queue.complete_deploy("success", duration_s=87)
    state = deploy_queue.read_state()
    # Brief 1 in history (acknowledged at claim time)
    assert len(state["history"]) == 1
    assert state["history"][0]["sha"] == "a"
    # Brief 2 still in queue (arrived after claim)
    assert len(state["queued"]) == 1
    assert state["queued"][0]["sha"] == "b"
    assert state["in_progress"] is None


def test_complete_writes_per_brief_history_with_shared_timestamp():
    deploy_queue.enqueue("a", "a", "Brief 1: A")
    deploy_queue.enqueue("b", "b", "Brief 2: B")
    deploy_queue.claim_for_deploy()
    deploy_queue.complete_deploy("success", duration_s=87)
    state = deploy_queue.read_state()
    assert state["queued"] == []
    assert state["in_progress"] is None
    assert len(state["history"]) == 2
    assert state["history"][0]["deployed_via_sha"] == "b"
    assert state["history"][1]["deployed_via_sha"] == "b"
    assert state["history"][0]["deployed_at"] == state["history"][1]["deployed_at"]
    assert all(h["status"] == "success" for h in state["history"])
    assert all(h["duration_s"] == 87 for h in state["history"])
```

### Step 5 — Create `wtyj/scripts/queue_enqueue.py`

CLI wrapper. Subject is base64-encoded to survive shell quoting issues.

```python
#!/usr/bin/env python3
"""Enqueue a commit for off-hours production deploy. Called by CI workflow.
Subject is base64-encoded by the caller to survive shell quoting issues
with quotes / backticks / dollar signs in commit messages."""
import argparse
import base64
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from shared import deploy_queue


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sha", required=True)
    p.add_argument("--short-sha", required=True)
    p.add_argument("--subject-b64", required=True,
                   help="Base64-encoded commit subject (UTF-8)")
    args = p.parse_args()
    subject = base64.b64decode(args.subject_b64).decode("utf-8")
    state = deploy_queue.enqueue(args.sha, args.short_sha, subject)
    print(f"Enqueued. Queue length: {len(state['queued'])}")


if __name__ == "__main__":
    main()
```

### Step 6 — Create `wtyj/scripts/process_deploy_queue.sh`

Idempotent. Sets `DEPLOY_QUEUE_PATH` explicitly; no off-hours skip when invoked from CI's deploy-production job (which has already passed off-hours-decide).

```bash
#!/bin/bash
# Process deploy queue: deploy claimed SHAs to paying clients if off-hours.
# Idempotent: safe to run on cron every 30 min — no-ops when nothing to do.
# Honors $SKIP_OFF_HOURS_CHECK=1 (set by CI's deploy-production which already
# decided off-hours is OK and may be at the boundary).
set -e

export DEPLOY_QUEUE_PATH="${DEPLOY_QUEUE_PATH:-/root/wtyj_deploy_queue.json}"
cd /root

# Off-hours check (skip if CI already decided)
if [ "${SKIP_OFF_HOURS_CHECK:-0}" != "1" ]; then
  COMMIT_MSG=$(git log -1 --pretty=%B)
  if ! python3 /root/wtyj/scripts/off_hours_check.py --commit-message "$COMMIT_MSG"; then
    echo "Currently business hours — skipping queue processing"
    exit 0
  fi
fi

# Atomically claim a deploy task (returns JSON or empty)
CLAIM=$(python3 -c "
import sys, json
sys.path.insert(0, '/root/wtyj')
from shared import deploy_queue
c = deploy_queue.claim_for_deploy()
print(json.dumps(c) if c else '')
")

if [ -z "$CLAIM" ]; then
  echo "Nothing to deploy (queue empty or another deploy in progress)"
  exit 0
fi

SHA=$(echo "$CLAIM" | python3 -c "import sys,json; print(json.load(sys.stdin)['deploy_short_sha'])")
echo "Deploying claimed SHA: $SHA"
START=$(date +%s)

# Pre-deploy snapshot
bash /root/wtyj/scripts/pre_deploy_snapshot.sh "$SHA"

# Deploy paying clients (image already built by canary, just restart)
STATUS="success"
for client in adamus consultadespertares; do
  cd /root/clients/$client
  if ! (docker compose down && docker compose up -d); then
    STATUS="failed"
    break
  fi
done

# Health check with retry
if [ "$STATUS" = "success" ]; then
  for p in 8002 8003; do
    OK=0
    for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
      if curl -sf -m 3 http://localhost:$p/health | grep -q '"ok"'; then
        OK=1; break
      fi
      sleep 5
    done
    if [ "$OK" = "0" ]; then
      STATUS="failed"
      bash /root/wtyj/scripts/rollback.sh all || true
      break
    fi
  done
fi

DURATION=$(( $(date +%s) - START ))

# Mark complete in queue (writes per-brief history)
python3 -c "
import sys
sys.path.insert(0, '/root/wtyj')
from shared import deploy_queue
deploy_queue.complete_deploy('$STATUS', $DURATION)
"

echo "Deploy $STATUS in ${DURATION}s"
[ "$STATUS" = "success" ] && exit 0 || exit 1
```

### Step 7 — Restructure `.github/workflows/ci-deploy.yml`

Replace contents:

```yaml
name: CI/CD — Test + Canary + Production (off-hours)

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt && pip install pytest
      - env:
          ANTHROPIC_API_KEY: "test-key"
          DASHBOARD_PASSWORD: "testpass"
          WHATSAPP_VERIFY_TOKEN: "test"
          WHATSAPP_PHONE_NUMBER_ID: "test"
          META_ACCESS_TOKEN: "test"
          LATE_API_KEY: "test"
          ZERNIO_WEBHOOK_SECRET: "test"
          CLIENT_CONFIG_PATH: "clients/bluemarlin/config/client.json"
        run: python -m pytest wtyj/tests/ -q --tb=short

  deploy-canary:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    steps:
      - name: Build + deploy staging + BlueMarlin canary + E2E
        uses: appleboy/ssh-action@v1.2.0
        with:
          host: ${{ secrets.VPS_HOST }}
          username: ${{ secrets.VPS_USER }}
          key: ${{ secrets.VPS_SSH_KEY }}
          command_timeout: 10m
          script: |
            set -e
            cd /root && git pull
            SHA=$(git rev-parse --short HEAD)
            chmod +x wtyj/scripts/*.sh
            docker tag wtyj-agent:latest wtyj-agent:previous 2>/dev/null || \
              echo "No previous (first run)"
            cd /root/clients/bluemarlin && docker compose build
            docker tag wtyj-agent:latest wtyj-agent:$SHA
            docker tag wtyj-agent:latest wtyj-agent:staging
            cd /root/staging && docker compose down && docker compose up -d
            for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
              curl -sf -m 3 http://localhost:9001/health | grep -q '"ok"' && break
              [ "$attempt" = "12" ] && { echo "STAGING FAILED"; exit 1; }
              sleep 5
            done
            cd /root/clients/bluemarlin && docker compose down && docker compose up -d
            for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
              curl -sf -m 3 http://localhost:8001/health | grep -q '"ok"' && break
              [ "$attempt" = "12" ] && {
                bash /root/wtyj/scripts/rollback.sh bluemarlin || true; exit 1; }
              sleep 5
            done
            if ! bash /root/wtyj/scripts/e2e_canary_test.sh; then
              bash /root/wtyj/scripts/rollback.sh bluemarlin || true
              exit 1
            fi

  off-hours-decide:
    needs: deploy-canary
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    outputs:
      action: ${{ steps.check.outputs.action }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - id: check
        name: Decide deploy or queue
        run: |
          COMMIT_MSG=$(git log -1 --pretty=%B)
          if python3 wtyj/scripts/off_hours_check.py --commit-message "$COMMIT_MSG"; then
            echo "action=deploy" >> "$GITHUB_OUTPUT"
            echo "Off-hours — proceeding with production deploy"
          else
            echo "action=queue" >> "$GITHUB_OUTPUT"
            echo "Business hours — queuing for off-hours deploy"
          fi
      - name: Enqueue when blocked
        if: steps.check.outputs.action == 'queue'
        uses: appleboy/ssh-action@v1.2.0
        with:
          host: ${{ secrets.VPS_HOST }}
          username: ${{ secrets.VPS_USER }}
          key: ${{ secrets.VPS_SSH_KEY }}
          script: |
            export DEPLOY_QUEUE_PATH=/root/wtyj_deploy_queue.json
            cd /root && git pull
            FULL_SHA=$(git rev-parse HEAD)
            SHORT_SHA=$(git rev-parse --short HEAD)
            SUBJECT_B64=$(git log -1 --pretty=%s | base64 -w0)
            python3 /root/wtyj/scripts/queue_enqueue.py \
              --sha "$FULL_SHA" --short-sha "$SHORT_SHA" --subject-b64 "$SUBJECT_B64"

  deploy-production:
    needs: off-hours-decide
    runs-on: ubuntu-latest
    if: needs.off-hours-decide.outputs.action == 'deploy' && github.ref == 'refs/heads/main' && github.event_name == 'push'
    steps:
      - name: Snapshot DBs + deploy paying clients + record history
        uses: appleboy/ssh-action@v1.2.0
        with:
          host: ${{ secrets.VPS_HOST }}
          username: ${{ secrets.VPS_USER }}
          key: ${{ secrets.VPS_SSH_KEY }}
          command_timeout: 10m
          script: |
            set -e
            export DEPLOY_QUEUE_PATH=/root/wtyj_deploy_queue.json
            export SKIP_OFF_HOURS_CHECK=1
            cd /root
            FULL_SHA=$(git rev-parse HEAD)
            SHORT_SHA=$(git rev-parse --short HEAD)
            SUBJECT_B64=$(git log -1 --pretty=%s | base64 -w0)
            chmod +x /root/wtyj/scripts/*.sh

            # Enqueue current commit so it appears in queue → in_progress → history
            python3 /root/wtyj/scripts/queue_enqueue.py \
              --sha "$FULL_SHA" --short-sha "$SHORT_SHA" --subject-b64 "$SUBJECT_B64"

            # Process queue: claim + deploy + complete (writes history)
            bash /root/wtyj/scripts/process_deploy_queue.sh
```

### Step 8 — Create `.github/workflows/scheduled-deploy.yml`

```yaml
name: Scheduled production deploy (drains queue at off-hours)

on:
  schedule:
    - cron: '0,30 * * * *'   # every 30 min, every day
  workflow_dispatch:           # manual trigger from control panel "deploy now"

jobs:
  drain-queue:
    runs-on: ubuntu-latest
    steps:
      - name: Process queue if off-hours and queue non-empty
        uses: appleboy/ssh-action@v1.2.0
        with:
          host: ${{ secrets.VPS_HOST }}
          username: ${{ secrets.VPS_USER }}
          key: ${{ secrets.VPS_SSH_KEY }}
          command_timeout: 10m
          script: |
            export DEPLOY_QUEUE_PATH=/root/wtyj_deploy_queue.json
            chmod +x /root/wtyj/scripts/*.sh
            bash /root/wtyj/scripts/process_deploy_queue.sh
```

### Step 9 — Modify `tools/control-panel/server.js`

Add two endpoints:

```javascript
// Add near other route definitions
app.get('/api/deploys/state', (_req, res) => {
  const { exec } = require('child_process')
  exec(
    'ssh root@108.61.192.52 "cat /root/wtyj_deploy_queue.json 2>/dev/null || echo \'{}\'"',
    { timeout: 5000 },
    (err, stdout) => {
      if (err) return res.status(500).json({ error: err.message })
      try {
        const parsed = JSON.parse(stdout || '{}')
        res.json({
          queued: parsed.queued || [],
          in_progress: parsed.in_progress || null,
          history: parsed.history || [],
        })
      } catch (e) {
        res.status(500).json({ error: 'parse failed', raw: stdout })
      }
    }
  )
})

app.post('/api/deploys/trigger', (_req, res) => {
  const { exec } = require('child_process')
  exec(
    'gh workflow run scheduled-deploy.yml -R BensonOpas/wtyj-agent',
    { timeout: 8000 },
    (err, stdout, stderr) => {
      if (err) return res.status(500).json({ error: err.message, stderr })
      res.json({ ok: true, message: 'Triggered scheduled-deploy workflow' })
    }
  )
})
```

### Step 10 — Create `tools/control-panel/src/pages/Deploys.tsx`

```tsx
import { useState, useEffect } from 'react'

interface QueuedEntry {
  sha: string; short_sha: string; brief: number | null; subject: string; queued_at: string
}
interface AcknowledgedBrief {
  sha: string; short_sha: string; brief: number | null; subject: string; queued_at: string
}
interface InProgress {
  deploy_sha: string; deploy_short_sha: string; deploy_brief: number | null;
  deploy_subject: string; started_at: string; acknowledged_briefs: AcknowledgedBrief[]
}
interface HistoryEntry {
  sha: string; short_sha: string; brief: number | null; subject: string;
  deployed_at: string; duration_s: number; status: string; deployed_via_sha: string
}
interface DeployState {
  queued: QueuedEntry[]
  in_progress: InProgress | null
  history: HistoryEntry[]
}

function timeAgo(iso: string): string {
  const sec = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (sec < 60) return `${sec}s ago`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`
  return `${Math.floor(sec / 86400)}d ago`
}

function nextOffHoursWindow(): string {
  const now = new Date()
  const next = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(),
                                  now.getUTCDate() + 1, 0, 0, 0))
  const ms = next.getTime() - now.getTime()
  const hrs = Math.floor(ms / 3600000)
  const mins = Math.floor((ms % 3600000) / 60000)
  return `${hrs}h ${mins}m`
}

export default function Deploys() {
  const [state, setState] = useState<DeployState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [triggering, setTriggering] = useState(false)

  const fetchState = () => {
    fetch('/api/deploys/state')
      .then(r => r.json())
      .then(d => { setState(d); setError(null) })
      .catch(e => setError(String(e)))
  }

  useEffect(() => {
    fetchState()
    const i = setInterval(fetchState, 30000)
    return () => clearInterval(i)
  }, [])

  const triggerDeploy = () => {
    setTriggering(true)
    fetch('/api/deploys/trigger', { method: 'POST' })
      .then(r => r.json())
      .then(() => setTimeout(fetchState, 2000))
      .finally(() => setTriggering(false))
  }

  if (error) return <div className="deploys-page"><div className="dp-error">Error: {error}</div></div>
  if (!state) return <div className="deploys-page">Loading...</div>

  return (
    <div className="deploys-page">
      <div className="dp-header">
        <h2>Deploys</h2>
        <button className="dp-trigger" onClick={triggerDeploy} disabled={triggering}>
          {triggering ? 'Triggering...' : 'Deploy queued now'}
        </button>
      </div>

      <section className="dp-section">
        <h3>Currently deploying</h3>
        {state.in_progress ? (
          <div className="dp-inprogress">
            <span className="dp-brief">Brief {state.in_progress.deploy_brief ?? '—'}</span>
            <span className="dp-sha">{state.in_progress.deploy_short_sha}</span>
            <span className="dp-subject">{state.in_progress.deploy_subject}</span>
            <span className="dp-elapsed">started {timeAgo(state.in_progress.started_at)}</span>
          </div>
        ) : (
          <div className="dp-empty">Idle</div>
        )}
      </section>

      <section className="dp-section">
        <h3>Queue ({state.queued.length} waiting) — auto-deploys in {nextOffHoursWindow()} (next off-hours window)</h3>
        {state.queued.length === 0 ? (
          <div className="dp-empty">Queue empty</div>
        ) : (
          <div className="dp-list">
            {state.queued.map(q => (
              <div key={q.sha} className="dp-row dp-queued">
                <span className="dp-brief">Brief {q.brief ?? '—'}</span>
                <span className="dp-sha">{q.short_sha}</span>
                <span className="dp-subject">{q.subject}</span>
                <span className="dp-time">queued {timeAgo(q.queued_at)}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="dp-section">
        <h3>Recent deploys</h3>
        {state.history.length === 0 ? (
          <div className="dp-empty">No deploys yet</div>
        ) : (
          <div className="dp-list">
            {state.history.map((h, i) => (
              <div key={`${h.sha}-${i}`} className={`dp-row dp-${h.status}`}>
                <span className="dp-brief">Brief {h.brief ?? '—'}</span>
                <span className="dp-sha">{h.short_sha}</span>
                <span className="dp-subject">{h.subject}</span>
                <span className={`dp-status dp-status-${h.status}`}>{h.status}</span>
                <span className="dp-time">{timeAgo(h.deployed_at)} ({h.duration_s}s)</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
```

### Step 11 — Modify `tools/control-panel/src/App.tsx`

Add Deploys to Tab union, TAB_LABELS, and render branch. Import at top.

### Step 12 — Append to `tools/control-panel/src/styles.css`

```css
/* ── Deploys ── */
.deploys-page { padding: 32px; max-width: 1100px; margin: 0 auto; width: 100%; }
.dp-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.dp-header h2 { font-size: 16px; font-weight: 600; }
.dp-trigger {
  background: var(--text); color: white; border: none; padding: 6px 14px;
  border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer;
}
.dp-trigger:disabled { background: var(--text-muted); cursor: not-allowed; }
.dp-error { color: var(--red); font-size: 13px; padding: 16px; background: var(--red-bg); border-radius: 8px; }
.dp-section { margin-bottom: 24px; }
.dp-section h3 {
  font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;
  color: var(--text-secondary); margin-bottom: 10px;
}
.dp-empty { color: var(--text-muted); font-size: 13px; padding: 12px 0; }
.dp-list { display: flex; flex-direction: column; gap: 4px; }
.dp-row {
  display: grid; grid-template-columns: 90px 70px 1fr auto auto;
  gap: 12px; align-items: center;
  padding: 10px 14px; background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; font-size: 12px;
}
.dp-queued { border-left: 3px solid var(--amber); }
.dp-success { border-left: 3px solid var(--green); }
.dp-failed { border-left: 3px solid var(--red); }
.dp-inprogress {
  display: grid; grid-template-columns: 90px 70px 1fr auto;
  gap: 12px; align-items: center;
  padding: 10px 14px; background: var(--blue-bg); border: 1px solid #bfdbfe;
  border-radius: 8px; font-size: 12px;
}
.dp-brief { font-weight: 700; color: var(--text); }
.dp-sha { font-family: 'SF Mono', 'Menlo', monospace; font-size: 11px; color: var(--text-secondary); }
.dp-subject { color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dp-time, .dp-elapsed { color: var(--text-muted); font-size: 11px; white-space: nowrap; }
.dp-status { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.3px; }
.dp-status-success { color: var(--green); }
.dp-status-failed { color: var(--red); }
```

### Step 13 — Update `wtyj/briefs/infra.md`

Update the "Deploy pipeline" section: canary always runs, production gated by off-hours, queue file at `/root/wtyj_deploy_queue.json`, scheduled-deploy workflow drains queue every 30 min, control panel "Deploys" tab visualizes the state.

## Tests

11 tests total:
- 5 in `wtyj/tests/scripts/test_off_hours_check.py` (Curaçao block, off-hours allow, [HOTFIX] in subject bypasses, [HOTFIX] in body does NOT bypass, boundary at 00:00 UTC)
- 6 in `wtyj/tests/shared/test_deploy_queue.py` (extract brief from various, enqueue + brief, idempotent, claim moves all + clears + blocks repeat, mid-deploy enqueue lands in fresh queue, complete writes per-brief history)

Brief 195 had 6 off-hours tests. This brief leaves 5 (drops 1 net). Adds 6 deploy_queue tests. Net change: **+5 tests**.

Regression baseline: **899 passing / 0 failures** (current actual). After this brief: **904 passing / 0 failures (baseline 899 + 5 net).**

## Success Condition

- A push during business hours: test passes, deploy-canary runs + E2E passes + BlueMarlin updated, off-hours-decide outputs `queue`, deploy-production skipped, queue file at `/root/wtyj_deploy_queue.json` contains the new entry with extracted brief number.
- A push during off-hours (or `[HOTFIX]` in subject): full pipeline runs through deploy-production, latest commit deployed to all 3 paying clients, history shows the entry.
- Body-text `[HOTFIX]` no longer bypasses (proven by test 4 in test_off_hours_check.py).
- A push during an in-flight deploy lands in the fresh queue and is NOT swept by complete_deploy (proven by test 5 in test_deploy_queue.py).
- Scheduled-deploy.yml fires every 30 min cron; when off-hours + non-empty queue + no in-flight, deploys latest queued SHA, all acknowledged briefs appear in history with same `deployed_at`.
- Control panel `/api/deploys/state` returns valid JSON. Deploys tab shows in-progress, queue with brief numbers, history. "Deploy queued now" triggers `gh workflow run scheduled-deploy.yml`.
- All 4 containers healthy after a queued deploy fires.

## Rollback

```bash
git revert <this-brief-sha>
git push origin main
```

Reverting restores Brief 195's workflow (canary blocked by off-hours, no queue). Helper scripts and Python module remain on disk but unused. Clean.

If queue file gets corrupted on VPS:
```bash
ssh root@108.61.192.52 'echo "{}" > /root/wtyj_deploy_queue.json'
```
Empty state. Next push starts fresh.

If lock file gets stuck (process killed):
```bash
ssh root@108.61.192.52 'rm -f /root/wtyj_deploy_queue.json.lock'
```
fcntl.flock releases on FD close including process death, so this should never be needed — but if it is, just delete the file.
