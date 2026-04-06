# BRIEF 146 — Adamus Second-Client Deployment (Orchestrator-Only)

**Status:** Draft
**Files:** `bluemarlin/agents/marina/email_poller.py`, `supervisord.conf`, `clients/adamus/config/client.json` (new), `clients/adamus/config/platform.env.example` (new), `clients/adamus/docker-compose.yml` (new), `bluemarlin/tests/marina/test_146_adamus_second_client.py` (new)
**Depends on:** Brief 145 (parameterized email poller + generic config file names)
**Blocks:** Future real-email migration for Adamus (Mailgun or OAuth bootstrap)

---

## Context

Phase 2 claims the system can serve multiple clients from one Docker image with nothing but a new `client.json` + `platform.env`. Never tested. BlueFinn is still the only client that has run. This brief deploys Restaurant Adamus — a beach club in Curaçao, agent name Sofia, restaurant terminology, zero overlap with charter vocabulary — as a second container on the same VPS on port 8002, reading the same Docker image as BlueFinn.

We are deliberately running Adamus **without email** for this first test. Email is one channel out of many and setting up a new Microsoft OAuth refresh token for sophia@wetakeyourjob.com is a time sink that tells us nothing about whether multi-client architecture works. What proves it works is: send the same message into BlueFinn's and Adamus's orchestrators and get two completely different responses grounded in two completely different `client.json` files — Marina replies in charter vocabulary, Sofia replies in restaurant vocabulary.

The blocker is that when Adamus starts without an `EMAIL_ADDRESS` and without an `azure_refresh_token.txt`, the `email-poller` process under supervisord crashes on startup, supervisord retries it to the `startretries` limit, and the container logs fill with noise. This brief adds a graceful exit path: if `EMAIL_ADDRESS` is empty OR the refresh token file is missing, `email_poller.main()` logs the reason and returns `0`. Supervisord is reconfigured to not restart a process that exited cleanly. BlueFinn is unaffected because its `EMAIL_ADDRESS` and token file are both present.

---

## Why This Approach

**Alternative considered: skip the code change, let email_poller crash on Adamus.** Rejected. Even though `startretries=3` limits the restart loop, supervisord marks the process FATAL and writes stack traces to the log every container start. It also confuses humans reading logs trying to debug something else. The graceful-exit path is ~5 lines and backwards compatible.

**Alternative considered: remove email-poller from supervisord.conf for Adamus.** Rejected. Would require two different supervisord configs, two different Docker images, or a supervisord template that's rendered at container start. All worse than a 5-line Python check.

**Alternative considered: actually do the OAuth flow for sophia@ and deploy with email.** Rejected. The Azure refresh-token bootstrap is manual (browser + device code flow or redirect-URI flow) and is not testable in pytest. It blocks the real goal. Email will be fixed later when we do Mailgun.

**Alternative considered: put Adamus config inside `bluemarlin/clients/adamus/` (under the existing tree).** Rejected. The `bluemarlin/` subdirectory is the source tree — it's `COPY`-ed into the Docker image. Putting `clients/adamus/` at the repo root keeps the source image pure and makes `clients/` a dedicated mount-point namespace for per-client deployments.

**Tradeoff accepted:** Adamus's Google Calendar and Google Sheets service-account-key file (`calendar-key.json`) is reused from BlueFinn — both containers mount the same physical file from `/root/bluemarlin/config/calendar-key.json`. That's technically a shared credential across businesses. For the demo this is fine (same owner, same GCP project); for real multi-tenant it needs to become per-client. Noted in roadmap under "Rename Google Cloud project to agnostic name."

---

## Source Material

### Current `email_poller.py` lines 26-34 and 503-506

```python
# ========= CONFIG =========
CLIENT_ID = os.environ.get("AZURE_CLIENT_ID", "28e94343-2f77-444c-ac32-58b7bed33b65")
TENANT_ID = os.environ.get("AZURE_TENANT_ID", "caac06b5-1420-4223-9dcc-ba4a670ec26a")
EMAIL_ADDR = os.environ.get("EMAIL_ADDRESS", "hello@wetakeyourjob.com")

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_DIR = os.path.normpath(os.path.join(_MODULE_DIR, "..", "..", "config"))
REFRESH_TOKEN_PATH = os.path.join(_CONFIG_DIR, "azure_refresh_token.txt")
```

