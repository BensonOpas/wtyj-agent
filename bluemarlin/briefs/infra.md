# INFRA.md — BlueMarlin Infrastructure Reference
# READ THIS before assuming anything about the VPS, deployment, or runtime.
# Update this file whenever infra facts change.

---

## VPS

| Item | Value |
|------|-------|
| Host | `108.61.192.52` |
| User | `root` |
| Port | 22 |
| SSH command | `ssh root@108.61.192.52` |
| SSH key (Mac) | `~/.ssh/id_rsa` |
| OS | Ubuntu |

---

## Project on VPS

| Item | Value |
|------|-------|
| Project root | `/root/bluemarlin/` |
| Source files | `/root/bluemarlin/src/` |
| Config files | `/root/bluemarlin/config/` |
| Log directory | `/root/bluemarlin/logs/` |
| Log filenames | `bluemarlin.log` (main), `bluemarlin_demo.log` (demo) |
| Python binary | `/usr/bin/python3` (3.12.3) |

---

## Environment Variables

- All secrets live in `/root/bluemarlin/config/bluemarlin.env`
- **NOT in `.bashrc`, `.zshrc`, or `.profile`** — Claude Code: do not look there
- The systemd unit sources this file at startup
- Key variables: `ANTHROPIC_API_KEY`, Azure OAuth credentials
- Azure refresh token file: `/root/bluemarlin/config/azure_refresh_token.txt`
- Calendar key: `/root/bluemarlin/config/bluemarlin-calendar-key.json`

---

## Poller Process

The email poller runs 24/7 as a systemd service. It is always running unless explicitly stopped.

| Item | Value |
|------|-------|
| Service name | `bluemarlin` |
| Status check | `systemctl status bluemarlin` |
| Is-active check | `systemctl is-active bluemarlin` |
| Restart | `systemctl restart bluemarlin` |
| Stop | `systemctl stop bluemarlin` |
| Logs (tail) | `journalctl -u bluemarlin -n 50` |
| Logs (follow) | `journalctl -u bluemarlin -f` |
| JSONL log | `/root/bluemarlin/logs/bluemarlin.log` (via bm_logger) |

---

## Deploy Flow

After every `git push` from Mac, Claude Code can deploy directly via Bash tool:

```bash
ssh root@108.61.192.52 "cd /root/bluemarlin && git pull && systemctl restart bluemarlin && systemctl is-active bluemarlin"
```

Key auth is configured — no password needed.

pip installs: `[VERIFY — ask Benson if any pip install is needed after dependency changes]`

---

## Google Workspace CLI (gws)

| Item | Value |
|------|-------|
| Binary path | `/usr/bin/gws` |
| Auth env var | `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` |
| Credentials file | `/root/bluemarlin/config/bluemarlin-calendar-key.json` |
| Spreadsheet ID | `1t1gy6qILNbJNwMBhvixT5yNspulT6-Mkr4-2dMo384I` |

---

## Email

| Item | Value |
|------|-------|
| Marina's inbox | `hello@wetakeyourjob.com` (Microsoft Outlook, OAuth2) |
| IMAP host | `outlook.office365.com:993` |
| SMTP host | `smtp.office365.com:587` |
| Demo support/relay | `butlerbensonagent@gmail.com` |
| Production support | `info@bluefinncharters.com` |

---

## Email Authentication

| Record | Type | Value |
|--------|------|-------|
| SPF | TXT @ | `v=spf1 include:spf.protection.outlook.com -all` |
| DKIM selector1 | CNAME | `selector1-wetakeyourjob-com._domainkey.NETORGFT20395980.p-v1.dkim.mail.microsoft` |
| DKIM selector2 | CNAME | `selector2-wetakeyourjob-com._domainkey.NETORGFT20395980.p-v1.dkim.mail.microsoft` |
| DMARC | TXT _dmarc | `v=DMARC1; p=none; rua=mailto:hello@wetakeyourjob.com; fo=1; adkim=s; aspf=s; pct=100` |

DKIM enabled in Microsoft 365 Defender → Email authentication → DKIM. Configured: 2026-03-10.

Next steps (operator):
- Verify headers show `spf=pass dkim=pass dmarc=pass` after 24–48h propagation
- Consider tightening DMARC: `p=none` → `p=quarantine` → `p=reject` after monitoring

---

## Console Convention

When asking Benson to run a command, ALWAYS specify which machine:
- **"Run on VPS:"** — command goes into the SSH session at `root@108.61.192.52`
- **"Run on Mac:"** — command goes into Benson's local terminal

Never say "run this command" without specifying which console.

---

## Things Claude Code Keeps Getting Wrong

1. **API key location** — it is in `bluemarlin.env`, NOT in `.bashrc` or shell profile. Never tell Benson to check `.zshrc` for the key.
2. **Poller is always running** — do not assume it needs to be started. It runs 24/7 via systemd. Just restart after deploys.
3. **VPS project path** — it is `/root/bluemarlin/`, NOT `/root/bluemarlin-agent/` (that is the Mac path).
4. **SSH from Claude Code** — Works. Key auth is set up (`~/.ssh/id_rsa`). Claude Code can SSH directly via the Bash tool. No password needed.

---

## Gaps to Verify

- pip installs: unknown — `[VERIFY: ask Benson if pip install is ever needed after changes]`
