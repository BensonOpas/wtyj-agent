# Claude Code Security Hook — PreToolUse (Windows port)
# Blocks dangerous commands even with bypass permissions enabled.
# Logs to %USERPROFILE%\.claude\hooks\security.log + audio bell on block.
#
# This is the Windows PowerShell port of the Mac security-gate.sh.
# All security blocks from the Mac version are preserved.
# The read-before-edit tracker has been REMOVED (caused false positives).

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
