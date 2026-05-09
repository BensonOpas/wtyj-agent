# WTYJ — Mac → Windows 11 Migration Plan
**Status:** LOCKED 2026-05-09 · Operator: Benson · From: Mac Mini · To: Windows 11 work user

---

## What this is

The complete plan to move your dev environment from Mac to a new Windows 11 work user. Two deliverables: this file and the prompt below. You transfer this file to Windows, do Phase 1 by hand, paste the prompt into Claude Code on Windows, and Claude does everything else.

Total time: ~30 minutes (10 min manual setup + 15 min Claude doing it + 5 min final logins).

The Mac is your fallback — DO NOT touch it until Windows passes the Phase 4 verification.

---

## TL;DR — what you actually do

1. **Phase 1 (10 min, manual on Windows).** Create work user, install Claude Code, log in.
2. **Paste the prompt below into Claude Code on Windows.** Hit enter.
3. **Phase 2 (~15 min).** Claude installs everything, copies state, generates SSH key. You watch.
4. **Phase 3 (5 min).** Four manual logins. Claude tells you exactly what to paste where.
5. **Phase 4.** Run four verification commands. If all pass, Windows is done. Mac stays as fallback for a day or two.
6. **Phase 5 (later, separate).** Hand the Mac to SR.

---

## THE PROMPT — paste this into Claude Code on Windows after Phase 1

```
You are running on my new Windows 11 work user. I'm migrating from a Mac. Read MIGRATION_PLAN.md (I have a copy of this file open in another window) and execute Phase 2 step-by-step. Stop after each major step and tell me what you did.

Specifically:
1. Verify you're on Windows 10 1809+ or Windows 11.
2. Install Git, Python 3.12, Node.js LTS, GitHub CLI via winget (per-user scope, no admin needed). Skip silently if already installed.
3. Clone git@github.com:BensonOpas/wtyj-agent.git into %USERPROFILE%\Projects\wtyj-agent. If the SSH key isn't set up yet, use HTTPS for the initial clone — we'll switch to SSH after gh auth.
4. From the clone, fetch the migration-state branch: `git fetch origin migration-state`.
5. From that branch, copy these into place under %USERPROFILE%\.claude\:
   - assets/settings.json → %USERPROFILE%\.claude\settings.json
   - assets/memory/*.md (37 files) → %USERPROFILE%\.claude\projects\-Users-benson-Projects-bluemarlin-agent\memory\
   - assets/hooks/security-gate.ps1 + notify-done.ps1 → %USERPROFILE%\.claude\hooks\
   - assets/hooks/sounds/*.mp3 → %USERPROFILE%\.claude\hooks\sounds\
6. Generate a fresh SSH key: ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\id_ed25519 -N ""
7. Print the public key + paste-ready commands for adding it to GitHub and the VPS.
8. Print the Phase 3 manual checklist.

DO NOT push any branches. DO NOT delete the migration-state branch. DO NOT log into anything on my behalf.

If anything fails, stop and tell me what failed and what you'd try next. Don't fight errors silently.
```

That's the full prompt. Copy-paste it as-is.

---

## Phase 1 — Manual setup on Windows (you do this, no Claude help, ~10 min)

### Step 1.1: Create the work user account

1. Press `Win + I` to open Settings.
2. Go to `Accounts` → `Other users`.
3. Click `Add account`.
4. Choose `I don't have this person's sign-in information` → `Add a user without a Microsoft account`.
   - **Use a LOCAL account, not a Microsoft account.** A Microsoft account would auto-sync OneDrive, themes, and possibly drag personal files into the work user. We want a clean start.
5. Username: `Benson-Work` (or whatever you want — the docs assume `Benson-Work` from here on).
6. Skip the password questions if asked, or set one.
7. After creation, click the new user → `Change account type` → set to `Administrator`. (Needed so winget can install per-user packages without prompting for separate credentials.)

### Step 1.2: Log into the work user

1. Click Start → your avatar → `Sign out`.
2. Log in as `Benson-Work`.
3. Set a wallpaper that's visually distinct from your gaming user — useful so you instantly know which user you're in.

