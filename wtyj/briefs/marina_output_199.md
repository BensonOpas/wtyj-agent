# OUTPUT 199 — Unboks tenant: SOT-based client.json + WhatsApp credential migration for FB promo

## What was done

Replaced `clients/unboks/config/client.json` with a real customer-facing config derived from Calvin's SOT spec — agent named "Calvin" (internal id `calvin-csa`), 5 languages, never-quote-pricing rule, `topics_refused` covering competitor names + technical details + medical/legal advice, full SOT pasted verbatim into `agent_persona.freeform_notes` so Marina has the full product context. Wrote and shipped a small idempotent shell script (`/tmp/move_wa_creds.sh`, scp'd to VPS, executed, deleted) that moved the 8 WhatsApp/Zernio/Meta/Late credential lines from `bluemarlin/config/platform.env` to `unboks/config/platform.env` with timestamped backups (`*.bak.20260503-220922`). Restarted both containers (`docker compose restart` for bluemarlin, `down + up -d` for unboks so the new client.json loads). Added a 3-test pytest module (`wtyj/tests/test_199_unboks_config.py`) validating JSON shape, agent identity (Calvin / 5 langs / booking off), and pricing-guard rule presence. Updated `wtyj/briefs/infra.md` with the routing change note and reframed Unboks's tenant row from "internal sandbox" to "own product, customer-facing".

## Tests

907 passing / 0 failures (baseline 904 + 3 new).

## Deployment

Backend image unchanged (no Python changes). Source commit to be made post-review. Container restarts already done as part of execution since the credential move is a runtime config change, not a code change. Verified post-restart:
- `https://api.wetakeyourjob.com/unboks/health` and `bluemarlin/health` both return `{"status":"ok"}`
- `bluemarlin/config/platform.env`: all WHATSAPP_*, META_*, LATE_API_KEY, ZERNIO_WEBHOOK_SECRET lines empty (`=<empty>`)
- `unboks/config/platform.env`: same 8 keys all populated (`=<set>`)

**Required follow-up outside this brief:** Calvin/SR must update Meta's developer console (or Zernio's account dashboard, depending on which platform handles the WhatsApp routing) to change the inbound webhook URL from `https://api.wetakeyourjob.com/bluemarlin/webhook/whatsapp` to `https://api.wetakeyourjob.com/unboks/webhook/whatsapp`. Until that flip, inbound messages still hit the now-credentials-empty bluemarlin tenant and the routing fix isn't fully live. Backend is ready; the URL change is the last mile.
