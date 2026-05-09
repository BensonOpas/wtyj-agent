# Claude Code Stop Hook — random sound when Claude finishes a turn (Windows port)
# Mac equivalent: afplay random.mp3 &
# Windows: launches a hidden background process to play the sound, then exits
# immediately so it doesn't block Claude Code's turn-end.

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
