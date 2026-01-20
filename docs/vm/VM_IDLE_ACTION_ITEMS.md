# VM Idle Investigation - Action Items

**Investigation Date**: 2026-01-19 03:32 UTC
**Status**: IMMEDIATE ACTION REQUIRED

---

## IMMEDIATE ACTION (Do This RIGHT NOW)

### Stop the VM to Prevent Further Waste

**Cost**: Currently wasting $0.20/hour = $4.80/day

```bash
# Stop the VM immediately
az vm deallocate --resource-group OPENADAPT-AGENTS --name waa-eval-vm
```

**Verification**:
```bash
# Confirm VM is stopped
az vm show --name waa-eval-vm --resource-group OPENADAPT-AGENTS \
  --query "powerState" -o tsv
# Should show: "VM deallocated"
```

**Estimated Savings**: $4.80/day

---

## SHORT-TERM FIX (Next Session When You Need the VM)

### Problem: Container Stuck on "ISO file not found"

The container cannot boot Windows because the ISO file is missing or failed to download.

### Option A: Wait for ISO Download (Simplest)

The container may be downloading the Windows ISO in the background. This can take 30-60 minutes depending on network speed.

**Steps**:
1. Start the VM
2. Monitor container logs to watch for ISO download progress
3. Wait for Windows to boot (can take 20-30 min after ISO downloads)
4. Verify WAA server responds

**Commands**:
```bash
# 1. Start VM
az vm start --resource-group OPENADAPT-AGENTS --name waa-eval-vm

# 2. Monitor container logs (watch for ISO download progress)
az vm run-command invoke \
  --resource-group OPENADAPT-AGENTS \
  --name waa-eval-vm \
  --command-id RunShellScript \
  --scripts "docker logs winarena --tail 100"

# 3. Wait 30-60 minutes, then check if WAA server responds
az vm run-command invoke \
  --resource-group OPENADAPT-AGENTS \
  --name waa-eval-vm \
  --command-id RunShellScript \
  --scripts "curl -s http://localhost:5000/probe && echo 'Server is UP' || echo 'Server still not responding'"

# 4. If server responds, get public IP and test
az vm show --name waa-eval-vm --resource-group OPENADAPT-AGENTS \
  --show-details --query "publicIps" -o tsv

# Test from local machine
curl http://PUBLIC_IP:5000/probe
```

**Expected Timeline**:
- ISO download: 30-60 minutes (depends on network)
- Windows boot: 10-20 minutes
- WAA server startup: 2-5 minutes
- **Total**: 45-90 minutes

---

### Option B: Recreate Container from Scratch (If Option A Fails)

If the ISO issue persists or you don't want to wait, recreate the container.

**Steps**:
1. Start VM
2. Stop and remove existing container
3. Re-run `vm-setup` command to create fresh container
4. Monitor progress to ensure success

**Commands**:
```bash
# 1. Start VM
az vm start --resource-group OPENADAPT-AGENTS --name waa-eval-vm

# 2. Stop and remove broken container
az vm run-command invoke \
  --resource-group OPENADAPT-AGENTS \
  --name waa-eval-vm \
  --command-id RunShellScript \
  --scripts "docker stop winarena && docker rm winarena && echo 'Container removed'"

# 3. Re-run vm-setup to recreate container with health checks
uv run python -m openadapt_evals.benchmarks.cli vm-setup \
  --vm-name waa-eval-vm \
  --resource-group OPENADAPT-AGENTS \
  --auto-verify

# This will:
# - Validate nested virtualization
# - Start Docker daemon
# - Pull windowsarena/winarena:latest
# - Create and start container
# - Wait for Windows to boot
# - Verify WAA server responds
# - Return server URL when ready
```

**Expected Timeline**: 15-20 minutes (if image already downloaded), 30-40 minutes (fresh pull)

---

## LONG-TERM SOLUTION (Missing Feature - Auto-Shutdown)

### Problem: Regular Azure VMs Have No Auto-Shutdown by Default

The VM `waa-eval-vm` is a regular Azure VM (not Azure ML Compute Instance), so it runs indefinitely until manually stopped.

The `idle_timeout_minutes` configuration in `azure.py` only applies to Azure ML Compute Instances created via the `AzureWAAOrchestrator` class.

### Solution 1: Enable Azure Auto-Shutdown for Regular VMs

Add a daily shutdown schedule to the VM:

```bash
# Set VM to auto-shutdown daily at 2:00 AM UTC
az vm auto-shutdown \
  --resource-group OPENADAPT-AGENTS \
  --name waa-eval-vm \
  --time 0200 \
  --email your-email@example.com
```

**Benefits**:
- VM automatically stops every day at 2 AM UTC
- Email notification before shutdown (10 min warning)
- Prevents runaway costs from forgotten VMs

