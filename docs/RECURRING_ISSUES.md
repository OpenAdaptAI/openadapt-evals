# Recurring Issues Registry

**Purpose**: Prevent solving the same problem multiple times due to context loss.

**Rule**: Before fixing ANY infrastructure issue, check this file and run `bd list --labels=recurring`.

---

## Issue #1: Windows Product Key / Edition Selection Prompt

**Symptom**: Windows installer shows "Select operating system" or asks for product key instead of auto-installing.

**Root Cause**: Multiple factors can cause this:
1. `VERSION=11e` (Enterprise Evaluation) shows edition picker - use `VERSION=11` (Pro) instead
2. Missing `InstallFrom/MetaData` element in autounattend.xml
3. Cached Windows storage at `/mnt/waa-storage/` has old broken install
4. Using `dockurr/windows` directly instead of `waa-auto` image
5. Docker image not rebuilt after Dockerfile changes

**Fix Checklist**:
- [ ] Dockerfile uses `VERSION=11` (not `11e`)
- [ ] Dockerfile patches autounattend.xml with InstallFrom/MetaData for index 1
- [ ] Delete cached storage: `rm -rf /mnt/waa-storage/*`
- [ ] Rebuild image: `docker build --no-cache -t waa-auto .`
- [ ] Verify container uses `waa-auto:latest` not `dockurr/windows`

**Prior Fix Attempts**:
| Date | Commit | What was tried | Result |
|------|--------|----------------|--------|
| 2026-01-XX | ??? | Added VERSION=11 | Partial - still saw prompts |
| 2026-01-XX | ??? | Added InstallFrom sed patch | Unknown |
| 2026-01-20 | ??? | Reset storage + fresh install | Still showing prompt |

**Beads Tasks**: `bd list --labels=windows,product-key`

---

## Issue #2: WAA Server Not Responding (Timeout)

**Symptom**: `vm probe` times out after 600s, WAA server never responds on port 5000.

**Root Cause**: Multiple factors:
1. Windows stuck at installation prompt (see Issue #1)
2. Windows installed but install.bat never ran (FirstLogonCommands failed)
3. Python/Flask not installed in Windows
4. Network misconfiguration (wrong IP: should be 172.30.0.2)

**Fix Checklist**:
- [ ] Check VNC at localhost:8006 - what does Windows show?
- [ ] If at desktop, check if install.bat ran (look for WAA folder)
- [ ] Check container logs: `docker logs winarena`
- [ ] Verify network: container should use `--net=waa-net` with IP 172.30.0.2

**Beads Tasks**: `bd list --labels=waa,timeout`

---

## Adding New Recurring Issues

When you encounter an issue that:
1. Has happened before (check git history, CLAUDE.md)
2. Involves infrastructure (VMs, Docker, Windows, Azure)
3. Has non-obvious root causes

Add it here with:
1. **Symptom**: What the user sees
2. **Root Cause**: Why it happens (may be multiple)
3. **Fix Checklist**: Step-by-step verification
4. **Prior Fix Attempts**: Table of what was tried

Also create a Beads task with `--labels=recurring`:
```bash
bd create "Issue title" -p 1 --labels=recurring,infrastructure -d "Description"
```

---

## For Claude Code Agents

**MANDATORY before any infrastructure fix**:
1. Read this file
2. Run `bd list --labels=recurring`
3. Check if this issue is already documented
4. If yes, follow the Fix Checklist
5. If no, document it here BEFORE attempting fix

**After any fix attempt**:
1. Update the "Prior Fix Attempts" table
2. Create/update Beads task with result
3. If fix worked, document WHY in root cause section