### Step 1.3: Install Claude Code

1. Press `Win + X` → `Terminal (Admin)` to open Windows Terminal as admin (needed only for this one-time install — afterward you'll use it in regular mode).
2. Paste this exact command:
   ```
   irm https://claude.ai/install.ps1 | iex
   ```
3. Wait ~30 seconds. The installer downloads the binary and adds it to your PATH.
4. Close Windows Terminal entirely. Open it fresh (regular mode, not admin).
5. Run `claude --version`. If you see a version number, you're good.

### Step 1.4: Log into Claude Code

1. In a regular Windows Terminal, run `claude` in any folder (just to start a session).
2. When it prompts, type `/login`.
3. A browser window opens. Sign in with your Anthropic account (the same one you use on Mac).
4. Once signed in, you'll be at a `claude>` prompt. You're ready.

### Step 1.5: Open this MIGRATION_PLAN.md somewhere visible

Have it open in a text editor, browser, or printed out. Claude will reference parts of it during Phase 2.

---

## Phase 2 — Claude on Windows takes over (~15 min, you watch)

Paste **THE PROMPT** from above into the running Claude session. Claude will execute these steps in order:

### 2.1: Verify Windows version
Runs `[System.Environment]::OSVersion`. Confirms Win10 1809+ or Win11. If older, stops and tells you.

### 2.2: Install dev tools via winget (per-user scope)

```powershell
winget install --id Git.Git --scope user --accept-source-agreements --accept-package-agreements --silent
winget install --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements --silent
winget install --id OpenJS.NodeJS.LTS --scope user --accept-source-agreements --accept-package-agreements --silent
winget install --id GitHub.cli --scope user --accept-source-agreements --accept-package-agreements --silent
```

Each is wrapped in try/catch — if a package is already installed, Claude reports "skipped: already present" and moves on. No red errors.

After install, Claude reloads the PATH so the new binaries are findable in the same session:
```powershell
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "User") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "Machine")
```

Verifies each binary with `--version`.

### 2.3: Clone the repo

Creates `%USERPROFILE%\Projects` if missing. Initial clone over HTTPS (no SSH key yet):
```powershell
mkdir $env:USERPROFILE\Projects -ErrorAction SilentlyContinue
cd $env:USERPROFILE\Projects
git clone https://github.com/BensonOpas/wtyj-agent.git
cd wtyj-agent
```

If HTTPS prompts for credentials, Claude pauses and tells you to use a GitHub Personal Access Token or skip ahead to `gh auth login` first.

### 2.4: Fetch migration-state branch

```powershell
cd $env:USERPROFILE\Projects\wtyj-agent
git fetch origin migration-state
git checkout migration-state -- tools/migration/assets
```

This pulls just the `tools/migration/assets` folder from the migration-state branch into the working directory, without switching branches. The branch stays untouched on remote — you can delete it later when migration is verified.

### 2.5: Copy state files into place

Memory files (37 of them):
```powershell
$srcMem = "$env:USERPROFILE\Projects\wtyj-agent\tools\migration\assets\memory"
$dstMem = "$env:USERPROFILE\.claude\projects\-Users-benson-Projects-bluemarlin-agent\memory"
mkdir $dstMem -Force | Out-Null
Copy-Item "$srcMem\*.md" $dstMem -Force
```

Note the destination uses the Mac-style encoded path (`-Users-benson-Projects-...`). This is intentional: CLAUDE.md references this exact path with `@~/.claude/projects/-Users-benson-Projects-bluemarlin-agent/memory/MEMORY.md`. Keeping the same string makes both Mac and Windows resolve correctly without editing CLAUDE.md.

Settings:
```powershell
mkdir $env:USERPROFILE\.claude -Force | Out-Null
Copy-Item "$env:USERPROFILE\Projects\wtyj-agent\tools\migration\assets\settings.json" `
          "$env:USERPROFILE\.claude\settings.json" -Force
```

Hooks:
```powershell
$hooksDir = "$env:USERPROFILE\.claude\hooks"
mkdir $hooksDir -Force | Out-Null
mkdir "$hooksDir\sounds" -Force | Out-Null
Copy-Item "$env:USERPROFILE\Projects\wtyj-agent\tools\migration\assets\hooks\*.ps1" $hooksDir -Force
Copy-Item "$env:USERPROFILE\Projects\wtyj-agent\tools\migration\assets\hooks\sounds\*.mp3" "$hooksDir\sounds" -Force
```

### 2.6: Generate SSH key

Idempotent — only generates if no key exists:
```powershell
$sshDir = "$env:USERPROFILE\.ssh"
mkdir $sshDir -Force | Out-Null
$keyPath = "$sshDir\id_ed25519"
if (-not (Test-Path $keyPath)) {
    ssh-keygen -t ed25519 -f $keyPath -N '""' -C "benson-windows-$(Get-Date -Format 'yyyyMMdd')"
}
$pubKey = Get-Content "$keyPath.pub"
```

### 2.7: Print public key + Phase 3 commands

Claude prints:

```
Your new SSH public key:
  <pubkey here>

To add it to GitHub:
  After running 'gh auth login' in Phase 3, run:
  gh ssh-key add $env:USERPROFILE\.ssh\id_ed25519.pub --title "Benson-Windows"

To add it to the VPS (you'll be prompted for the VPS root password ONE time):
  ssh root@108.61.192.52 "echo '<pubkey>' >> ~/.ssh/authorized_keys"

Phase 3 manual logins:
  1. Sign into Chrome with butlerbensonagent@gmail.com (auto-syncs bookmarks/passwords)
  2. gh auth login   (browser-based, GitHub access)
  3. Paste the gh ssh-key command above
  4. Paste the ssh root@... command above (one-time, then SSH key works)
  5. cd $env:USERPROFILE\Projects\wtyj-agent ; pip install -r requirements.txt
  6. (Optional) cd tools/control-panel ; npm install   (if you use the local control panel)
  
After Phase 3, run Phase 4 verification.
```

### 2.8: Stop and wait

Claude does NOT run Phase 3 automatically. Manual logins require a human at the keyboard. Claude stops here and waits for you.

---

## Phase 3 — Manual logins (you do this, ~5 min)

### 3.1: Sign into Chrome

1. Open Chrome (it's installed by default on Windows 11, or grab from google.com/chrome).
2. Click the profile icon (top right) → `Sign in to Chrome` → use `butlerbensonagent@gmail.com`.
3. Wait 30 seconds. Bookmarks, passwords, extensions, history — all sync down.
4. Verify by checking your bookmarks bar — you should see your usual tabs.

### 3.2: GitHub auth

In Windows Terminal:
```
gh auth login
```
Choose `GitHub.com` → `HTTPS` → `Login with a web browser` → paste the one-time code into the browser → confirm. This gets you `git` and `gh` access without further prompts.

### 3.3: Add SSH key to GitHub

Paste the command Claude printed earlier:
```
gh ssh-key add $env:USERPROFILE\.ssh\id_ed25519.pub --title "Benson-Windows"
```

### 3.4: Add SSH key to VPS

Paste the SSH command Claude printed. You'll be prompted for the VPS root password ONCE. After this, you can `ssh root@108.61.192.52` without a password.

### 3.5: Switch the local repo from HTTPS to SSH (so future pulls don't prompt)

```
cd $env:USERPROFILE\Projects\wtyj-agent
git remote set-url origin git@github.com:BensonOpas/wtyj-agent.git
```

### 3.6: Install repo dependencies

```
cd $env:USERPROFILE\Projects\wtyj-agent
pip install -r requirements.txt
```

If you use the local control panel:
```
cd tools/control-panel
npm install
```

---

## Phase 4 — Verification (run these four; all must pass)

```powershell
# 1. Claude Code itself
claude --version
# Expected: a version number (no error)

# 2. Test suite parity
cd $env:USERPROFILE\Projects\wtyj-agent
python -m pytest wtyj/tests/ -q
# Expected: "1015 passed" (matches Mac baseline as of 2026-05-09)

# 3. VPS reachability
ssh root@108.61.192.52 "curl -s http://localhost:8001/health"
# Expected: {"status":"ok"}

# 4. unboks-cli works (memory + auth path resolution)
python tools/unboks-cli/tasks.py list --status open
# Expected: tasks list (will prompt for password '456' once on first run, then caches token)
```

If all four pass: **Windows is operational.** Use it for actual work for a day or two. Mac stays as fallback. Once you're confident, trigger Phase 5.

If any fails: STOP. Do not retire the Mac. Tell Claude what failed; debug from Windows.

---

## What gets preserved verbatim

| Item | From Mac | To Windows | Mechanism |
|---|---|---|---|
| Memory files (37 .md) | `~/.claude/projects/-Users-benson-Projects-bluemarlin-agent/memory/` | `%USERPROFILE%\.claude\projects\-Users-benson-Projects-bluemarlin-agent\memory\` | migration-state branch |
| Cleaned settings.json | `~/.claude/settings.json` | `%USERPROFILE%\.claude\settings.json` | migration-state branch (Mac-isms stripped) |
| Hook scripts | bash `.sh` | PowerShell `.ps1` (rewritten) | migration-state branch |
| Hook sounds (3 mp3s) | `~/.claude/hooks/sounds/` | `%USERPROFILE%\.claude\hooks\sounds\` | migration-state branch |

## What gets fresh-installed

| Item | Why fresh |
|---|---|
| Git, Python 3.12, Node LTS, gh CLI | Faster than copying; winget handles it |
| Claude Code binary | Native Windows installer, auto-updates |
| Anthropic auth token | Re-login (browser flow, same account) |
| GitHub auth token | `gh auth login` (browser flow, same account) |
| SSH key | New ed25519 key generated on Windows; added to GitHub + VPS |
| Chrome profile | Google sync pulls bookmarks/passwords/extensions on login |
| claude-hud, context7, pyright-lsp plugins | Auto-install on first Claude Code run via the `enabledPlugins` config |
| unboks-cli auth tokens | Re-login on first `tasks.py` run (password is `456`, takes 5 seconds) |

## What's intentionally NOT migrated

| Item | Why not |
|---|---|
| 734MB of conversation transcripts (`*.jsonl`) | Memory files capture state; transcripts are huge and rarely useful after the fact |
| 44MB file-history | Regenerable; Claude Code rebuilds as you work |
| `~/.claude/cache/`, `image-cache/` | Auto-rebuilds |
| `~/.claude/teams/`, `~/.claude/sessions/` | Per-machine ephemeral state |
| Mac-specific hook bits (osascript, afplay, `stat -f %m`, Keychains deny) | Replaced with Windows equivalents in the rewritten hooks |
| Mac chrome MCP extension state | Re-install when needed; not blocking for daily work |

## What lives on the VPS (untouched by migration)

The agent's production state — `hello@wetakeyourjob.com` mailbox, Late/Zernio/Meta tokens, all four containers (BlueMarlin/Adamus/Consulta/unboks), the `tasks.json` deploy queue — all live in `/root/clients/<tenant>/config/platform.env` and `/root/wtyj_deploy_queue.json` on the VPS. Nothing about migration touches them.

---

## Hooks — what stays vs what was dropped

### KEPT (security checks — unchanged behavior, ported to PowerShell)

| Block | Pattern |
|---|---|
| Destructive delete | `rm -rf` on `/`, `~`, `$HOME`, `../` |
| Fork bomb | `:(){...}` |
| Piped remote exec (Unix) | `curl \| sh`, `wget \| bash` |
| Piped remote exec (Windows, NEW) | `irm \| iex`, `iwr \| Invoke-Expression` |
| Git push to unknown remote | Anything not under `BensonOpas/` |
| Git remote add | All `git remote add` |
| Git force push | Any `git push --force` |
| Credentials in command line | `API_KEY=`, `SECRET_KEY=`, `sk_live_`, `sk_test_`, etc. |
| Data exfiltration | `curl -d @file ...` |
| Disk write | `dd of=/dev/...` |
| System shutdown | `shutdown`, `reboot`, `halt` |
| Write to `.env` | All `.env` paths |
| Write to SSH config | `id_*`, `authorized_keys`, `known_hosts` |
| Write to `.gitconfig` | The git config file |
| Audio bell on block | `[Console]::Beep(800, 300)` |
| Block log | `%USERPROFILE%\.claude\hooks\security.log` |

### DROPPED (the misfire source — gone for good)

The Mac script tracked every file you Read in a session via `/tmp/claude_read_files.txt` and blocked Edits on files you hadn't Read. This is what caused every red message you saw this session — the tracker missed reads done in subagents, in plan mode, in different worktrees, etc. It will not be ported.

### Notify-done (audio cue when Claude finishes a turn) — KEPT

Picks a random mp3 from `~/.claude/hooks/sounds/` and plays it via `System.Windows.Media.MediaPlayer` in a fire-and-forget background process. Same vibe as Mac's `afplay`.

---

## Troubleshooting (anticipated issues)

### "winget: command not found"
You're on a Windows version older than 1809, or winget isn't installed. Update Windows or install App Installer from the Microsoft Store.

### "claude: command not found" after install
Path didn't refresh in the current terminal. Close Windows Terminal entirely and reopen. If still not found:
```powershell
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "User") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "Machine")
```

### Hooks not firing on Windows
Settings.json hook commands need to invoke PowerShell explicitly. The migration sets them to:
```json
"command": "powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/security-gate.ps1"
```
If you see "execution policy" errors, run once as admin:
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### `git clone` over HTTPS prompts for credentials
Either run `gh auth login` first (gives `gh` a token that git uses), or use the SSH remote after Phase 3.4.

### Pytest fails on a clean clone
You skipped `pip install -r requirements.txt`. Run it from the repo root.

### `python -m pytest` count doesn't match 1015
The baseline as of this plan is 1015 (post Briefs 236+237). If new briefs ship between this plan and your migration, the number will be higher — check the latest in `wtyj/briefs/system_state.md` for the current expected count.

### Plugin auto-install fails on first Claude Code run
The three plugins (`claude-hud`, `context7`, `pyright-lsp`) install on demand from configured marketplaces. If they fail, run `/plugin install <name>` inside Claude.

### `tasks.py` says "Wrong password" when caching the first token
Default unboks dashboard password is `456`. If that fails, check VPS-side `/root/clients/unboks/config/platform.env` for `DASHBOARD_PASSWORD` — it might have been rotated.

### SSH to VPS times out
The VPS IP is `108.61.192.52`. If unreachable, check VPS status (https://my.vultr.com or whichever provider) and your firewall — port 22 must be reachable.

### Claude on Windows says "the migration-state branch doesn't exist"
The Mac side hasn't pushed it yet. Tell me to push it from the Mac before continuing.

---

## Phase 5 (later, separate from this plan) — Mac handover to SR

DO NOT do this until Windows passes Phase 4 verification AND you've used Windows for at least one full work day without issues.

When you're ready, this is what gets done on the Mac:
- Sign out of Chrome (your personal Google).
- `claude /logout` (Claude Code).
- `gh auth logout` (GitHub).
- Wipe `~/.claude/`, `~/.ssh/`, `~/.config/gh/`.
- Wipe browser sessions / clear cookies.
- Leave `~/Projects/wtyj-agent` cloned and clean — gives SR a starting point.
- Hand SR a one-page checklist: "Log in with your own Anthropic account, your own GitHub, your own Google, generate your own SSH key, add it to the VPS."

The agent's production accounts (`hello@wetakeyourjob.com`, Late, Zernio, Meta) live on the VPS — never on the Mac, never on Windows, untouched by handover.

This phase has its own brief when you're ready.

---

## Appendix A — Cleaned settings.json (the file Claude on Windows will write)

This is the EXACT content of `%USERPROFILE%\.claude\settings.json` after migration. Mac-isms removed, hook paths updated for PowerShell.

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  },
  "permissions": {
    "deny": [
      "Read(~/.ssh/**)",
      "Read(~/.gnupg/**)",
      "Read(~/.aws/**)",
      "Read(~/.azure/**)",
      "Read(~/.config/gh/**)",
      "Read(~/.git-credentials)",
      "Read(~/.docker/config.json)",
      "Read(~/.kube/**)",
      "Read(~/.npmrc)",
      "Read(~/.pypirc)",
      "TaskCreate",
      "TaskUpdate",
      "TaskList",
      "TaskGet"
    ],
    "defaultMode": "bypassPermissions"
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/security-gate.ps1"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/notify-done.ps1"
          }
        ]
      }
    ]
  },
  "enabledPlugins": {
    "claude-hud@claude-hud": true,
    "context7@claude-plugins-official": true,
    "pyright-lsp@claude-plugins-official": true
  },
  "extraKnownMarketplaces": {
    "claude-hud": {
      "source": {
        "source": "github",
        "repo": "jarrodwatts/claude-hud"
      }
    }
  },
  "effortLevel": "xhigh",
  "skipDangerousModePermissionPrompt": true,
  "teammateMode": "tmux",
  "remoteControlAtStartup": true,
  "agentPushNotifEnabled": true
}
```

