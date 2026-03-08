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
| Log filename | `[VERIFY: ls /root/bluemarlin/logs/]` |
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

After every `git push` from Mac, run this on VPS:

```bash
ssh root@108.61.192.52
cd /root/bluemarlin
git pull
systemctl restart bluemarlin
systemctl status bluemarlin   # confirm active
```

One-liner from Mac (once SSH key is confirmed working):
```bash
ssh root@108.61.192.52 "cd /root/bluemarlin && git pull && systemctl restart bluemarlin"
```

pip installs: `[VERIFY — ask Benson if any pip install is needed after dependency changes]`

---

## Google Workspace CLI (gws)

| Item | Value |
|------|-------|
| Binary path | `[VERIFY: run 'which gws' on VPS]` |
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

## Things Claude Code Keeps Getting Wrong

1. **API key location** — it is in `bluemarlin.env`, NOT in `.bashrc` or shell profile. Never tell Benson to check `.zshrc` for the key.
2. **Poller is always running** — do not assume it needs to be started. It runs 24/7 via systemd. Just restart after deploys.
3. **VPS project path** — it is `/root/bluemarlin/`, NOT `/root/bluemarlin-agent/` (that is the Mac path).
4. **SSH from Claude Code** — Claude Code's sandbox blocks outbound SSH. Cannot SSH from tool calls. Benson must run SSH commands himself or use the one-liner above.

---

## Gaps to Verify (run on VPS manually)

```bash
# 1. Exact log filename
ls /root/bluemarlin/logs/

# 2. gws binary path
which gws

# 3. pip — check if a venv is in use
which python3
pip3 list | grep -E "anthropic|dateparser"
```

Update this file once verified.
