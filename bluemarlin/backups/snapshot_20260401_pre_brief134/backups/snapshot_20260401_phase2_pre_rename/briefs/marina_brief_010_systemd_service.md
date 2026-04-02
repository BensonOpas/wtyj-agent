# BRIEF 010 — systemd background service
# This brief is executed manually on the VPS, not by Claude Code.
# Read CODEX_CONTEXT.md before executing this brief.
## Objective
Create a systemd service that runs email_poller.py automatically
on boot and keeps it running 24/7. If the poller crashes it
restarts automatically. Logs are accessible via journalctl.
## Context
Currently email_poller.py must be started manually with:
  cd /root/bluemarlin && python3 src/email_poller.py
It dies when the terminal closes or the VPS reboots.
A systemd service fixes both problems.
## Files to create
/etc/systemd/system/bluemarlin.service
## Files to read before making any changes
/root/bluemarlin/src/email_poller.py — confirm the entry point
Read the first 5 lines only to confirm the shebang and structure.
## Service file contents
Create /etc/systemd/system/bluemarlin.service with exactly:
[Unit]
Description=BlueMarlin Autonomous Booking Agent
After=network.target
Wants=network-online.target
[Service]
Type=simple
User=root
WorkingDirectory=/root/bluemarlin
Environment=ANTHROPIC_API_KEY=PLACEHOLDER
EnvironmentFile=-/root/bluemarlin/config/bluemarlin.env
ExecStart=/usr/bin/python3 /root/bluemarlin/src/email_poller.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=bluemarlin
[Install]
WantedBy=multi-user.target
## Environment file
Create /root/bluemarlin/config/bluemarlin.env with:
ANTHROPIC_API_KEY=the_actual_key_from_bashrc
This file is the authoritative source for the API key when
running as a service. The service reads it via EnvironmentFile.
This file must never be committed to Git — it is already covered
by the config/ gitignore rule.
## Steps to execute — follow this order exactly
STEP 1
Read /root/.bashrc and find the ANTHROPIC_API_KEY value.
Use that value to create /root/bluemarlin/config/bluemarlin.env:
  echo 'ANTHROPIC_API_KEY=<the_actual_value>' > /root/bluemarlin/config/bluemarlin.env
  chmod 600 /root/bluemarlin/config/bluemarlin.env
STEP 2
Create the service file at /etc/systemd/system/bluemarlin.service
with the exact contents shown above.
STEP 3
Reload systemd to pick up the new service file:
  systemctl daemon-reload
STEP 4
Enable the service so it starts on boot:
  systemctl enable bluemarlin
STEP 5
Start the service:
  systemctl start bluemarlin
STEP 6
Wait 5 seconds then check the service status:
  systemctl status bluemarlin
STEP 7
Check the live logs to confirm the poller started correctly:
  journalctl -u bluemarlin -n 20
## Test commands
Run these after completing all steps.
Report exact output of each test.
# Test 1 — service is active and running
systemctl is-active bluemarlin
# Test 2 — service is enabled for boot
systemctl is-enabled bluemarlin
# Test 3 — poller startup message visible in logs
journalctl -u bluemarlin -n 5 --no-pager
# Test 4 — ANTHROPIC_API_KEY is set in service environment
systemctl show bluemarlin --property=Environment
# Test 5 — confirm poller process is running
ps aux | grep email_poller | grep -v grep
## Definition of done
- [ ] /etc/systemd/system/bluemarlin.service created
- [ ] /root/bluemarlin/config/bluemarlin.env created with real key
- [ ] bluemarlin.env has chmod 600
- [ ] systemctl daemon-reload completed
- [ ] systemctl enable bluemarlin completed
- [ ] systemctl start bluemarlin completed
- [ ] systemctl is-active bluemarlin returns "active"
- [ ] systemctl is-enabled bluemarlin returns "enabled"
- [ ] journalctl shows poller startup message
- [ ] All 5 tests pass with exact output shown
- [ ] OUTPUT_010.md written to /root/bluemarlin/briefs/
- [ ] OUTPUT_010.md includes SYSTEM_STATE update block
