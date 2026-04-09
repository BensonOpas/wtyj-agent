# BRIEF 177 — Phase 2 Multi-Client Dashboard Routing + Roberto Container Shell
**Status:** Approved (plan mode) | **Files:** (infra-only, see below) | **Depends on:** Briefs 145–154 (phase 2 backend) | **Blocks:** Roberto real-config brief, owner-ping brief

## Context

Phase 2 multi-client architecture is proven at the BACKEND layer — two containers `wtyj-bluemarlin` (:8001) and `wtyj-adamus` (:8002) run side-by-side, each with its own `platform.env` and `client.json`, each validating its own `DASHBOARD_PASSWORD` at `wtyj/dashboard/api.py:106–113`. But the dashboard FRONTEND is still single-tenant, and the routing layer in between is hardcoded to BlueMarlin. Verified during planning:

- `/etc/nginx/sites-available/api-wetakeyourjob` on the VPS has one `proxy_pass http://127.0.0.1:8001;` — Adamus's backend on :8002 is currently unreachable from outside the VPS.
- `~/Projects/wetakeyourjob-dashboard/artifacts/dashboard/src/lib/api.ts:1` hardcodes `BASE_URL = "https://api.wetakeyourjob.com/dashboard/api"`. No tenant dropdown, no runtime URL switch.
- The Login page has a single password field with no client selector.

Benson wants to set up an Adamus dashboard (password `456`) and a Roberto dashboard (password `789`) right now. Roberto has a psychology practice. He does NOT want Marina to book/pay — he wants her in "filter/buffer" mode: receive WhatsApp, decide, escalate important stuff, stay quiet otherwise. Roberto's real business info is not known yet and must be left blank/NA.

This brief builds the routing shell so both dashboards become reachable, AND creates Roberto's container shell so his dashboard login works against an empty-but-valid backend. It does NOT build the WhatsApp owner-ping feature (deferred to a follow-up brief once Roberto provides his real number).

## Why This Approach

Four options were evaluated during planning:

1. **Path-prefix + tenant dropdown (CHOSEN).** One Replit app, nginx rewrites `/bluemarlin/*` / `/adamus/*` / `/roberto/*` to ports 8001/8002/8003, frontend login page gets a client `<select>` that sets the prefix via localStorage.
2. **Subdomain per client.** `api-adamus.wetakeyourjob.com` etc. Cleaner namespacing but adds DNS + Certbot work per client. Rejected — too much infra per onboarding, and DNS TTL makes rollback slower.
3. **Three separate Replit apps.** Duplicate the dashboard repo three times. Rejected — three codebases to keep in sync, poor maintenance, operator has to bookmark three URLs.
4. **Defer routing entirely.** Just set the passwords, leave nginx alone, neither backend reachable. Rejected — doesn't actually solve Benson's ask.

**Tradeoff carried:** Option 1 couples all clients to ONE Replit app (one failure domain for the frontend). Acceptable because the dashboard is auxiliary tooling — if it goes down, the backends keep processing messages. The alternative (Option 3) trades one failure domain for three, which is worse.

**Owner-ping WhatsApp notification feature is out of scope** — the Explore phase identified it as a single-brief addon that needs `business.owner_whatsapp` + `business.dashboard_url` fields and a notification dispatcher extension. But Roberto doesn't have a real WhatsApp number yet, so shipping it now means shipping code that can't be end-to-end tested against its primary user. Deferred to a follow-up brief.

## Instructions

This brief touches ZERO Python files. All work is VPS-side (direct file edits on the server) plus a frontend repo commit cycle. Deployment is three independently-rollback-able stages.

### Stage 1: Backend containers (VPS)

**Step 1.1 — Update Adamus DASHBOARD_PASSWORD.** SSH to `root@108.61.192.52`. Edit `/root/clients/adamus/config/platform.env` and set `DASHBOARD_PASSWORD=456`. Restart the container:
```bash
cd /root/clients/adamus && docker compose restart
```
Verify the new password is live:
```bash
curl -s -X POST http://localhost:8002/dashboard/api/login \
  -H 'Content-Type: application/json' -d '{"password":"456"}'
```
Expect `{"token":"..."}`.