```python
# ========= MAIN LOOP =========
def main():
    log("Email poller started. UNSEEN-based AUTO-REPLY mode (marina_agent unified call).")
```

### Current `supervisord.conf` `[program:email-poller]` block

```ini
[program:email-poller]
command=python3 -m agents.marina.email_poller
directory=/app
autostart=true
autorestart=true
startsecs=5
startretries=3
redirect_stderr=true
stdout_logfile=/app/logs/email_poller.log
stdout_logfile_maxbytes=10MB
```

### Adamus Google Calendar IDs (confirmed in conversation 2026-04-06)

- Lunch: `c3058824908775658a72e60877f8cea295b54b2b0d5c1c5a33c295e0ec2f8094@group.calendar.google.com`
- Dinner: `5b51d6514c5576577fd39e8cb385c0fbcbfc285d283b8ca27095d322b9af50a1@group.calendar.google.com`

### Adamus Google Sheet ID

`1OYtPI5Fn7btaPROsJgtpXnoWR025cbjHWudHx2a8ggc`

### Adamus agent configuration decisions

- Agent name: **Sofia** (not Marina)
- Business: Restaurant Adamus, beach club on Jan Thiel Beach, Curaçao
- Services: lunch and dinner
- Languages: English, Dutch, Spanish, Papiamentu
- Terminology: `reservation` / `diners` / `seating`
- Payment timing: `none` (pay at venue)
- Group threshold for escalation: 12 diners
- Support email (demo): `butlerbensonagent@gmail.com`
- Customer-facing email: `sophia@wetakeyourjob.com` (not wired up this brief)

### Supervisord behavior reference

From supervisord docs:
- `autorestart=unexpected` means "restart only if exit code is NOT in `exitcodes`." With `exitcodes=0`, clean exits are respected and crashes still trigger restart.
- **Critical:** `startsecs` is the interval a process must stay alive before supervisord transitions it from `STARTING` to `RUNNING`. If a process exits faster than `startsecs` it is treated as a startup failure and goes to `BACKOFF`, ignoring `exitcodes`. For Adamus the email-poller will exit in milliseconds via the guard clause, well under the default 5 seconds. So we **must set `startsecs=0`** for the email-poller program specifically, so the immediate clean exit is treated as a normal exit and not a startup failure.

BlueFinn is unaffected: its poller never exits the `while True:` loop, so `startsecs=0` makes no practical difference to BlueFinn's behavior.

### VPS deployment directory layout

```
/root/
├── docker-compose.yml           (BlueFinn — existing, port 8001)
├── Dockerfile                   (existing)
├── supervisord.conf             (existing, MODIFIED in this brief)
├── bluemarlin/
│   ├── agents/                  (source)
│   ├── shared/
│   └── config/
│       ├── client.json          (BlueFinn)
│       ├── platform.env         (BlueFinn)
│       ├── calendar-key.json    (BlueFinn — shared with Adamus this brief)
│       └── azure_refresh_token.txt
└── clients/
    └── adamus/                  (NEW — git-pulled from repo)
        ├── docker-compose.yml   (NEW — checked into git)
        ├── config/
        │   ├── client.json      (NEW — checked into git)
        │   ├── platform.env.example (NEW — checked into git)
        │   ├── platform.env     (created manually on VPS, gitignored)
        │   └── calendar-key.json (copied from BlueFinn config on VPS, gitignored)
        ├── data/                (empty, created at deploy time, gitignored)
        └── logs/                (empty, created at deploy time, gitignored)
```

---

## Instructions

### Step 1 — Graceful exit in `email_poller.py`

In `bluemarlin/agents/marina/email_poller.py`, locate the `main()` function (around line 503). Replace:

```python
# ========= MAIN LOOP =========
def main():
    log("Email poller started. UNSEEN-based AUTO-REPLY mode (marina_agent unified call).")
```

with:

```python
# ========= MAIN LOOP =========
def main():
    # Email-disabled path for clients that don't use email.
    # Exit 0 cleanly; supervisord is configured not to restart on clean exits.
    if not EMAIL_ADDR or not os.path.exists(REFRESH_TOKEN_PATH):
        log(f"Email polling disabled for this client "
            f"(EMAIL_ADDRESS={'set' if EMAIL_ADDR else 'empty'}, "
            f"refresh_token={'present' if os.path.exists(REFRESH_TOKEN_PATH) else 'missing'}). "
            f"Exiting cleanly.")
        return
    log("Email poller started. UNSEEN-based AUTO-REPLY mode (marina_agent unified call).")
```