**Limitations**:
- Only shuts down at scheduled time (not idle-based)
- VM must be manually restarted each day
- Not suitable for long-running evaluations

---

### Solution 2: Implement Idle-Based Auto-Shutdown Script

Add a systemd service on the VM that monitors idle time and shuts down when idle.

**Implementation**:

Create `/etc/systemd/system/idle-shutdown.service`:
```ini
[Unit]
Description=Auto-shutdown when idle
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/idle-shutdown.sh
Restart=always

[Install]
WantedBy=multi-user.target
```

Create `/usr/local/bin/idle-shutdown.sh`:
```bash
#!/bin/bash
# Auto-shutdown VM after 60 minutes of idle time

IDLE_THRESHOLD=3600  # 60 minutes in seconds
CHECK_INTERVAL=300   # Check every 5 minutes

while true; do
    # Check if WAA server is responding
    if curl -sf http://localhost:5000/probe > /dev/null; then
        # Server is active, reset idle timer
        LAST_ACTIVE=$(date +%s)
    else
        # Server not responding, check idle time
        CURRENT_TIME=$(date +%s)
        IDLE_TIME=$((CURRENT_TIME - LAST_ACTIVE))

        if [ $IDLE_TIME -gt $IDLE_THRESHOLD ]; then
            echo "VM idle for $IDLE_TIME seconds, shutting down"
            sudo shutdown -h now
            exit 0
        fi
    fi

    sleep $CHECK_INTERVAL
done
```

**Deploy**:
```bash
# Copy script to VM
az vm run-command invoke \
  --resource-group OPENADAPT-AGENTS \
  --name waa-eval-vm \
  --command-id RunShellScript \
  --scripts "cat > /usr/local/bin/idle-shutdown.sh << 'EOF'
#!/bin/bash
[... paste script above ...]
EOF
chmod +x /usr/local/bin/idle-shutdown.sh"

# Create and enable systemd service
az vm run-command invoke \
  --resource-group OPENADAPT-AGENTS \
  --name waa-eval-vm \
  --command-id RunShellScript \
  --scripts "cat > /etc/systemd/system/idle-shutdown.service << 'EOF'
[... paste service file above ...]
EOF
systemctl daemon-reload
systemctl enable idle-shutdown
systemctl start idle-shutdown"
```

**Benefits**:
- True idle-based shutdown (not time-based)
- Configurable idle threshold
- Works for any VM usage pattern

**Limitations**:
- Requires manual deployment on each VM
- Needs maintenance if WAA server changes ports

---

### Solution 3: Add Timeout to Container Startup Health Check

Modify the `vm-setup` bash script in `cli.py` to detect stuck containers and auto-shutdown the VM.

**Changes to `/Users/abrichr/oa/src/openadapt-evals/openadapt_evals/benchmarks/cli.py`**:

In the `cmd_vm_setup()` function, after the container creation section (around line 598), add:

```bash
echo ""
echo "=== Stage 5: Wait for Windows to Boot (with timeout) ==="
TIMEOUT=900  # 15 minutes
START_TIME=$(date +%s)
CONSECUTIVE_WAITS=0

while true; do
    # Check if server responds
    if curl -s http://localhost:5000/probe > /dev/null; then
        echo "✓ WAA server is ready"
        break
    fi

    # Check for stuck state (repeated "Waiting for response" messages)
    RECENT_LOGS=$(docker logs winarena --tail 5)
    if echo "$RECENT_LOGS" | grep -q "Waiting for a response"; then
        CONSECUTIVE_WAITS=$((CONSECUTIVE_WAITS + 1))

        # If stuck for >10 consecutive checks (5 minutes), it's broken
        if [ $CONSECUTIVE_WAITS -gt 10 ]; then
            echo "ERROR: Container stuck in wait loop (5+ minutes)"
            echo "Likely issue: Windows ISO failed to download or is corrupted"
            echo "Stopping container and shutting down VM to prevent waste"
            docker stop winarena
            sudo shutdown -h +1  # Shutdown in 1 minute
            exit 1
        fi
    else
        CONSECUTIVE_WAITS=0  # Reset if not waiting
    fi

    # Check absolute timeout
    ELAPSED=$(($(date +%s) - START_TIME))
    if [ $ELAPSED -gt $TIMEOUT ]; then
        echo "ERROR: Container startup timeout (15 minutes)"
        echo "Container logs:"
        docker logs winarena --tail 20
        echo ""
        echo "Stopping container and shutting down VM"
        docker stop winarena
        sudo shutdown -h +1  # Shutdown in 1 minute
        exit 1
    fi

    echo "Waiting for WAA server... ($CONSECUTIVE_WAITS consecutive waits, ${ELAPSED}s elapsed)"
    sleep 30
done
```

**Benefits**:
- Detects stuck containers automatically
- Prevents wasted costs from broken setups
- Provides clear error messages