**Step 1.2 — Create Roberto container shell.** On the VPS:
```bash
mkdir -p /root/clients/roberto/config /root/clients/roberto/data /root/clients/roberto/logs
```

**Step 1.3 — Write `/root/clients/roberto/docker-compose.yml`.** Copy Adamus's compose file (`clients/adamus/docker-compose.yml` in the source repo) verbatim and change exactly two fields: `container_name: wtyj-roberto` and `ports: "8003:8001"`. Leave `image: wtyj-agent` (no tag — Docker defaults to `:latest`), the `env_file`, the `environment` block (`GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/app/config/calendar-key.json`), and the volumes as-is. No `networks:` block exists in Adamus's compose — Docker Compose auto-generates a `roberto_default` network from the compose directory name, no manual edit needed.

**Known dormant risk:** the `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` env var points at a file that won't exist in `/root/clients/roberto/config/`. This is safe because the `gws_calendar` / `sheets_writer` code paths are lazy and only fire under `booking_flow: true`, and Roberto has `booking_flow: false`. Flagged for the follow-up brief that wires Roberto's real config — a stub `calendar-key.json` (or env var removal) will be needed when a real channel is added.

**Step 1.4 — Write `/root/clients/roberto/config/platform.env`:**
```env
ANTHROPIC_API_KEY=<shared Claude key from BlueMarlin's platform.env>
DASHBOARD_PASSWORD=789
EMAIL_ADDRESS=
LATE_API_KEY=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_VERIFY_TOKEN=
ZERNIO_WEBHOOK_SECRET=
```
Empty values for every channel credential. The email poller exits cleanly on empty `EMAIL_ADDRESS` (`email_poller.py:493–498`), and supervisord won't restart it because exit code is 0. No Zernio / WhatsApp / Late creds means no outbound channel — Roberto can't send or receive anything yet, which is the intended shell state.

**Step 1.5 — Write `/root/clients/roberto/config/client.json`:**
```json
{
  "business": {
    "name": "Roberto",
    "email": "",
    "booking_email": "",
    "phone": "NA",
    "whatsapp": "NA",
    "location": "NA",
    "languages": ["English"],
    "operating_days": "NA",
    "support_email": "",
    "spreadsheet_id": ""
  },
  "payment": {
    "timing": "none",
    "methods": [],
    "cancellation_policy": "NA"
  },
  "features": {
    "booking_flow": false
  },
  "terminology": {
    "service_label": "session",
    "party_size_label": "people",
    "slot_label": "appointment"
  },
  "booking_rules": {
    "required_fields": [],
    "hold_duration_hours": 0,
    "group_threshold_requires_human": 0,
    "max_bookings_per_thread": 0
  },
  "services": {},
  "service_aliases": {},
  "faq": {},
  "common_sense_knowledge": {
    "marina_persona": "TBD — Roberto has a psychology practice. Filter/buffer mode only: receive, decide, escalate when needed, stay quiet otherwise. Do NOT attempt to book appointments or discuss pricing."
  }
}
```
Notes on the shape:
- `business.name = "Roberto"` is the only non-blank placeholder. Everything else is `""` or `"NA"` per Benson's "leave empty or NA" directive.
- `business.agent_name` is deliberately OMITTED so `marina_agent.py:454` falls back to `"Marina"` (the agent name interpolation site in `_build_system_prompt` is `f"You are {business.get('agent_name', 'Marina')}, the booking agent for ..."`). Benson renames later.
- `features.booking_flow: false` routes the WhatsApp path to `handle_incoming_dm()` — the flag check is at `webhook_server.py:200`, the `else:` branch spans `webhook_server.py:211–230`, and the DM-agent call is at line 230. Q&A + redirect, no holds, no payment. If a booking intent is detected despite that, `social_agent.py:628-660` still escalates with the full chat log.
- `terminology` uses psychology-friendly defaults ("session" / "appointment") — Benson can overwrite when Roberto clarifies.
- `common_sense_knowledge.marina_persona` is the one directive written: "filter/buffer mode, do not book or discuss pricing." Tells the agent what NOT to do in the absence of real business info.
- `spreadsheet_id: ""` is deliberate. Pre-existing dormant risk: the fallback in `sheets_writer.py:26` is a hardcoded BlueMarlin sheet ID. With `booking_flow: false` and no channels wired, no code path will actually call `sheets_writer` for Roberto. Flagged for the follow-up brief.

