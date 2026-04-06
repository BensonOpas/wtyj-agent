# BRIEF 056 — SSH Key Auth: Claude Code → VPS
**Status:** Complete (executed in session)
**Files:** `bluemarlin/briefs/INFRA.md`
**Depends on:** —
**Blocks:** —

## Context
INFRA.md stated "Claude Code's sandbox blocks outbound SSH. Benson must run SSH commands himself." This was never verified. It was an assumption written early in the project. Every deploy since has required Benson to manually open an SSH session, run `git pull`, and restart the service — Claude Code could not do this autonomously.

## Why This Approach
The Mac's `~/.ssh/id_rsa` key was already on the VPS in `~/.ssh/authorized_keys`, but the entry was malformed (likely a line-wrap from a manual paste). Running `ssh-copy-id` from the Mac correctly reinstalled the key. Once key auth worked, the Bash tool's `ssh` call succeeded — no sandbox restriction exists on Mac. No new tooling, no MCP server, no webhook. Simplest possible fix.

## Source Material
Verified in session:
- `ssh -o BatchMode=yes root@108.61.192.52 "echo ok"` → `ok`
- Deploy one-liner confirmed working: `ssh root@108.61.192.52 "cd /root/bluemarlin && git pull && systemctl restart bluemarlin && systemctl is-active bluemarlin"` → `active`
- Briefs 053–055 deployed via this method in the same session

## Instructions
All steps were executed in session. Documenting for the record:

1. Benson ran on Mac: `ssh-copy-id -i ~/.ssh/id_rsa.pub root@108.61.192.52` (password entered once)
2. Claude Code verified: `ssh -o BatchMode=yes root@108.61.192.52 "echo ok"` → `ok`
3. Claude Code deployed 053–055: `ssh root@108.61.192.52 "cd /root/bluemarlin && git pull && systemctl restart bluemarlin && systemctl is-active bluemarlin"` → `active`
4. INFRA.md updated:
   - Deploy Flow section rewritten to show Claude Code runs the one-liner directly
   - "Things Claude Code Keeps Getting Wrong" item 4 corrected from "SSH blocked" to "SSH works, key auth configured"
5. MEMORY.md updated: removed wrong note, added deploy one-liner

## Tests
Already verified in session:
- `ssh -o BatchMode=yes root@108.61.192.52 "echo ok"` exits 0, prints `ok`
- VPS service `is-active` returns `active` after deploy

## Success Condition
Claude Code can deploy to VPS in one Bash tool call without any manual steps from Benson.

## Rollback
N/A — key auth is additive. The VPS password still works if key auth is ever removed.
