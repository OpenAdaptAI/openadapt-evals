# Windows Container Setup Status Report

**Date**: 2026-01-18
**VM**: `waa-eval-vm` (Resource Group: `OPENADAPT-AGENTS`)
**Container**: `winarena`
**Status**: INTERRUPTED - VM Deallocated

---

## Current Status Assessment

### VM State
- **Power State**: VM deallocated (stopped)
- **Impact**: Container download was interrupted when VM was shut down
- **Location**: westus2
- **Size**: Standard_D4ds_v5 (4 vCPUs, 16 GB RAM)
- **OS**: Linux

### Container State
- **Status**: Unknown - cannot check while VM is deallocated
- **Last Known State**: Windows 11 ISO download in progress (5.7 GB)
- **Download Duration**: 2+ hours before interruption
- **Expected**: Download progress was lost when VM stopped

### Critical Finding
The VM was deallocated, which means:
1. The container was forcibly stopped
2. Any download progress may have been lost
3. Container needs to be restarted from scratch (or resume if download tool supports it)
4. VM incurs no compute charges while deallocated (storage charges only)

---

## Root Cause Analysis

### Why Download Takes So Long
1. **File Size**: 5.7 GB Windows 11 ISO
2. **Network Path**: Microsoft servers → Azure westus2 datacenter → VM → Container
3. **Bandwidth Limiting**: Microsoft may rate-limit ISO downloads
4. **Container Overhead**: Download happening inside Docker container adds layers

