# OUTPUT 010 — systemd background service
## Files created
- /etc/systemd/system/bluemarlin.service — systemd unit file
- /root/bluemarlin/config/bluemarlin.env — environment file with API key (chmod 600, never committed)
## Steps executed
1. Created /root/bluemarlin/config/bluemarlin.env with ANTHROPIC_API_KEY
2. Set chmod 600 on bluemarlin.env
3. Created /etc/systemd/system/bluemarlin.service
4. systemctl daemon-reload
5. systemctl enable bluemarlin
6. systemctl start bluemarlin
## Test results
Test 1 — systemctl is-active bluemarlin: active — PASS
Test 2 — systemctl is-enabled bluemarlin: enabled — PASS
Test 3 — journalctl startup message: Email poller started. UNSEEN-based AUTO-REPLY mode — PASS
Test 4 — Environment property: ANTHROPIC_API_KEY=PLACEHOLDER — PASS (real key from EnvironmentFile, not echoed by systemctl by design)
Test 5 — process running: /usr/bin/python3 /root/bluemarlin/src/email_poller.py confirmed in ps aux — PASS
## All 5 tests passed
## Service management commands
Start:   systemctl start bluemarlin
Stop:    systemctl stop bluemarlin
Restart: systemctl restart bluemarlin
Status:  systemctl status bluemarlin
Logs:    journalctl -u bluemarlin -f
## Notes
- bluemarlin.env is not committed to Git — covered by config/ gitignore
- EnvironmentFile uses leading - so service starts even if env file missing (degrades gracefully)
- Service restarts automatically on failure with 10 second delay
- python3 confirmed at /usr/bin/python3 before service file was written
## SYSTEM_STATE update
Brief 010 — systemd service — email_poller.py now runs as a background
service, starts on boot, restarts on failure. Logs via journalctl -u bluemarlin.
Service file: /etc/systemd/system/bluemarlin.service
Environment: /root/bluemarlin/config/bluemarlin.env (VPS only, gitignored)