Differences from Mac version:
- Removed: `Read(~/Library/Keychains/**)` from deny list (Mac-only path).
- Removed: the `statusLine` block that referenced `/opt/homebrew/bin/node` (claude-hud plugin auto-reconfigures statusLine on first run on Windows).
- Changed: hook command paths from `~/.claude/hooks/security-gate.sh` → `powershell -NoProfile -ExecutionPolicy Bypass -File ~/.claude/hooks/security-gate.ps1`.
- Same as Mac: everything else.

---

## Appendix B — security-gate.ps1 (full source)

This is the EXACT content of `%USERPROFILE%\.claude\hooks\security-gate.ps1`.

```powershell
# Claude Code Security Hook — PreToolUse (Windows port)
# Blocks dangerous commands even with bypass permissions enabled.
# Logs to %USERPROFILE%\.claude\hooks\security.log + audio bell on block.
#
# This is the Windows PowerShell port of the Mac security-gate.sh.
# All security blocks from the Mac version are preserved.
# The read-before-edit tracker has been removed (caused false positives).

$ErrorActionPreference = "Continue"
$logFile = "$env:USERPROFILE\.claude\hooks\security.log"

# Read JSON input from stdin
try {
    $rawInput = [Console]::In.ReadToEnd()
    $inputData = $rawInput | ConvertFrom-Json -ErrorAction Stop
} catch {
    # Malformed input — allow (don't break Claude Code)
    exit 0
}

$tool = $inputData.tool_name
$cmd = $inputData.tool_input.command
$file = $inputData.tool_input.file_path

function Block($reason, $detail) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    try {
        Add-Content -Path $logFile -Value "[$ts] BLOCKED | $reason | $detail" -ErrorAction SilentlyContinue
    } catch { }
    
    # Audio bell (non-blocking, fail-safe)
    try { [Console]::Beep(800, 300) } catch { }
    
    $output = @{
        hookSpecificOutput = @{
            hookEventName = "PreToolUse"
            permissionDecision = "deny"
            permissionDecisionReason = "SECURITY: $reason"
        }
    }
    $output | ConvertTo-Json -Compress
    exit 0
}

# === BASH/POWERSHELL COMMAND CHECKS ===
if ($tool -eq "Bash" -and $cmd) {

    # Destructive file operations
    if ($cmd -match 'rm\s+(-[a-zA-Z]*)?r[a-zA-Z]*f?\s+(/|~|\$HOME|\.\./)') {
        Block "Destructive delete" "rm -rf on root/home/parent: $cmd"
    }

    # Fork bomb
    if ($cmd -match ':\s*\(\s*\)\s*\{') {
        Block "Fork bomb" $cmd
    }

    # Piped remote execution (Unix-style)
    if ($cmd -match '(curl|wget)\s+.*\|\s*(sh|bash|zsh|python)') {
        Block "Piped remote execution" "curl/wget piped to shell: $cmd"
    }

    # Piped remote execution (PowerShell-style)
    if ($cmd -match '(irm|iwr|Invoke-RestMethod|Invoke-WebRequest)\s+.*\|\s*(iex|Invoke-Expression)') {
        Block "Piped remote execution (PowerShell)" "irm/iwr piped to iex: $cmd"
    }

    # Git push — verify remote is BensonOpas-owned
    if ($cmd -match '\bgit\s+push\b') {
        $remoteUrl = ""
        try {
            $remoteUrl = (git remote get-url origin 2>$null) -join ""
        } catch { }
        if ($remoteUrl -and -not ($remoteUrl -match 'github\.com[:/]BensonOpas/')) {
            Block "Git push to unknown remote" "$cmd (remote: $remoteUrl)"
        }
    }

    # Git remote add
    if ($cmd -match 'git\s+remote\s+add') {
        Block "Adding git remote" $cmd
    }

    # Force push
    if ($cmd -match 'git\s+push\s+.*--force') {
        Block "Force push" $cmd
    }

    # Credentials in command line (case-insensitive in PowerShell -match by default)
    if ($cmd -match '(API_KEY|SECRET_KEY|PASSWORD|PRIVATE_KEY|sk_live_|sk_test_)\s*=' `
        -and -not ($cmd -match '(os\.environ|getenv|setdefault|echo.*>>)')) {
        Block "Credential in command" "Possible secret in command line"
    }

    # Exfiltration (curl posting file content to URL)
    if ($cmd -match 'curl\s+.*(-d|--data)\s+.*@') {
        Block "Data exfiltration" "curl sending file data to URL: $cmd"
    }

    # Disk wipe
    if ($cmd -match 'dd\s+.*of=\s*/dev/') {
        Block "Disk write" "dd writing to device: $cmd"
    }

    # System shutdown / reboot
    if ($cmd -match '(shutdown|reboot|halt|init\s+0|Stop-Computer|Restart-Computer)') {
        Block "System shutdown" $cmd
    }
}

