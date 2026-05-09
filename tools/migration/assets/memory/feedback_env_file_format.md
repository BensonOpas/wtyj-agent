---
name: env file format — no export prefix
description: VPS config/bluemarlin.env must use KEY=value format without 'export' prefix — systemd EnvironmentFile cannot parse 'export KEY=value'
type: feedback
---

Never add `export` prefix to lines in `config/bluemarlin.env`. systemd's `EnvironmentFile=` directive silently fails to parse `export KEY=value` — it only accepts `KEY=value`.

**Why:** A Claude Code session during Brief 075 added `export` prefixes to make `source bluemarlin.env` export vars to subprocesses for test runs. This broke both systemd services (bluemarlin + bluemarlin-social) — they loaded zero env vars, causing empty Claude API replies. The email service only survived because it hadn't been restarted yet.

**How to apply:** If a script needs the env vars exported (e.g., for running tests), use `export $(grep -v '^#' config/bluemarlin.env | grep '=' | xargs)` or `set -a; source config/bluemarlin.env; set +a` — never modify the file itself.
