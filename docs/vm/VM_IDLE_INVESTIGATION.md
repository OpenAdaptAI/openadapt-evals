# VM Idle Investigation Report

**Investigation Date**: 2026-01-19 03:32 UTC
**VM Name**: waa-eval-vm
**Resource Group**: OPENADAPT-AGENTS

---

## Executive Summary

**IMMEDIATE RECOMMENDATION**: 🚨 **STOP THE VM NOW** - It is idle, stuck, and wasting money.

**Status**: VM is running but completely idle with a stuck container that has been waiting for Windows ISO for 31+ minutes.

**Issue**: Container stuck on "Error: ISO file not found or is empty" - Windows cannot boot, WAA server will never respond.

**Cost Impact**:
- VM running for 3h 38min (since VM restart, not creation)
- Hourly cost: $0.20/hour (Standard_D4ds_v5)
- Cost so far: ~$0.73
- Projected daily waste: $4.80 if left running

---

## 1. Current VM State

### VM Information
- **VM Name**: waa-eval-vm
- **Size**: Standard_D4ds_v5
- **Location**: westus2
- **Created**: 2026-01-08T15:15:44Z (10 days ago)
- **Power State**: VM running
- **Current Uptime**: 3 hours, 38 minutes (VM was restarted recently)
- **Public IP**: 172.171.112.41
- **Private IP**: 10.0.0.4

### Cost Calculation
- **Hourly Rate**: $0.20/hour (Standard_D4ds_v5 pricing)
- **Current Session Cost**: ~$0.73 (3.6 hours)
- **Total VM Cost (10 days)**: Indeterminate (VM may have been stopped/started multiple times)
- **Waste per Day**: $4.80/day if left idle

---

## 2. Container Status

### Docker Container: winarena

**Status**: Running but stuck (Up 31 minutes)

**Issue**: Container cannot start Windows VM due to missing ISO file

**Container Logs** (last 50 lines):
```
Starting WinArena...
Starting VM...
Starting WinArena VM...
❯ Starting Windows for Docker v0.00...
❯ For support visit https://github.com/dockur/windows
❯ CPU: Intel Xeon Platinum 8370C | RAM: 14/16 GB | DISK: 98 GB (ext4) | KERNEL: 6.8.0-1044-azure...

Error: ISO file not found or is empty.
Waiting for a response from the windows server. This might take a while...
[Repeated 14+ times]
```

**Diagnosis**:
- Container is stuck in infinite wait loop
- Windows VM cannot boot without ISO file
- WAA server will NEVER respond in this state
- No progress for 31+ minutes (container uptime)

### WAA Server Status
- **Endpoint**: http://172.171.112.41:5000/probe
- **Status**: NOT RESPONDING (expected - Windows never booted)
- **Root Cause**: Windows ISO missing, VM cannot start

---

## 3. Auto-Shutdown Analysis

### CRITICAL FINDING: No Auto-Shutdown Configured

**Regular Azure VMs do NOT have auto-shutdown by default.**

The VM `waa-eval-vm` is a **regular Azure VM** (not Azure ML Compute Instance).

**Auto-Shutdown Configuration Status**:
- ❌ No Azure DevTestLab schedule found
- ❌ No `scheduledEventsProfile` configured
- ❌ No auto-shutdown configured via `az vm auto-shutdown`
- ❌ This is NOT an Azure ML Compute Instance (those have 60-min idle timeout)

**Why Auto-Shutdown Didn't Trigger**:
Because it doesn't exist. Regular Azure VMs run indefinitely until manually stopped.

**What About `idle_timeout_minutes` in azure.py?**

The `idle_timeout_minutes: int = 60` configuration in `/Users/abrichr/oa/src/openadapt-evals/openadapt_evals/benchmarks/azure.py` line 246 is for **Azure ML Compute Instances**, not regular VMs.

From `azure.py` line 517:
```python
compute = ComputeInstance(
    name=name,
    size=vm_size,
    idle_time_before_shutdown_minutes=self.config.idle_timeout_minutes,
)
```

This VM (`waa-eval-vm`) was created as a regular VM, not via Azure ML. Therefore, this timeout does NOT apply.

**Conclusion**: Auto-shutdown is a **missing feature** for regular VMs.

---

## 4. Activity Monitoring

### Why Dashboard Shows "No Recent Activity"

**Live Tracking File**: `/Users/abrichr/oa/src/openadapt-evals/benchmark_live.json`

**Contents**:
```json
{
  "status": "complete",
  "total_tasks": 5,
  "tasks_completed": 5
}
```