**Limitations**:
- Only applies to new `vm-setup` runs
- Doesn't help with already-running broken containers

---

### Solution 4: Use Azure ML Compute Instances Instead

Azure ML Compute Instances have built-in idle timeout (default 60 minutes).

**Changes Required**:
1. Create Azure ML workspace (if not already exists)
2. Modify CLI to use `AzureWAAOrchestrator` instead of raw `az vm` commands
3. Update documentation to recommend Azure ML for production use

**Example**:
```python
from openadapt_evals.benchmarks.azure import AzureConfig, AzureMLClient

config = AzureConfig.from_env()
client = AzureMLClient(config)

# Creates compute instance with auto-shutdown after 60 min idle
client.create_compute_instance(
    name="waa-eval-compute",
    vm_size="Standard_D4s_v5",
)
```

**Benefits**:
- Built-in idle timeout (no custom code needed)
- Azure manages lifecycle
- Better for parallel evaluations

**Limitations**:
- Requires Azure ML workspace setup
- More complex initial configuration
- Different cost model (compute instances may cost more)

---

### Solution 5: Add Prominent Documentation Warning

Update README and CLI help to warn users about manual shutdown requirement.

**Add to `/Users/abrichr/oa/src/openadapt-evals/README.md`**:

```markdown
## ⚠️ IMPORTANT: Manual VM Shutdown Required

**Regular Azure VMs do NOT auto-shutdown. You MUST manually stop VMs when done to avoid unnecessary costs.**

**After finishing work, ALWAYS run:**

\`\`\`bash
# Via Azure CLI
az vm deallocate --resource-group OPENADAPT-AGENTS --name waa-eval-vm

# Or via this project's CLI
uv run python -m openadapt_evals.benchmarks.cli vm-stop
\`\`\`

**Cost if left running**: $0.20/hour = $4.80/day = $144/month

**Recommended**: Set up auto-shutdown schedule (see VM Management section).
```

**Add to CLI help**:

In `cli.py`, update the `vm-start` and `up` command help text:

```python
@cli.command()
@click.option("--vm-name", default="waa-eval-vm")
@click.option("--resource-group", default="OPENADAPT-AGENTS")
def vm_start(vm_name: str, resource_group: str):
    """Start an Azure VM.

    ⚠️  WARNING: This VM will NOT auto-shutdown. You must manually stop it
    when done to avoid unnecessary costs ($0.20/hour = $4.80/day).

    Stop with: uv run python -m openadapt_evals.benchmarks.cli vm-stop
    """
    # ... implementation
```

---

## Recommended Approach

**For Immediate Use**:
1. ✅ **Stop VM now** (prevents further waste)
2. ✅ **Use Option B** when you need it next (recreate container fresh)
3. ✅ **Enable Azure auto-shutdown** (Solution 1 - daily 2 AM shutdown)

**For Long-Term Reliability**:
1. ✅ **Implement Solution 3** (add timeout to vm-setup script)
2. ✅ **Document manual shutdown requirement** (Solution 5)
3. ⚠️ **Consider Solution 4** (Azure ML Compute Instances) for production

**For Maximum Cost Optimization**:
1. ✅ **Solution 2** (idle-based auto-shutdown script)
2. ✅ **Solution 1** (daily auto-shutdown as fallback)
3. ✅ **Solution 5** (documentation warnings)

---

## Implementation Priority

| Priority | Solution | Effort | Impact | When to Implement |
|----------|----------|--------|--------|-------------------|
| P0 | Stop VM NOW | 1 min | High | Immediate |
| P0 | Enable daily auto-shutdown (Solution 1) | 5 min | High | Today |
| P1 | Add timeout to vm-setup (Solution 3) | 30 min | High | This week |
| P1 | Document manual shutdown (Solution 5) | 15 min | Medium | This week |
| P2 | Idle-based auto-shutdown (Solution 2) | 2 hours | Medium | Next sprint |
| P3 | Migrate to Azure ML (Solution 4) | 1 day | High | Future (if scale needed) |

---

## Next Session Checklist

**When you start VM again**:
- [ ] Start VM: `az vm start --resource-group OPENADAPT-AGENTS --name waa-eval-vm`
- [ ] Choose fix: Option A (wait for ISO) or Option B (recreate container)
- [ ] Monitor progress: Check logs every 10 minutes
- [ ] Verify server: `curl http://PUBLIC_IP:5000/probe`
- [ ] **Set reminder to stop VM when done**
- [ ] Stop VM: `az vm deallocate --resource-group OPENADAPT-AGENTS --name waa-eval-vm`

**To prevent this issue in the future**:
- [ ] Implement Solution 1 (daily auto-shutdown)
- [ ] Implement Solution 3 (timeout in vm-setup)
- [ ] Update README with shutdown warning (Solution 5)

---

**Generated**: 2026-01-19 03:32 UTC