Rest of `main()` is unchanged. Backwards compatible — BlueFinn has both `EMAIL_ADDRESS` set and `azure_refresh_token.txt` present, so the guard is false and the poller runs normally.

### Step 2 — Supervisord config

In `supervisord.conf`, update the `[program:email-poller]` block. Replace:

```ini
[program:email-poller]
command=python3 -m agents.marina.email_poller
directory=/app
autostart=true
autorestart=true
startsecs=5
startretries=3
```

with:

```ini
[program:email-poller]
command=python3 -m agents.marina.email_poller
directory=/app
autostart=true
autorestart=unexpected
exitcodes=0
startsecs=0
startretries=3
```

Note two changes from the original: `autorestart=true` → `autorestart=unexpected` AND `startsecs=5` → `startsecs=0`. Without `startsecs=0`, supervisord treats Adamus's millisecond-fast clean exit as a startup failure and marks it FATAL anyway, defeating the whole graceful-exit path.

Leave the rest of the block (`redirect_stderr`, `stdout_logfile`, `stdout_logfile_maxbytes`) unchanged. Leave `[program:webhook-server]` unchanged (its `startsecs=5` is correct — the webhook server stays up).

### Step 3 — Create `clients/adamus/config/client.json`

Create the file at repo path `clients/adamus/config/client.json` with this exact content:

```json
{
  "business": {
    "name": "Restaurant Adamus",
    "email": "sophia@wetakeyourjob.com",
    "booking_email": "sophia@wetakeyourjob.com",
    "phone": "+599 9 XXX XXXX",
    "whatsapp": "+599 9 XXX XXXX",
    "location": "Jan Thiel Beach, Curaçao",
    "languages": ["English", "Dutch", "Spanish", "Papiamentu"],
    "operating_days": "Wednesday to Sunday",
    "agent_name": "Sofia",
    "agent_signature": "Sofia\nRestaurant Adamus",
    "spreadsheet_id": "1OYtPI5Fn7btaPROsJgtpXnoWR025cbjHWudHx2a8ggc",
    "support_email": "butlerbensonagent@gmail.com"
  },
  "payment": {
    "timing": "none",
    "methods": ["Cash", "Credit card", "Debit card"],
    "cancellation_policy": "Please cancel at least 2 hours before your reservation.",
    "hold_duration_hours": 4
  },
  "features": {
    "booking_flow": true
  },
  "terminology": {
    "service_label": "reservation",
    "party_size_label": "diners",
    "slot_label": "seating"
  },
  "booking_rules": {
    "required_fields": ["service_name", "date", "guests"],
    "group_threshold_requires_human": 12,
    "max_bookings_per_thread": 2
  },
  "services": {
    "lunch": {
      "display_name": "Lunch",
      "description": "Beachfront lunch with Caribbean fusion menu",
      "price": 0,
      "capacity": 40,
      "days_available": "Wed, Thu, Fri, Sat, Sun",
      "duration_hours": 2,
      "included": ["Complimentary water", "Bread basket"],
      "slots": [
        {
          "time": "12:00",
          "resource": "Main Terrace",
          "location": "Jan Thiel Beach",
          "calendar_id": "c3058824908775658a72e60877f8cea295b54b2b0d5c1c5a33c295e0ec2f8094@group.calendar.google.com"
        },
        {
          "time": "13:30",
          "resource": "Main Terrace",
          "location": "Jan Thiel Beach",
          "calendar_id": "c3058824908775658a72e60877f8cea295b54b2b0d5c1c5a33c295e0ec2f8094@group.calendar.google.com"
        }
      ]
    },
    "dinner": {
      "display_name": "Dinner",
      "description": "Evening dining with ocean view, cocktails, and fresh seafood",
      "price": 0,
      "capacity": 60,
      "days_available": "Wed, Thu, Fri, Sat, Sun",
      "duration_hours": 2.5,
      "included": ["Amuse-bouche", "Live music on Fridays"],
      "slots": [
        {
          "time": "18:00",
          "resource": "Beach Deck",
          "location": "Jan Thiel Beach",
          "calendar_id": "5b51d6514c5576577fd39e8cb385c0fbcbfc285d283b8ca27095d322b9af50a1@group.calendar.google.com"
        },
        {
          "time": "20:00",
          "resource": "Beach Deck",
          "location": "Jan Thiel Beach",
          "calendar_id": "5b51d6514c5576577fd39e8cb385c0fbcbfc285d283b8ca27095d322b9af50a1@group.calendar.google.com"
        }
      ]
    }
  },
  "service_aliases": {
    "lunch": ["middag", "almuerzo", "eten"],
    "dinner": ["diner", "cena", "avondeten", "sena"]
  },
  "faq": {
    "dress_code": "Smart casual. No swimwear at dinner.",
    "parking": "Free parking at Jan Thiel Beach lot, 2-minute walk.",
    "kids": "Children are welcome. We have a kids menu available.",
    "vegetarian": "We offer vegetarian and vegan options. Let us know about allergies when booking.",
    "private_events": "We host private events for groups of 20+. Contact us for details.",
    "music": "Live music every Friday evening from 19:00.",
    "drinks": "Full bar with cocktails, wine, and local beers. Happy hour 17:00-18:00 Wed-Sat."
  },
  "common_sense_knowledge": {
    "marina_persona": "Warm, casual, beachy. You work at a chill beach restaurant on Jan Thiel Beach. Keep it relaxed and welcoming. Your name is Sofia. Your business is Restaurant Adamus. You handle reservations for lunch and dinner seatings only — nothing else."
  }
}
```

