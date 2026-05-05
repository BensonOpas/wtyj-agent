# OUTPUT 200 — api.unboks.org cutover (Layer 1 of wtyj→unboks rebrand)

## What was done
Phase A of the brief executed cleanly. New nginx server block at `/etc/nginx/sites-available/api-unboks` on the VPS (separate file from `api-wetakeyourjob` for clean rollback isolation), enabled via symlink, validated with `nginx -t`, reloaded into the running daemon. The block routes `api.unboks.org/api/{tenant}/...` requests to the right backend container by stripping both the `/api/` and `/{tenant}/` prefixes via the trailing-slash on `proxy_pass`. `/api/healthz` proxies to BlueMarlin's `/health` endpoint to match SR's frontend's expected global health route. Two new shell scripts shipped at `wtyj/scripts/`: `smoke_unboks_domain.sh` (6 external checks for post-cutover verification) and `cutover_unboks_domain.sh` (DNS verification + certbot + reload, runs in Phase B). Both registered as executable in git via `git update-index --chmod=+x` to prevent the chmod-drift footgun Brief 199 surfaced. No Python source code was touched.

## Tests
907 passing / 0 failures (baseline 907 + 0 new — pure infrastructure brief, no pytest tests added). Behavioral verification was via Phase A's Host-header smoke checks against the running nginx: `/api/healthz`, all 4 tenant `/health` endpoints, and 404 for unknown paths — all returned the expected statuses.

## Deployment
No docker rebuild needed (zero Python changes). The nginx config WAS the deploy and was applied in-line during Phase A execution (write file → `nginx -t` → `systemctl reload nginx`). Existing `api.wetakeyourjob.com` routes remain healthy and untouched. The new `api.unboks.org` server block is dormant until SR points DNS at `108.61.192.52` — at which point Phase B (`bash wtyj/scripts/cutover_unboks_domain.sh` on the VPS) issues the TLS cert and the cutover is live.

Brief is **executed for Phase A**. Phase B is documented + scripted, awaiting SR's DNS change.