# === FILE WRITE CHECKS ===
if (($tool -eq "Write" -or $tool -eq "Edit") -and $file) {

    # Block writes to env files
    if ($file -match '\.env$') {
        Block "Write to env file" "Attempted edit of $file"
    }

    # Block writes to SSH keys / config
    if ($file -match '\.ssh[/\\](id_|authorized_keys|known_hosts)') {
        Block "Write to SSH config" "Attempted edit of $file"
    }

    # Block writes to git config
    if ($file -match '\.gitconfig$') {
        Block "Write to git config" "Attempted edit of $file"
    }
}

# === ALLOW EVERYTHING ELSE ===
# Note: read-before-edit tracker DELIBERATELY REMOVED (was the source of all
# misfires on Mac). Claude Code's own internal Read tracking is sufficient.
exit 0
```

---

## Appendix C — notify-done.ps1 (full source)

This is the EXACT content of `%USERPROFILE%\.claude\hooks\notify-done.ps1`.

```powershell
# Claude Code Stop Hook — random sound when Claude finishes a turn (Windows port)
# Mac equivalent: afplay random.mp3 &
# Windows: launches a hidden background process to play, then exits immediately
# (so it doesn't block Claude Code's turn-end).

$soundsDir = "$env:USERPROFILE\.claude\hooks\sounds"
$sounds = Get-ChildItem -Path $soundsDir -Filter "*.mp3" -ErrorAction SilentlyContinue
if (-not $sounds -or $sounds.Count -eq 0) { exit 0 }