**Analysis**:
- This file is from a PREVIOUS completed evaluation (5 tasks, all complete)
- Current VM session has NO active evaluation running
- Dashboard correctly shows "no recent activity" because there IS no activity
- The VM is idle and not being used for any task

**Is Monitoring Broken?**
No. Monitoring is working correctly. The VM is genuinely idle with no active tasks.

---

## 5. Cost Analysis

### Actual Costs

**VM Pricing** (Standard_D4ds_v5, West US 2):
- Hourly: $0.20/hour
- Daily: $4.80/day
- Weekly: $33.60/week
- Monthly: $144.00/month

**Current Session**:
- Runtime: 3.6 hours
- Cost: ~$0.73

**If Left Running Idle**:
- 1 day: $4.80 wasted
- 1 week: $33.60 wasted
- 1 month: $144.00 wasted

**Is This Intentional?**
No. The container is stuck and will never become productive.

**Is This Waste?**
Yes. 100% waste. Container is broken and cannot complete any work.

---

## 6. Investigation Checklist

- [x] VM running time and cost: 3.6 hours, ~$0.73
- [x] Container status: Running but stuck on ISO error
- [x] Windows ISO download progress: FAILED (ISO not found)
- [x] WAA server responding: NO (cannot boot without Windows)
- [x] Auto-shutdown code exists: YES (but only for Azure ML Compute Instances)
- [x] Auto-shutdown configuration: NO (regular VMs don't have this by default)
- [x] Why logs aren't showing: Logs show container IS stuck
- [x] Recommendation: **STOP IMMEDIATELY**

---

## 7. Root Cause Analysis

### Problem: Container Stuck on ISO Download

**Error**: `Error: ISO file not found or is empty.`

**What this means**:
The container is trying to boot a Windows 11 VM using the `dockur/windows` Docker image, but the Windows ISO file is either:
1. Not downloaded yet
2. Failed to download
3. Corrupted or empty
4. Incorrect path configuration

**Why it's stuck**:
The container retries indefinitely without failing, so it will never self-terminate.

**Why WAA server doesn't respond**:
The WAA server runs inside the Windows VM. If Windows cannot boot, the server will never start.

---

## 8. Recommendations

### IMMEDIATE ACTION (RIGHT NOW)

**Stop the VM to prevent further waste**:

```bash
az vm deallocate --resource-group OPENADAPT-AGENTS --name waa-eval-vm
```

**Estimated savings**: $4.80/day

---

### SHORT-TERM FIX (Next Session)

**Option A: Fix the ISO issue**

The container needs to download the Windows 11 ISO. This can take a while (potentially hours) depending on network speed.

**Steps**:
1. Start VM
2. SSH into VM or use `az vm run-command`
3. Check container logs: `docker logs winarena -f`
4. Monitor ISO download progress
5. If ISO download succeeds, Windows will eventually boot (could take 20-30 min)
6. Verify WAA server responds: `curl http://localhost:5000/probe`

**Command to monitor**:
```bash
az vm run-command invoke \
  --resource-group OPENADAPT-AGENTS \
  --name waa-eval-vm \
  --command-id RunShellScript \
  --scripts "docker logs winarena -f"
```

**Option B: Recreate the container with proper ISO**

If the ISO issue persists, you may need to:
1. Stop and remove the container: `docker stop winarena && docker rm winarena`
2. Re-run `vm-setup` command to create it fresh
3. This time, monitor the logs to ensure ISO downloads successfully

**Re-setup command**:
```bash
uv run python -m openadapt_evals.benchmarks.cli vm-setup \
  --vm-name waa-eval-vm \
  --resource-group OPENADAPT-AGENTS \
  --auto-verify
```

---

### LONG-TERM SOLUTION (Missing Feature)

**Problem**: Regular Azure VMs have no auto-shutdown by default.

**Solution 1: Implement auto-shutdown for regular VMs**

Add Azure DevTestLab schedule to VMs created via CLI:

```bash
az vm auto-shutdown \
  --resource-group OPENADAPT-AGENTS \
  --name waa-eval-vm \
  --time 0200 \
  --email your-email@example.com
```

This shuts down the VM daily at 2:00 AM (UTC).

**Solution 2: Use Azure ML Compute Instances instead**

Azure ML Compute Instances have built-in idle timeout (default 60 minutes).

**Modify `cli.py` to use Azure ML SDK**:
Instead of creating regular VMs, create Azure ML Compute Instances using the `AzureMLClient` class in `azure.py`.

**Solution 3: Add timeout to container health check**

Modify `vm-setup` bash script to:
1. Monitor container logs
2. Detect "waiting for response" loop
3. Kill container if stuck for >15 minutes
4. Shutdown VM after container failure

**Implementation** (add to `cli.py` vm-setup script):
```bash
# Wait for container startup with timeout
TIMEOUT=900  # 15 minutes
START_TIME=$(date +%s)
while true; do
    # Check if server responds
    if curl -s http://localhost:5000/probe > /dev/null; then
        echo "✓ WAA server is ready"
        break
    fi

    # Check timeout
    ELAPSED=$(($(date +%s) - START_TIME))
    if [ $ELAPSED -gt $TIMEOUT ]; then
        echo "ERROR: Container startup timeout (15 min)"
        echo "Stopping container and shutting down VM"
        docker stop winarena
        sudo shutdown -h now
        exit 1
    fi

    sleep 30
done
```

**Solution 4: Document manual shutdown in README**

Add prominent warning:
```markdown
⚠️ **IMPORTANT**: Azure VMs do NOT auto-shutdown. Always manually stop VMs when done:

\`\`\`bash
az vm deallocate --resource-group OPENADAPT-AGENTS --name waa-eval-vm
\`\`\`

Or use the CLI:
\`\`\`bash
uv run python -m openadapt_evals.benchmarks.cli vm-stop
\`\`\`
```

---

## 9. Comparison: Azure ML Compute Instance vs Regular VM

| Feature | Azure ML Compute Instance | Regular Azure VM |
|---------|---------------------------|------------------|
| Auto-shutdown | ✅ Yes (idle_timeout_minutes) | ❌ No (must configure manually) |
| Created via | `AzureMLClient.create_compute_instance()` | `az vm create` or Azure Portal |
| Workspace required | ✅ Yes | ❌ No |
| This VM (`waa-eval-vm`) | ❌ No | ✅ Yes |
| Auto-shutdown configured | ❌ No | ❌ No |

**Key Finding**: The code in `azure.py` is designed for Azure ML evaluations with auto-shutdown. However, `waa-eval-vm` was created as a regular VM outside of this system, so it lacks auto-shutdown.

---

## 10. Summary

### What's Happening
- VM is running but idle
- Container is stuck waiting for Windows ISO (error state)
- WAA server will never respond in current state
- No active evaluation or useful work happening
- Costing $0.20/hour for nothing

### Why Auto-Shutdown Didn't Trigger
- This is a regular Azure VM, not an Azure ML Compute Instance
- Regular VMs have no auto-shutdown by default
- The `idle_timeout_minutes` config in `azure.py` only applies to Azure ML Compute Instances
- Auto-shutdown is a **missing feature** for regular VMs

### Why Dashboard Shows No Activity
- Dashboard is working correctly
- VM genuinely has no active tasks
- `benchmark_live.json` is from a previous completed run
- Current container is stuck and not running any evaluation

### What to Do RIGHT NOW
```bash
# Stop the VM immediately
az vm deallocate --resource-group OPENADAPT-AGENTS --name waa-eval-vm
```

### Next Steps
1. **Stop the VM** (immediate)
2. **Fix the ISO issue** before next use (see Option A/B above)
3. **Implement auto-shutdown** for regular VMs (long-term)
4. **Add timeout to container startup** to detect stuck states
5. **Document manual shutdown requirement** in README

---

## Appendix: Commands Used

```bash
# Check VM details
az vm show --name waa-eval-vm --resource-group OPENADAPT-AGENTS --show-details

# Check container status
az vm run-command invoke --resource-group OPENADAPT-AGENTS --name waa-eval-vm \
  --command-id RunShellScript --scripts "docker ps -a"

# Check container logs
az vm run-command invoke --resource-group OPENADAPT-AGENTS --name waa-eval-vm \
  --command-id RunShellScript --scripts "docker logs winarena --tail 50"

# Check WAA server
az vm run-command invoke --resource-group OPENADAPT-AGENTS --name waa-eval-vm \
  --command-id RunShellScript --scripts "curl -s http://localhost:5000/probe"

# Check auto-shutdown configuration
az resource list --resource-group OPENADAPT-AGENTS \
  --resource-type "Microsoft.DevTestLab/schedules" \
  --query "[?contains(name, 'waa-eval-vm')]"

# Stop VM (immediate action)
az vm deallocate --resource-group OPENADAPT-AGENTS --name waa-eval-vm
```

---

**Report Generated**: 2026-01-19 03:32 UTC
**Investigator**: Claude Code Agent
**Status**: Complete
