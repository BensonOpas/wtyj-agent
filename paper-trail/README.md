# Paper Trail Snapshot — 2026-05-09

One-shot snapshot of Benson's `~/.claude/` paper trail from the Mac, taken
**2026-05-09 at the start of the Mac→Windows migration**, just before the
Mac was retired and handed to SR. Contents are conversation transcripts,
project history, file-history, plans, sessions, todos, plugins, the
top-level `~/.claude.json`, and other paper-trail dirs.

This branch is a **temporary transport mechanism** — see "After extracting"
below for the cleanup step.

---

## What's included

- `paper-trail.tar.zst.part-aa` (85MB)
- `paper-trail.tar.zst.part-ab` (74MB)
- `paper-trail.tar.zst.sha256` — SHA256 of the reassembled tarball (verify after `cat`)
- `paper-trail.chunks.sha256` — SHA256 of each chunk (verify after pulling)

Total compressed: 159MB. Raw uncompressed: ~900MB. Compression ratio: 5.6x.

## What's NOT included (intentional exclusions)

- `~/.claude/projects/-Users-benson-Projects-bluemarlin-agent/auth/` —
  unboks-cli credentials (password + JWT). These are secrets; never put in git.
  The unboks-cli will re-acquire them on first run on Windows.
- `~/.claude/settings.json` — already migrated separately on the
  `migration-state` branch (Windows-cleaned version).
- `~/.claude/hooks/` — already migrated separately on the `migration-state`
  branch (PowerShell ports).
- `~/.claude/cache/`, `image-cache/`, `paste-cache/` — caches, regenerable.
- `~/.claude/mcp-needs-auth-cache.json`, `stats-cache.json` — caches.
- `~/.claude/telemetry/` — Anthropic internal data, not paper trail.
- `~/.claude/chrome/chrome-native-host/` — fresh install on Windows when
  the claude-in-chrome extension is set up there.
- `~/.claude/teams/`, `session-env/`, `debug/` — empty on the Mac.

## Reassemble + extract on Windows

```powershell
# In PowerShell, on the Windows work user, after pulling this branch:
cd $env:USERPROFILE\Projects\wtyj-agent\paper-trail

# 1. Verify chunk integrity (optional but recommended)
Get-FileHash paper-trail.tar.zst.part-aa -Algorithm SHA256
Get-FileHash paper-trail.tar.zst.part-ab -Algorithm SHA256
# Compare to paper-trail.chunks.sha256

# 2. Reassemble
cmd /c "copy /b paper-trail.tar.zst.part-aa+paper-trail.tar.zst.part-ab paper-trail.tar.zst"

# 3. Verify the reassembled tarball
$expected = (Get-Content paper-trail.tar.zst.sha256).Split(' ')[0]
$actual = (Get-FileHash paper-trail.tar.zst -Algorithm SHA256).Hash.ToLower()
if ($expected -ne $actual) {
    Write-Error "SHA256 mismatch — reassembly corrupted. Re-pull the branch."
    exit 1
}
Write-Host "SHA256 OK." -ForegroundColor Green

# 4. Extract into %USERPROFILE% (paths inside the tar are relative to ~/)
#    Requires tar.exe (built into Windows 10 1803+) with zstd support, OR 7-Zip.
#    Windows tar supports zstd from Win11 22H2 onward (built-in libarchive).
tar --zstd -xf paper-trail.tar.zst -C $env:USERPROFILE
# If that fails (older Windows), use 7-Zip: 7z x paper-trail.tar.zst then 7z x paper-trail.tar

# 5. Verify the extract — should see the Mac-era project history
Test-Path "$env:USERPROFILE\.claude\projects\-Users-benson-Projects-bluemarlin-agent\a8da0e6a-d80e-4538-ae7c-11b06ae6beb0.jsonl"
# Expected: True
```

## After extracting — IMPORTANT cleanup

Once Windows has extracted and verified, **delete this branch from origin**.
It's a one-time transport mechanism — leaving 159MB of compressed conversation
history in the repo permanently is wasteful and arguably a security concern
(transcripts include business detail and may include occasional secrets that
slipped through the auth/ exclusion).

```bash
# From the Mac OR Windows after pull:
git push origin --delete paper-trail-mac-2026-05-09
git branch -D paper-trail-mac-2026-05-09  # local cleanup
```

Also delete the local `paper-trail/` directory after extraction:
```powershell
Remove-Item -Path "$env:USERPROFILE\Projects\wtyj-agent\paper-trail" -Recurse -Force
```

## What about the Mac-encoded project dir name?

The tarball contains `~/.claude/projects/-Users-benson-Projects-bluemarlin-agent/`
— that's the Mac-style path-encoding of the historical Mac project directory.
After extracting on Windows, that directory name will sit at
`%USERPROFILE%\.claude\projects\-Users-benson-Projects-bluemarlin-agent\` on
Windows too (just a folder name; the encoding doesn't have to match the actual
Windows path).

When you run `claude` in your Windows repo at `C:\Users\Benson-Work\Projects\wtyj-agent`,
Claude Code creates its OWN project directory keyed on the Windows path
(something like `C--Users-Benson-Work-Projects-wtyj-agent`). The two coexist —
one is your archive, one is your live history. That's intentional and correct.

`MEMORY.md` is referenced by `CLAUDE.md` via the literal path
`@~/.claude/projects/-Users-benson-Projects-bluemarlin-agent/memory/MEMORY.md`,
which resolves correctly on both Mac and Windows because we kept the encoded
path the same string. So memory keeps working without editing CLAUDE.md.

## Provenance

- Built on Mac at `/Users/benson/Projects/bluemarlin-agent/.claude/worktrees/etakeyourjob/`
- Date: 2026-05-09
- Source: `~/.claude/` + `~/.claude.json`
- Snapshotted via `rsync -a` (point-in-time, active jsonl session frozen at copy moment)
- Compressed: `tar --zstd`
- Split: `split -b 85m`
- One commit on orphan branch `paper-trail-mac-2026-05-09`, no parent in history