**Step 1.6 — Start the container:**
```bash
cd /root/clients/roberto && docker compose up -d
docker compose ps   # expect wtyj-roberto up
curl -s http://localhost:8003/health   # expect {"status":"ok"}
curl -s -X POST http://localhost:8003/dashboard/api/login \
  -H 'Content-Type: application/json' -d '{"password":"789"}'
```
Expect `{"token":"..."}`.

**Stage 1 acceptance:** All three containers (`wtyj-bluemarlin`, `wtyj-adamus`, `wtyj-roberto`) healthy on their respective ports. Adamus accepts password `456`. Roberto accepts password `789`. BlueMarlin unaffected.

### Stage 2: nginx path-prefix routing (VPS)

**Step 2.1 — Edit `/etc/nginx/sites-available/api-wetakeyourjob`.** The current file has one `server { server_name api.wetakeyourjob.com; ... }` block containing a single `location / { proxy_pass http://127.0.0.1:8001; ... }`. Add three new `location` blocks BEFORE the root location:

```nginx
# Phase 2 multi-client routing (Brief 177). Each prefix strips and forwards
# to the client's container. The root /dashboard/api/ path stays on BlueMarlin
# so the old frontend build keeps working during rollout.

location /bluemarlin/ {
    proxy_pass http://127.0.0.1:8001/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
location /adamus/ {
    proxy_pass http://127.0.0.1:8002/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
location /roberto/ {
    proxy_pass http://127.0.0.1:8003/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

**Critical:** the trailing slash on `proxy_pass http://127.0.0.1:8002/;` is load-bearing. nginx strips the matched `/adamus/` prefix when the proxy_pass URL has a trailing slash, so `/adamus/dashboard/api/login` becomes `/dashboard/api/login` on the backend. Without the trailing slash, nginx forwards the full path and the backend sees `/adamus/dashboard/api/login` which doesn't match any route.

**Step 2.2 — Syntax check and reload.**
```bash
nginx -t
```
If the syntax check fails, DO NOT reload — fix the config and retry. On success:
```bash
systemctl reload nginx
```

**Step 2.3 — External verification.**
```bash
curl -s https://api.wetakeyourjob.com/bluemarlin/health   # expect {"status":"ok"}
curl -s https://api.wetakeyourjob.com/adamus/health       # expect {"status":"ok"}
curl -s https://api.wetakeyourjob.com/roberto/health      # expect {"status":"ok"}
# Backward compat — existing frontend build still works:
curl -s https://api.wetakeyourjob.com/health              # expect {"status":"ok"} (BlueMarlin)
```

**Stage 2 acceptance:** All four curls return `{"status":"ok"}`. The backward-compat root path still routes to BlueMarlin so the existing deployed frontend keeps working until Stage 3 ships.

### Stage 3: Frontend dropdown (dashboard repo)

**Separate repo:** `~/Projects/wetakeyourjob-dashboard/`. Not part of the bluemarlin-agent /brief workflow — commit and deploy via Replit's normal cycle.

**Step 3.1 — `artifacts/dashboard/src/lib/api.ts`:** Replace the hardcoded `BASE_URL` constant with a localStorage-driven getter. Read the file first to see the current shape, then replace:

```typescript
// New exports:
const VALID_CLIENTS = ["bluemarlin", "adamus", "roberto"] as const;
export type Client = typeof VALID_CLIENTS[number];

export function getClient(): Client {
  const stored = localStorage.getItem("wtyj_client");
  return VALID_CLIENTS.includes(stored as Client) ? (stored as Client) : "bluemarlin";
}

export function setClient(client: Client): void {
  localStorage.setItem("wtyj_client", client);
}

function getBaseUrl(): string {
  return `https://api.wetakeyourjob.com/${getClient()}/dashboard/api`;
}
```
Every existing fetch() call site in `api.ts` that uses `BASE_URL` must be updated to call `getBaseUrl()` instead.

**Step 3.2 — `artifacts/dashboard/src/pages/Login.tsx`:** Add a `<select>` element above the password input:
```tsx
<select
  value={selectedClient}
  onChange={(e) => {
    setSelectedClient(e.target.value as Client);
    setClient(e.target.value as Client);
  }}
>
  <option value="bluemarlin">BlueMarlin Charters</option>
  <option value="adamus">Restaurant Adamus</option>
  <option value="roberto">Roberto</option>
</select>
```
On mount, initialize `selectedClient` from `getClient()` so the dropdown remembers the last choice. Call `setClient(selectedClient)` before `login.mutate()` so the password check hits the right backend.

**Step 3.3 — `artifacts/dashboard/src/components/auth/AuthProvider.tsx`:** Namespace the token storage key by client. Current code uses a hardcoded `bluemarlin_token` key — rename to `wtyj_token_${client}` so each client has its own slot. On logout, clear BOTH `wtyj_token_${currentClient}` and `wtyj_client` so the dropdown resets to default on next login.

**Step 3.4 — Commit, push, Replit auto-deploys.**

**Stage 3 acceptance (manual, in browser):**
1. Open `https://bluemarlindashboard.replit.app/`. Dropdown visible with three options.
2. Select BlueMarlin + existing password → logged in, existing conversations/escalations visible.
3. Logout, select Adamus + `456` → logged in, Adamus view.
4. Logout, select Roberto + `789` → logged in, empty Roberto view.
5. BlueMarlin's existing workflows (Messages, Escalations, Content Pipeline) still work as before.

**Expected operational side effect:** Any user who was logged in to the dashboard before the Stage 3 deploy will be silently logged out on their next page load — the token storage key rename from `bluemarlin_token` to `wtyj_token_${client}` means the old token is no longer found. Users must re-authenticate via the new dropdown. This is expected; not a bug.

## Tests

No backend source code is changing, so there are no new unit tests. The brief's real behavior is verified by the three stage acceptance checks above.

**Backend regression (sanity check):**
```bash
python3 -m pytest wtyj/tests/ -q --tb=line
```
Must stay at **833 passing / 0 failures** (same as Brief 176 baseline). Any regression means something environmental shifted — investigate before proceeding to deploy stages.

## Success Condition

All three clients (BlueMarlin, Adamus, Roberto) are reachable from `bluemarlindashboard.replit.app` via the tenant dropdown, each authenticating against their own `DASHBOARD_PASSWORD`, with BlueMarlin's existing workflows unaffected.

## Rollback

Per stage, from latest to earliest:

- **Stage 3 rollback:** Revert the frontend commit in `~/Projects/wetakeyourjob-dashboard/`, Replit redeploys the previous build. Because Stage 2 left the backward-compat `/dashboard/api/*` route alive on nginx, the old frontend build keeps working against BlueMarlin during the rollback window.
- **Stage 2 rollback:** Remove the three new `location` blocks from `/etc/nginx/sites-available/api-wetakeyourjob`, `nginx -t && systemctl reload nginx`. Existing BlueMarlin root route untouched, zero downtime.
- **Stage 1 rollback:** `cd /root/clients/roberto && docker compose down && cd .. && rm -rf roberto`. Revert `/root/clients/adamus/config/platform.env` `DASHBOARD_PASSWORD` to its previous value and `docker compose restart`. BlueMarlin unaffected at every step.

Full rollback leaves the system in exactly its pre-Brief-177 state.