NB: The key is `marina_persona` (not `sofia_persona`) because the prompt-building code in `marina_agent.py` reads that specific key — leave the key name alone. The persona text itself establishes Sofia positively; do not mention Marina, charters, boats, trips, or BlueFinn by name. The forbidden-vocabulary test (test 11) will fail if any of those strings appear.

### Step 4 — Create `clients/adamus/config/platform.env.example`

Create the file at repo path `clients/adamus/config/platform.env.example` with this exact content:

```bash
# Adamus platform.env — fill in secrets on the VPS, NOT here.
# This file is the template. Real values go in /root/clients/adamus/config/platform.env on the VPS.

# Anthropic (shared across all clients)
ANTHROPIC_API_KEY=

# Dashboard
DASHBOARD_PASSWORD=adamus-demo-2026

# Email (disabled for this test — orchestrator-only)
# Leave EMAIL_ADDRESS empty to skip email polling.
EMAIL_ADDRESS=
AZURE_CLIENT_ID=28e94343-2f77-444c-ac32-58b7bed33b65
AZURE_TENANT_ID=caac06b5-1420-4223-9dcc-ba4a670ec26a

# Google service account key path inside the container
GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/app/config/calendar-key.json

# WhatsApp (disabled for this test)
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_VERIFY_TOKEN=

# Zernio (disabled for this test)
LATE_API_KEY=
ZERNIO_WEBHOOK_SECRET=

# Meta app (not used for Adamus)
META_APP_ID=
META_APP_SECRET=
```

### Step 5 — Create `clients/adamus/docker-compose.yml`

Create the file at repo path `clients/adamus/docker-compose.yml` with this exact content:

```yaml
services:
  bluemarlin:
    image: root-bluemarlin
    container_name: bluemarlin-adamus
    restart: unless-stopped
    ports:
      - "8002:8001"
    env_file:
      - ./config/platform.env
    environment:
      - GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/app/config/calendar-key.json
    volumes:
      - ./config/client.json:/app/config/client.json:ro
      - ./config/calendar-key.json:/app/config/calendar-key.json:ro
      - ./data:/app/data
      - ./logs:/app/logs
```

Note: No mount for `azure_refresh_token.txt` because Adamus doesn't have one. No `build:` directive — uses the pre-built `root-bluemarlin` image that BlueFinn's docker-compose produces.

### Step 6 — Write the tests

Create `bluemarlin/tests/marina/test_146_adamus_second_client.py`. Tests should cover:

1. `test_email_poller_exits_cleanly_when_email_address_empty` — use `monkeypatch.setattr` to set `email_poller.EMAIL_ADDR` to `""`, call `email_poller.main()`, assert it returns `None` without raising. Use `pytest`'s `caplog` fixture to verify the "disabled" log message is present.
2. `test_email_poller_exits_cleanly_when_refresh_token_missing` — use `monkeypatch.setattr` to set `email_poller.EMAIL_ADDR` to `"test@example.com"` and `email_poller.REFRESH_TOKEN_PATH` to a `tmp_path / "nonexistent.txt"`. Call `main()`, assert it returns without raising.
3. `test_email_poller_proceeds_past_guard_when_both_present` — set `email_poller.EMAIL_ADDR` to `"test@example.com"`, create `tmp_path / "token.txt"` with arbitrary contents and point `email_poller.REFRESH_TOKEN_PATH` at it, **also monkeypatch `email_poller.THREAD_STATE_PATH` to a path under `tmp_path`** (so `load_json` does not touch the dev checkout's `bluemarlin/config/email_thread_state.json`), then monkeypatch `email_poller.imap_connect` to raise a sentinel exception. Use `pytest.raises(SentinelException)` around the `main()` call and assert the sentinel fires — proves the guard was passed. **Do not let this test mutate any file under `bluemarlin/config/`.**
4. `test_adamus_client_json_is_valid_json` — load `clients/adamus/config/client.json`, assert it parses.
5. `test_adamus_client_json_has_sofia_agent` — assert `business.agent_name == "Sofia"` and `business.agent_signature` starts with "Sofia".
6. `test_adamus_client_json_uses_restaurant_terminology` — assert `terminology.service_label == "reservation"`, `party_size_label == "diners"`, `slot_label == "seating"`.
7. `test_adamus_client_json_has_real_calendar_ids` — assert the lunch calendar ID starts with `c3058824908775` and the dinner calendar ID starts with `5b51d6514c5576`. Guards against placeholder drift.
8. `test_adamus_client_json_has_real_spreadsheet_id` — assert `business.spreadsheet_id == "1OYtPI5Fn7btaPROsJgtpXnoWR025cbjHWudHx2a8ggc"`.
9. `test_adamus_payment_timing_is_none` — restaurant should not trigger payment-link logic.
10. `test_adamus_group_threshold_is_12` — `booking_rules.group_threshold_requires_human == 12`.
11. `test_adamus_client_json_no_bluefinn_references` — load as text, assert the strings `BlueFinn`, `bluefinn`, `charter`, `trip`, `boat`, `Marina` do not appear anywhere in the file. (Case-sensitive for `Marina` to allow `marina_persona` as a key.) Actually: allow the substring `marina_persona` as the one permitted occurrence of `marina`.
12. `test_adamus_docker_compose_uses_prebuilt_image` — load `clients/adamus/docker-compose.yml`, assert `image: root-bluemarlin` and not `build:`.
13. `test_adamus_docker_compose_port_8002` — assert the port mapping contains `"8002:8001"`.

Tests must import `email_poller` module and use monkeypatching. Use `importlib.reload` if needed to defeat module-level caching. Use `pytest` fixtures for tempdir/token-file setup.

### Step 7 — Run tests locally

```bash
cd /Users/benson/Projects/bluemarlin-agent/bluemarlin
python3 -m pytest tests/marina/test_146_adamus_second_client.py -v
```

All new tests must pass. Then run full regression:

```bash
python3 -m pytest tests/ -q --tb=no
```

Expected: 643+13 = 656 tests passing (minus the 6 pre-existing failures that are known stale). No new failures.

### Step 8 — Update `.gitignore` for Adamus runtime directories

The `.gitignore` (as of the earlier git cleanup) already has:

- `**/platform.env`, `**/calendar-key.json`, `**/azure_refresh_token.txt` (broad catch-all, lines 41-44)
- `clients/*/config/platform.env`, `clients/*/config/calendar-key.json`, `clients/*/config/azure_refresh_token.txt` (explicit client-config patterns, lines 48-50)

**Only the runtime directories `data/` and `logs/` are missing.** Append exactly these two lines to `.gitignore`, at the end of the "Client-specific config trees" block:

```
clients/*/data/
clients/*/logs/
```

Do NOT add other patterns — they already exist. Verify before committing:

```bash
grep -nE "clients/\*/" .gitignore
```

Expected: shows the 3 existing `clients/*/config/...` lines plus the 2 new `clients/*/data/` and `clients/*/logs/` lines.

`clients/adamus/config/client.json` and `clients/adamus/docker-compose.yml` are NOT gitignored — they are checked in.

### Step 9 — Commit and push

```bash
git add -A
git commit -m "Brief 146 — Adamus second-client deployment (orchestrator-only)"
git push
```

### Step 10 — Deploy BlueFinn rebuild (picks up email_poller + supervisord changes)

```bash
ssh root@108.61.192.52 "cd /root && git pull && docker compose down && docker compose build && docker compose up -d"
ssh root@108.61.192.52 "sleep 8 && docker compose ps && curl -s http://localhost:8001/health"
```

Expected: container `bluemarlin-default` running on 8001, `{"status":"ok"}`. Email poller runs normally because BlueFinn has both `EMAIL_ADDRESS` and `azure_refresh_token.txt`.

Verify email poller did NOT exit (it should be running):

```bash
ssh root@108.61.192.52 "docker compose exec bluemarlin supervisorctl status"
```

Expected: both `email-poller` and `webhook-server` in `RUNNING` state.

### Step 11 — Set up Adamus runtime directories and config on VPS

Prerequisite: Step 10 already ran `git pull` on the VPS, which created `/root/clients/adamus/` and `/root/clients/adamus/config/client.json`, `.../docker-compose.yml`, and `.../config/platform.env.example` via git. Verify this before proceeding:

```bash
ssh root@108.61.192.52 "ls -la /root/clients/adamus/ /root/clients/adamus/config/"
```

Expected: both directories exist, `config/` contains `client.json` and `platform.env.example`. If `config/` is missing entirely, the git pull didn't populate `clients/` — debug that before continuing (check for `.gitignore` misconfiguration on `clients/adamus/config/client.json`).

Now create runtime dirs and populate the non-git files:

```bash
ssh root@108.61.192.52 "
mkdir -p /root/clients/adamus/data /root/clients/adamus/logs
cp /root/bluemarlin/config/calendar-key.json /root/clients/adamus/config/calendar-key.json
cp /root/clients/adamus/config/platform.env.example /root/clients/adamus/config/platform.env
ls -la /root/clients/adamus/config/
"
```

Then edit `/root/clients/adamus/config/platform.env` on the VPS to set the real `ANTHROPIC_API_KEY`. The value is the same as BlueFinn's — look it up and copy it:

```bash
ssh root@108.61.192.52 "
grep ANTHROPIC_API_KEY /root/bluemarlin/config/platform.env
"
```

Take the value, paste it into Adamus's platform.env (replacing the empty `ANTHROPIC_API_KEY=` line). Easiest way:

```bash
ssh root@108.61.192.52 "
ANTHROPIC_KEY=\$(grep '^ANTHROPIC_API_KEY=' /root/bluemarlin/config/platform.env | cut -d= -f2-)
sed -i \"s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=\$ANTHROPIC_KEY|\" /root/clients/adamus/config/platform.env
echo 'Adamus platform.env updated:'
grep -v '^$\|^#' /root/clients/adamus/config/platform.env | grep -E 'ANTHROPIC|EMAIL_ADDRESS|DASHBOARD'
"
```

Expected output: `ANTHROPIC_API_KEY=sk-ant-api03-...`, `EMAIL_ADDRESS=` (empty), `DASHBOARD_PASSWORD=adamus-demo-2026`.

### Step 12 — Verify Docker image name, then start Adamus container

**Pre-check:** Adamus's docker-compose uses `image: root-bluemarlin` which assumes the BlueFinn build tagged the image with that exact name. This naming depends on the project directory name (`/root`) and the service name (`bluemarlin`). Verify it exists before starting:

```bash
ssh root@108.61.192.52 "docker images --format '{{.Repository}}:{{.Tag}}' | grep -i bluemarlin"
```

Expected: a line containing `root-bluemarlin:latest` (or similar). If the actual image is tagged differently (for example `bluemarlin:latest` or `bluemarlin-default`), you MUST update `clients/adamus/docker-compose.yml` on both the Mac and the VPS to use the real image name, re-commit, and re-pull on the VPS before proceeding. Do not guess.

Once verified:

```bash
ssh root@108.61.192.52 "cd /root/clients/adamus && docker compose up -d"
ssh root@108.61.192.52 "sleep 8 && docker compose -f /root/clients/adamus/docker-compose.yml ps && curl -s http://localhost:8002/health"
```

Expected: `bluemarlin-adamus` container running on port 8002, `{"status":"ok"}`.

Verify email-poller exited cleanly (not crashed) inside Adamus container:

```bash
ssh root@108.61.192.52 "docker compose -f /root/clients/adamus/docker-compose.yml exec bluemarlin supervisorctl status"
```

Expected: `email-poller` in `EXITED` state (exit code 0), `webhook-server` in `RUNNING` state.

Check the email-poller log for the disabled message:

```bash
ssh root@108.61.192.52 "docker compose -f /root/clients/adamus/docker-compose.yml exec bluemarlin cat /app/logs/email_poller.log"
```

Expected: contains "Email polling disabled for this client".

### Step 13 — Orchestrator proof: Sofia speaks restaurant

Send a test booking message into Adamus's webhook server directly. The goal is to prove the same code path returns different content when given Adamus's config vs BlueFinn's.

```bash
ssh root@108.61.192.52 "docker compose -f /root/clients/adamus/docker-compose.yml exec bluemarlin python3 -c '
import sys
sys.path.insert(0, \"/app\")
from shared import config_loader
b = config_loader.get_business()
t = config_loader.get_raw().get(\"terminology\", {})
print(\"name:\", b.get(\"name\"))
print(\"agent_name:\", b.get(\"agent_name\"))
print(\"service_label:\", t.get(\"service_label\"))
print(\"party_size_label:\", t.get(\"party_size_label\"))
services = list(config_loader.get_services().keys())
print(\"services:\", services)
'"
```

Expected output:
```
name: Restaurant Adamus
agent_name: Sofia
service_label: reservation
party_size_label: diners
services: ['lunch', 'dinner']
```

Then cross-check BlueFinn container still shows charter vocabulary:

```bash
ssh root@108.61.192.52 "docker compose exec bluemarlin python3 -c '
import sys
sys.path.insert(0, \"/app\")
from shared import config_loader
b = config_loader.get_business()
t = config_loader.get_raw().get(\"terminology\", {})
print(\"name:\", b.get(\"name\"))
print(\"agent_name:\", b.get(\"agent_name\"))
print(\"service_label:\", t.get(\"service_label\"))
'"
```

Expected output:
```
name: BlueFinn Charters Curaçao
agent_name: Marina
service_label: trip
```

If both outputs come out as expected: the multi-client architecture is proven. Two containers, same image, different client.json, different agent names, different terminology — no cross-contamination.

### Step 14 — Final regression on BlueFinn

```bash
ssh root@108.61.192.52 "curl -s http://localhost:8001/health && echo && curl -s http://localhost:8002/health"
```

Both must return `{"status":"ok"}`.

```bash
ssh root@108.61.192.52 "docker compose ps && echo && docker compose -f /root/clients/adamus/docker-compose.yml ps"
```

Both containers must be in `Up` state.

---

## Tests

Implemented as `bluemarlin/tests/marina/test_146_adamus_second_client.py`. See Step 6 for the 13-test list. Tests must:

- Assert specific literal values where possible (calendar ID prefixes, spreadsheet ID, port numbers, terminology strings).
- Exercise the real `email_poller.main()` function with environment manipulation — not mock it out.
- Load real files from `clients/adamus/config/` — not recreate fixtures.
- Guard against BlueFinn vocabulary leaking into Adamus config (test 11).

Total: 13 new tests. Existing 643 tests must still pass (minus 6 pre-existing unrelated failures).

---

## Success Condition

Two Docker containers running simultaneously on the same VPS — `bluemarlin-default` on port 8001 returning "Marina / trip / BlueFinn Charters" for `config_loader.get_business()`, and `bluemarlin-adamus` on port 8002 returning "Sofia / reservation / Restaurant Adamus" — with Adamus's email-poller cleanly exited (not crashed) and BlueFinn's email-poller still running. Both `/health` endpoints return `{"status":"ok"}`. All 13 new pytest tests pass.

---

## Rollback

**If the code change breaks BlueFinn's email poller:**
```bash
ssh root@108.61.192.52 "cd /root && git revert HEAD && docker compose down && docker compose build && docker compose up -d"
```

**If Adamus container won't start or crashes:**
```bash
ssh root@108.61.192.52 "cd /root/clients/adamus && docker compose down"
```
BlueFinn is untouched. Debug Adamus without affecting production.

**Full abort (remove Adamus entirely):**
```bash
ssh root@108.61.192.52 "cd /root/clients/adamus && docker compose down && rm -rf /root/clients/adamus"
```
Revert the git commit for the three config files. BlueFinn remains on the email-poller-change build or gets reverted separately.

**If tests fail locally before deployment:**
Don't touch the VPS. Fix the code, re-run tests. Nothing deploys until all tests green.