### Why VM Was Deallocated
- Likely stopped to save costs (deallocated VMs don't incur compute charges)
- Automatic shutdown policy (check if configured)
- Manual intervention to stop charges while waiting

---

## Action Plan

### Option A: Resume Current Approach (Recommended if cost is manageable)

**Pros**:
- Simplest approach
- Already configured
- May resume download if container supports it

**Cons**:
- VM compute charges while waiting (est. $0.20-0.30/hour)
- 4-6 hour wait time for download
- Risk of interruption again

**Steps**:
```bash
# 1. Start the VM
az vm start --resource-group OPENADAPT-AGENTS --name waa-eval-vm

# 2. Wait for VM to boot (2-3 minutes)
az vm wait --resource-group OPENADAPT-AGENTS --name waa-eval-vm --created

# 3. Check container status
az vm run-command invoke \
  --resource-group OPENADAPT-AGENTS \
  --name waa-eval-vm \
  --command-id RunShellScript \
  --scripts "docker ps -a"

# 4. Check if winarena container exists
az vm run-command invoke \
  --resource-group OPENADAPT-AGENTS \
  --name waa-eval-vm \
  --command-id RunShellScript \
  --scripts "docker logs winarena --tail 100"

# 5a. If container stopped, restart it
az vm run-command invoke \
  --resource-group OPENADAPT-AGENTS \
  --name waa-eval-vm \
  --command-id RunShellScript \
  --scripts "docker start winarena"

# 5b. If container doesn't exist, recreate it
az vm run-command invoke \
  --resource-group OPENADAPT-AGENTS \
  --name waa-eval-vm \
  --command-id RunShellScript \
  --scripts "docker run -d --name winarena -p 5000:5000 --shm-size=8g your-winarena-image"

# 6. Monitor download progress
az vm run-command invoke \
  --resource-group OPENADAPT-AGENTS \
  --name waa-eval-vm \
  --command-id RunShellScript \
  --scripts "docker logs winarena --tail 20 -f"

# 7. Set up auto-shutdown to prevent overnight charges (optional)
az vm auto-shutdown --resource-group OPENADAPT-AGENTS --name waa-eval-vm --time 2200
```

**Timeline**:
- VM startup: 2-3 minutes
- Container restart: 1-2 minutes
- ISO download: 4-6 hours (if starting fresh)
- Setup completion: 30 minutes
- **Total**: 5-7 hours

**Cost**:
- Standard_D4ds_v5 in westus2: ~$0.232/hour
- 7 hours: ~$1.62
- Plus storage costs (minimal)

---

### Option B: Pre-Download ISO (Fastest, Most Reliable)

**Pros**:
- Bypass slow download entirely
- More reliable (no download interruptions)
- Faster overall setup (1-2 hours total)
- Can verify ISO integrity before using

**Cons**:
- Requires additional setup steps
- Need Azure Storage account
- More complex initial configuration

**Steps**:
```bash
# 1. Create storage account (if not exists)
az storage account create \
  --name openadaptimages \
  --resource-group OPENADAPT-AGENTS \
  --location westus2 \
  --sku Standard_LRS

# 2. Create container for ISOs
az storage container create \
  --name windows-isos \
  --account-name openadaptimages

# 3. Download ISO locally (or on a fast connection)
# Option 3a: From your local machine
curl -L -o Win11_English_x64.iso "https://software-download.microsoft.com/..."

# Option 3b: Or download directly to Azure (faster)
# Use Azure Cloud Shell or a temporary VM with fast connection

# 4. Upload to Azure Storage
az storage blob upload \
  --account-name openadaptimages \
  --container-name windows-isos \
  --name Win11_English_x64.iso \
  --file Win11_English_x64.iso \
  --max-connections 8

# 5. Generate SAS URL (valid for 30 days)
az storage blob generate-sas \
  --account-name openadaptimages \
  --container-name windows-isos \
  --name Win11_English_x64.iso \
  --permissions r \
  --expiry $(date -u -d "30 days" '+%Y-%m-%dT%H:%MZ') \
  --https-only \
  --full-uri

# 6. Start VM and mount storage
az vm start --resource-group OPENADAPT-AGENTS --name waa-eval-vm

# 7. Download ISO from Azure Storage to VM (very fast - same datacenter)
az vm run-command invoke \
  --resource-group OPENADAPT-AGENTS \
  --name waa-eval-vm \
  --command-id RunShellScript \
  --scripts "curl -L -o /tmp/Win11.iso '<SAS_URL>'"

# 8. Mount ISO to container or copy to container volume
az vm run-command invoke \
  --resource-group OPENADAPT-AGENTS \
  --name waa-eval-vm \
  --command-id RunShellScript \
  --scripts "docker run -d --name winarena -p 5000:5000 -v /tmp/Win11.iso:/app/Win11.iso --shm-size=8g your-winarena-image"
```

**Timeline**:
- Storage setup: 10 minutes
- ISO download to Azure: 20-40 minutes (depends on your connection)
- ISO transfer Azure→VM: 5-10 minutes (fast, same datacenter)
- Container setup: 20 minutes
- **Total**: 1-2 hours

**Cost**:
- Storage: ~$0.02/GB/month = ~$0.12/month for 5.7GB
- Egress: None (same region)
- VM time: ~1 hour = ~$0.23
- **Total**: ~$0.35 (vs $1.62 for Option A)

---

### Option C: Use Pre-Built Windows Container Image

**Pros**:
- Fastest option (minutes, not hours)
- No ISO download needed
- More reproducible
- Can version control

**Cons**:
- Need to find/build appropriate image
- May require Docker Hub or Azure Container Registry
- Initial build takes time (but only once)

**Steps**:
```bash
# 1. Search for pre-built Windows container images
# Check Docker Hub: mcr.microsoft.com/windows/servercore
# Or build custom image with ISO pre-installed

# 2. If building custom:
# Create Dockerfile with pre-downloaded ISO
# Build on VM or locally
# Push to Azure Container Registry

# 3. Pull and run
az vm start --resource-group OPENADAPT-AGENTS --name waa-eval-vm
az vm run-command invoke \
  --resource-group OPENADAPT-AGENTS \
  --name waa-eval-vm \
  --command-id RunShellScript \
  --scripts "docker pull your-registry/winarena-prebuilt:latest && docker run -d --name winarena -p 5000:5000 --shm-size=8g your-registry/winarena-prebuilt:latest"
```

**Timeline**:
- Image pull: 10-20 minutes
- Container start: 2-5 minutes
- **Total**: 15-30 minutes

---

## Recommended Approach

**For Immediate Next Session**: **Option A** (Resume current approach)
- Simplest to execute
- Already partially configured
- Good for testing if process works end-to-end

**For Long-Term/Production**: **Option B** (Pre-download ISO)
- More reliable
- Better cost efficiency
- Reusable for future setups
- Recommended if you'll be setting up multiple instances

**For Scale**: **Option C** (Pre-built image)
- Best for repeated deployments
- Fastest startup time
- Professional approach

---

## Next Session Checklist

### Phase 1: Assess Current State (5 minutes)
- [ ] Start VM: `az vm start --resource-group OPENADAPT-AGENTS --name waa-eval-vm`
- [ ] Wait for VM ready: `az vm wait --created ...`
- [ ] Check container status: `docker ps -a | grep winarena`
- [ ] Check container logs: `docker logs winarena --tail 100`
- [ ] Determine: Does container exist? Is it running? What state is download in?

### Phase 2: Resume/Restart Container (10 minutes)
- [ ] If container exists and stopped: `docker start winarena`
- [ ] If container doesn't exist: Retrieve original `docker run` command and re-execute
- [ ] Verify container running: `docker ps | grep winarena`
- [ ] Check initial logs: `docker logs winarena -f` (monitor for 5 minutes)

### Phase 3: Monitor Progress (4-6 hours or overnight)
- [ ] Set up periodic log checking (every 30 minutes):
  ```bash
  # Create monitoring script
  while true; do
    echo "=== $(date) ==="
    az vm run-command invoke --resource-group OPENADAPT-AGENTS --name waa-eval-vm --command-id RunShellScript --scripts "docker logs winarena --tail 10"
    sleep 1800  # 30 minutes
  done
  ```
- [ ] Watch for completion message in logs
- [ ] Consider: Run overnight, check in morning

### Phase 4: Verify Completion (15 minutes)
- [ ] Check WAA server responds: `curl http://<VM-IP>:5000/health`
- [ ] Run probe command:
  ```bash
  az vm run-command invoke \
    --resource-group OPENADAPT-AGENTS \
    --name waa-eval-vm \
    --command-id RunShellScript \
    --scripts "docker exec winarena curl -X POST http://localhost:5000/probe"
  ```
- [ ] Verify Windows environment accessible
- [ ] Test basic WAA operations

### Phase 5: Document & Optimize (30 minutes)
- [ ] Document successful configuration
- [ ] Export container config: `docker inspect winarena > winarena-config.json`
- [ ] Create container image for reuse: `docker commit winarena winarena-ready:v1`
- [ ] (Optional) Push to Azure Container Registry
- [ ] Set up auto-shutdown to prevent runaway costs:
  ```bash
  az vm auto-shutdown --resource-group OPENADAPT-AGENTS --name waa-eval-vm --time 2200
  ```
- [ ] Update this document with results

---

## Success Criteria

### Container Ready
- [ ] Container status: Running
- [ ] WAA server responds on port 5000
- [ ] Health check returns success
- [ ] Can create Windows environment instance
- [ ] Can execute basic Windows commands

### System Stable
- [ ] Container runs for 1+ hour without crashes
- [ ] Memory usage stable (< 12 GB)
- [ ] No error messages in logs
- [ ] Response times acceptable (< 5 seconds for basic operations)

### Documentation Complete
- [ ] Setup steps documented
- [ ] Configuration files saved
- [ ] Troubleshooting guide created
- [ ] Reusable image/process established

---

## Timeline Estimates

### Scenario 1: Download Resumes Successfully
- Start VM: 3 minutes
- Resume container: 2 minutes
- Download completes: 2-4 hours (assuming 50% complete)
- Setup finishes: 30 minutes
- **Total**: 3-5 hours

### Scenario 2: Download Restarts from Beginning
- Start VM: 3 minutes
- Restart container: 5 minutes
- Full download: 4-6 hours
- Setup finishes: 30 minutes
- **Total**: 5-7 hours

### Scenario 3: Switch to Pre-Download Approach
- Upload ISO to Azure Storage: 30 minutes
- Start VM: 3 minutes
- Download from Storage: 10 minutes
- Configure container: 20 minutes
- **Total**: 1 hour

---

## Troubleshooting Guide

### Issue: Container Won't Start
**Symptoms**: `docker start winarena` fails
**Diagnosis**:
```bash
docker logs winarena
docker inspect winarena | grep -A 10 State
```
**Solutions**:
1. Check if port 5000 is already in use: `netstat -tlnp | grep 5000`
2. Remove and recreate container: `docker rm winarena && docker run ...`
3. Check disk space: `df -h`
4. Check memory: `free -h`

### Issue: Download Extremely Slow
**Symptoms**: Less than 1 Mbps download speed
**Diagnosis**:
```bash
# Inside container or VM
curl -o /dev/null https://software-download.microsoft.com/... -w "%{speed_download}\n"
```
**Solutions**:
1. Switch to Option B (pre-download)
2. Try different time of day (less Microsoft traffic)
3. Check Azure VM network throttling
4. Verify no bandwidth limits on VM size

### Issue: Download Hangs/Stalls
**Symptoms**: No progress for 30+ minutes
**Diagnosis**:
```bash
docker logs winarena --tail 50
docker exec winarena ps aux  # Check if download process running
```
**Solutions**:
1. Restart container: `docker restart winarena`
2. Check network connectivity: `docker exec winarena ping -c 5 google.com`
3. Try download with resume capability: `wget -c` or `curl -C -`

### Issue: Container Uses Too Much Memory
**Symptoms**: VM becomes unresponsive, OOM errors
**Diagnosis**:
```bash
docker stats winarena --no-stream
free -h
dmesg | grep -i oom
```
**Solutions**:
1. Increase VM size to D8ds_v5 (8 vCPUs, 32 GB RAM)
2. Reduce container shared memory: `--shm-size=4g`
3. Add memory limits: `--memory=12g --memory-swap=14g`

### Issue: ISO Download Completes but Container Fails
**Symptoms**: Download finishes, but container exits or errors
**Diagnosis**:
```bash
docker logs winarena --tail 200
docker exec winarena ls -lh /path/to/iso  # Verify ISO exists and size correct
docker exec winarena file /path/to/iso    # Verify ISO file type
```
**Solutions**:
1. Verify ISO integrity: `md5sum` or `sha256sum`
2. Check if ISO mounted correctly
3. Review container startup scripts for errors
4. Check container has enough disk space

---

## Cost Management

### Current Costs (Standard_D4ds_v5 in westus2)
- **Running**: ~$0.232/hour = $5.57/day
- **Deallocated**: $0/hour (only storage charges)
- **Storage**: ~$0.05/GB/month

### Cost Optimization Strategies
1. **Auto-Shutdown**: Configure VM to stop at night
   ```bash
   az vm auto-shutdown --resource-group OPENADAPT-AGENTS --name waa-eval-vm --time 2200 --timezone "Pacific Standard Time"
   ```

2. **Right-Size VM**: After setup, consider if D4ds_v5 is needed
   - For development: D2ds_v5 (2 vCPUs, 8 GB) = ~$0.116/hour
   - For production: Keep D4ds_v5 or upgrade to D8ds_v5

3. **Use Reserved Instances**: If running 24/7, save 72% with 3-year reservation

4. **Deallocate When Not Needed**:
   ```bash
   az vm deallocate --resource-group OPENADAPT-AGENTS --name waa-eval-vm
   ```

5. **Delete When Done**: If this is temporary testing
   ```bash
   az vm delete --resource-group OPENADAPT-AGENTS --name waa-eval-vm --yes
   ```

---

## Additional Resources

### Azure VM Management
- Start VM: `az vm start --resource-group OPENADAPT-AGENTS --name waa-eval-vm`
- Stop VM (keep IP): `az vm stop --resource-group OPENADAPT-AGENTS --name waa-eval-vm`
- Deallocate VM (release IP, no charges): `az vm deallocate --resource-group OPENADAPT-AGENTS --name waa-eval-vm`
- Get VM IP: `az vm show --resource-group OPENADAPT-AGENTS --name waa-eval-vm --show-details --query publicIps -o tsv`

### Docker Container Management
```bash
# Run commands on VM
az vm run-command invoke \
  --resource-group OPENADAPT-AGENTS \
  --name waa-eval-vm \
  --command-id RunShellScript \
  --scripts "YOUR_COMMAND_HERE"

# Common commands:
docker ps -a                           # List all containers
docker logs winarena                   # View logs
docker logs winarena -f                # Follow logs
docker stats winarena                  # Resource usage
docker exec winarena COMMAND           # Run command in container
docker inspect winarena                # Full container config
docker restart winarena                # Restart container
docker stop winarena                   # Stop container
docker start winarena                  # Start container
docker rm winarena                     # Remove container
```

### Monitoring & Debugging
```bash
# Check VM metrics
az monitor metrics list --resource <VM-RESOURCE-ID> --metric "Percentage CPU"

# SSH to VM (if configured)
ssh azureuser@<VM-PUBLIC-IP>

# View Azure Activity Log
az monitor activity-log list --resource-group OPENADAPT-AGENTS --max-events 50
```

---

## Recommendations Summary

### Immediate Next Steps (Next Session)
1. Start the VM
2. Check container state
3. Resume or restart winarena container
4. Monitor for 30 minutes to assess progress
5. If download is slow/stalled, switch to Option B (pre-download)

### Long-Term Improvements
1. Create pre-built container image with ISO included
2. Set up Azure Container Registry for image storage
3. Implement auto-shutdown to control costs
4. Document the working configuration for repeatability
5. Consider Azure Spot VMs for 60-90% cost savings (if workload tolerates interruptions)

### Questions to Resolve
1. What is the original `docker run` command used to create winarena?
2. Is there a specific Windows 11 ISO URL being used?
3. What is the expected behavior after ISO download completes?
4. Is this a one-time setup or will it be repeated?
5. What are the budget constraints for VM runtime?

---

**Status**: READY FOR NEXT SESSION
**Recommended Action**: Option A (Resume), fallback to Option B if issues
**Estimated Time to Completion**: 3-7 hours (or 1 hour with Option B)
**Priority**: Medium (blocked on download completion)
