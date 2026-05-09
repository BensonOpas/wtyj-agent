---
name: Windows migration plan
description: Full plan to migrate Benson's dev environment from Mac Mini to Windows 11 PC with WSL2. Not urgent — he's staying on macOS for now. Reference when he's ready.
type: project
originSessionId: a8da0e6a-d80e-4538-ae7c-11b06ae6beb0
---
Benson wants to move his WTYJ dev workflow from Mac Mini to his Windows 11 PC (good GPU, good CPU, 32GB RAM). He prefers working on Windows and wants both monitors on one machine. Not happening now — staying on macOS — but the plan is ready.

**Why:** He prefers Windows. Currently has 2 monitors shared between Mac Mini and Windows PC, with one keyboard he physically swaps between USB ports. He wants both monitors on Windows only and the Mac retired or headless.

**How to apply:** When Benson says "let's migrate" or "set up Windows", execute this plan.

## Physical setup decision (UPDATED 2026-05-09)
- **Separate Windows user accounts** for full isolation: `Benson-Work` (WTYJ) and existing user (gaming/personal).
- Log out / log in to switch — friction is intentional, acts as a hard mental break (Benson is burnt out, semi-retiring; the friction is a feature).
- WSL2 + Ubuntu installed INSIDE the work user only. Personal user never sees it.
- Work user's Chrome signs into `butlerbensonagent@gmail.com`. Personal Chrome stays on his personal Google.
- Earlier plan suggested virtual desktops — superseded. Files-mess concern + clean-break requirement made separate user the better fit.

## Mac handover to SR (NEW 2026-05-09)
- Benson is semi-retiring. SR will drive most work going forward. Mac Mini gets handed to SR.
- Order of operations: get Benson fully working on Windows FIRST (Mac as fallback), verify for a day or two, THEN prep Mac for SR.
- Mac prep checklist: sign out of all Benson's accounts (Google, Anthropic Claude Code, GitHub via gh, iCloud), wipe local creds (`~/.claude/`, `~/.ssh/`, `~/.config/gh/`, browser sessions), leave repo cloned at `~/Projects/wtyj-agent` so SR can `cd` and start, hand SR a checklist of what HE needs to log into (his own Anthropic key, his own GitHub auth, his own Google, his own VPS SSH key registered).
- VPS-side accounts (`hello@wetakeyourjob.com` Outlook, agent's Late/Zernio/Meta tokens) are NOT on the Mac — they live on the VPS at `/root/clients/<tenant>/config/platform.env`. Untouched by handover.

## What comes free with `git clone`
- CLAUDE.md, all source, briefs, tests, docs, control panel
- `.claude/agents/*.md` (6 agents) — but 3 have hardcoded Mac paths to fix
- `.claude/commands/brief.md` — has hardcoded Mac path to fix

## Files to copy from Mac
Memory files (29 .md files):
- FROM: `~/.claude/projects/-Users-benson-Projects-bluemarlin-agent/memory/`
- TO: `~/.claude/projects/-home-benson-Projects-bluemarlin-agent/memory/`

Global settings:
- FROM: `~/.claude/settings.json`
- TO: `~/.claude/settings.json` on WSL (then fix Mac-specific items below)

Hook scripts:
- FROM: `~/.claude/hooks/security-gate.sh` and `notify-done.sh`
- TO: same path on WSL, with these Mac→Linux fixes:
  - `osascript -e "display notification..."` → `notify-send` or PowerShell toast
  - `afplay` → `powershell.exe -c "(New-Object Media.SoundPlayer ...).PlaySync()"` or `mpv`
  - `stat -f %m` → `stat -c %Y`
  - Remove `~/Library/Keychains/**` from deny list

## Hardcoded paths to fix (in repo, commit the changes)
- `.claude/agents/task-sync.md:26` — `cd /Users/benson/Projects/bluemarlin-agent` → use `git rev-parse --show-toplevel`
- `.claude/agents/code-explainer.md:32` — same fix
- `.claude/commands/brief.md:77` — add WSL path alongside Mac path, or use `git rev-parse --show-toplevel`

## Fresh setup on WSL (can't copy)
1. `wsl --install` (installs Ubuntu, reboot)
2. Python 3.12: `sudo apt install python3.12 python3-pip python3.12-venv`
3. Node via nvm: `curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash && nvm install 22`
4. Git + GH CLI: `sudo apt install git` + `gh auth login`
5. Claude Code: `npm install -g @anthropic-ai/claude-code` + `claude login`
6. SSH keys: `ssh-keygen -t ed25519` → add to GitHub + VPS `authorized_keys`
7. Git identity: `git config --global user.name "Benson"` + email
8. Clone repo: `git clone git@github.com:BensonOpas/wtyj-agent.git ~/Projects/bluemarlin-agent`
9. `pip install -r requirements.txt`
10. Verify: `python3 -m pytest wtyj/tests/ -q` + `ssh root@108.61.192.52 "curl -s http://localhost:8001/health"`

## Settings.json Mac-specific items to fix
- statusLine command references `/opt/homebrew/bin/node` → re-install claude-hud plugin, auto-configures
- deny list has `~/Library/Keychains/**` → remove (macOS-only)
- Hooks reference `osascript` and `afplay` → see hook fixes above

## MCP servers
- claude-in-chrome: needs Chrome on Windows + the extension. WSL can talk to Windows Chrome via localhost. Separate setup.

## Estimated time: ~1.5 hours total
- WSL + dev tools: 45 min
- Memory/settings copy + path fixes: 30 min
- Auth setup (SSH, gh, claude): 15 min

## WSL2 notes for Benson's reference
- Ships with Windows 11, maintained by Microsoft, millions of users
- Local — no wifi needed to use it (only for git push/ssh/pip install)
- Keep code in `~/` inside WSL (NOT `/mnt/c/` — that's slow)
- 32GB RAM handles WSL + gaming simultaneously with zero issues
- `.wslconfig` can cap WSL RAM if ever needed: `[wsl2]\nmemory=8GB`