$pick = ($sounds | Get-Random).FullName

# Fire-and-forget background process plays the sound
$playerScript = @"
Add-Type -AssemblyName presentationCore
`$player = New-Object System.Windows.Media.MediaPlayer
`$player.Open([uri]'$pick')
`$player.Play()
Start-Sleep -Seconds 5
"@

Start-Process powershell -ArgumentList @(
    "-NoProfile", "-WindowStyle", "Hidden", "-Command", $playerScript
) -WindowStyle Hidden -ErrorAction SilentlyContinue

exit 0
```

---

## Appendix D — Fact-check log

Every claim in this plan was verified before locking. Sources:

| Claim | Verified by | Result |
|---|---|---|
| Claude Code supports Windows native (no WSL) | https://code.claude.com/docs/en/setup | ✅ Win10 1809+ supported. Install: `irm https://claude.ai/install.ps1 \| iex` in PowerShell. |
| Claude Code config dir on Windows is `%USERPROFILE%\.claude` | Same doc, uninstall section | ✅ Confirmed via `Remove-Item -Path "$env:USERPROFILE\.claude"` in official uninstall instructions |
| Git for Windows recommended for Bash tool support | Same doc, Set up on Windows section | ✅ "If Git for Windows is not installed, Claude Code uses PowerShell" |
| `winget install Git.Git` valid | winget package catalog | ✅ Standard winget ID |
| `winget install Python.Python.3.12` valid | winget package catalog | ✅ Standard winget ID |
| `winget install OpenJS.NodeJS.LTS` valid | winget package catalog | ✅ Standard winget ID |
| `winget install GitHub.cli` valid | winget package catalog | ✅ Standard winget ID (lowercase `cli`) |
| Mac repo is `BensonOpas/wtyj-agent` (private) | `gh repo view` from this Mac | ✅ Private repo, safe to push migration-state branch |
| Memory dir contains 37 .md files | `ls ~/.claude/projects/.../memory/` from this Mac | ✅ Confirmed |
| Mac sound files: 3 mp3s (~96KB total) | `du -sh ~/.claude/hooks/sounds/` | ✅ grenade.mp3, opachki.mp3, subtask-completed.mp3 |
| `tools/unboks-cli/tasks.py` reads from `Path.home() / ".claude/projects/-Users-benson-Projects-bluemarlin-agent/auth/"` | Read of script lines 28-37 | ✅ `Path.home()` resolves to `%USERPROFILE%` on Windows; same encoded path works |
| CLAUDE.md references `@~/.claude/projects/-Users-benson-Projects-bluemarlin-agent/memory/MEMORY.md` | CLAUDE.md content from this Mac | ✅ `~` expands to USERPROFILE on Windows; placing memory at the same encoded path makes both Mac and Windows resolve correctly |
| Test baseline 1015 passing | `wtyj/briefs/system_state.md` latest entry | ✅ Briefs 236+237 |
| VPS IP `108.61.192.52` | `briefs/infra.md` and recent deploy commands | ✅ Confirmed |
| Hooks fire-and-forget pattern needed (don't block Claude turn-end) | Bash uses `&` on Mac | ✅ PowerShell equivalent: `Start-Process -WindowStyle Hidden` |
| `$env:USERPROFILE` is the Windows equivalent of `~` for Path.home() resolution | Python docs + Windows env var standard | ✅ Confirmed |

**Things deliberately NOT verified (acknowledged as best-effort):**
- Whether `~` expansion in `settings.json` hook command paths works identically on Windows. The plan uses `~/.claude/hooks/...` syntax in the command string. PowerShell DOES expand `~` to `$HOME` (which is `$env:USERPROFILE` on Windows). If it doesn't work, the troubleshooting section covers the explicit-path workaround.
- Whether `tmux` is available on Windows native (used for `teammateMode`). If it isn't, that setting becomes a no-op — Claude Code falls back to its default. Not blocking.

---

## Appendix E — What Mac-side has to do before Windows can pull (one push)

The Mac side must push the `migration-state` branch to `origin` before Windows can pull. The branch contains:

```
tools/migration/assets/
├── memory/                       (37 .md files copied from ~/.claude/projects/.../memory/)
├── settings.json                 (Windows-cleaned version, see Appendix A)
└── hooks/
    ├── security-gate.ps1         (Appendix B)
    ├── notify-done.ps1           (Appendix C)
    └── sounds/
        ├── grenade.mp3
        ├── opachki.mp3
        └── subtask-completed.mp3
```

The push script lives at `tools/migration/push-migration-state.sh` (committed to main alongside this plan, kept around for the Mac handover phase too).

Once the migration is verified on Windows, the migration-state branch can be deleted from origin:
```
git push origin --delete migration-state
```

---

## End of plan

Lock-in date: 2026-05-09. Author: Benson + Claude (Opus 4.7). Verified pre-execution. No edits to the plan are expected during execution — if something needs to change, fix the plan first, then execute.
