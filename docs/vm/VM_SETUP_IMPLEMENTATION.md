# VM Setup Command Implementation

**Date**: January 18, 2026
**Status**: Complete and Ready for Testing

## Overview

Implemented the `vm-setup` CLI command to automate WAA container deployment on Azure VMs with 95%+ target reliability. This addresses the P0 priority from the WAA reliability analysis.

## What Was Implemented

### 1. Core Functionality (`cmd_vm_setup()`)

**File**: `/Users/abrichr/oa/src/openadapt-evals/openadapt_evals/benchmarks/cli.py` (lines 462-757)

**Features**:
- Multi-stage setup with 7 distinct phases
- Comprehensive health checks at each stage
- Idempotent (safe to re-run)
- Clear progress reporting
- Automatic retry logic for Docker daemon
- Windows boot detection via VNC port check
- WAA server verification
- Automatic verification option

**Stages**:
1. Validate nested virtualization support
2. Start Docker daemon (with 3 retry attempts)
3. Pull `windowsarena/winarena:latest` image
4. Create/start container with proper settings
5. Container health check
6. Windows boot detection (10 min timeout)
7. WAA server verification (5 min timeout)

**Implementation Details**:
- Uses `az vm run-command invoke` for remote execution
- 30-minute total timeout for setup script
- Checks for errors in output and returns proper exit codes
- Provides next steps and server URLs on success
- Optional auto-verification with 10 probe attempts

### 2. CLI Integration

**File**: `/Users/abrichr/oa/src/openadapt-evals/openadapt_evals/benchmarks/cli.py` (lines 1271-1279, 1355)

**Arguments**:
- `--vm-name` (default: `waa-eval-vm`)
- `--resource-group` (default: `OPENADAPT-AGENTS`)
- `--verify` - Run verification after setup
- `--auto-verify` - Automatically verify server is ready

**Usage**:
```bash
# Basic setup
uv run python -m openadapt_evals.benchmarks.cli vm-setup

# With auto-verification (recommended)
uv run python -m openadapt_evals.benchmarks.cli vm-setup --auto-verify

# Custom VM
uv run python -m openadapt_evals.benchmarks.cli vm-setup \
  --vm-name my-waa-vm \
  --resource-group MY-RG \
  --auto-verify
```

### 3. Test Script

**File**: `/Users/abrichr/oa/src/openadapt-evals/test_vm_setup.sh`

**Features**:
- Runs vm-setup with auto-verification
- Provides next steps on success
- Configurable via environment variables

**Usage**:
```bash
# Run with defaults
./test_vm_setup.sh

# Custom VM
VM_NAME=my-vm RESOURCE_GROUP=MY-RG ./test_vm_setup.sh
```

### 4. Documentation

**File**: `/Users/abrichr/oa/src/openadapt-evals/CLAUDE.md`

**Updates**:
- Added to Quick Start section
- Added to CLI Commands table
- New dedicated section "WAA Container Setup (vm-setup)" with:
  - What it does (7 stages)
  - Usage examples
  - Timeline expectations
  - Features list
  - Requirements
  - Troubleshooting guide
  - Test instructions

## Technical Specifications

### Container Configuration

```bash
docker run -d \
  --name winarena \
  --privileged \
  --device=/dev/kvm \
  -p 5000:5000 \    # WAA server
  -p 6080:6080 \    # VNC (noVNC)
  -p 3389:3389 \    # RDP
  -e RAM_SIZE=8G \
  -e CPU_CORES=4 \
  windowsarena/winarena:latest
```

### Health Check Strategy

1. **Nested Virtualization**: Check `/proc/cpuinfo` for `vmx` or `svm` flags
2. **Docker Daemon**: Retry up to 3 times with 5s delays
3. **Image Pull**: Check if image exists before pulling
4. **Container Status**: Verify `docker inspect` shows "running" status
5. **Windows Boot**: Poll VNC port (6080) inside container every 5s, max 10 min
6. **WAA Server**: Poll server port (5000) inside container every 5s, max 5 min
7. **External Verification**: Optional HTTP probe to `/probe` endpoint

### Error Handling

- Exit on first error in script (`set -e`)
- Clear error messages with context
- Logs container output on failure
- Returns non-zero exit codes for failures
- Provides troubleshooting commands in output

## Timeline

| Scenario | Expected Duration |
|----------|------------------|
| Fresh VM, first run | 15-20 minutes |
| Fresh VM, image cached | 5-10 minutes |
| Existing container, stopped | 2-5 minutes |
| Existing container, running | <1 minute (verification only) |

## Success Criteria

- [x] `vm-setup` command exists and is callable
- [x] Multi-stage health checks implemented
- [x] Idempotent (safe to re-run)
- [x] Clear error messages
- [x] Progress reporting every 30s
- [x] Automatic retry for Docker daemon
- [x] Windows boot detection
- [x] WAA server verification
- [x] Returns server URL on success
- [x] Test script created
- [x] Documentation updated
- [ ] **Tested on actual Azure VM** (pending)
- [ ] **95%+ success rate validated** (pending field testing)

## Next Steps

### 1. Test on Live VM

```bash
# Ensure VM is running
uv run python -m openadapt_evals.benchmarks.cli vm-start

# Run setup
./test_vm_setup.sh

# Expected: Success in 15-20 minutes
```

### 2. Validate Idempotency

```bash
# Run setup twice
./test_vm_setup.sh
./test_vm_setup.sh

# Expected: Second run completes in <1 minute
```

### 3. Test Error Recovery

```bash
# Stop Docker on VM
az vm run-command invoke \
  --resource-group OPENADAPT-AGENTS \
  --name waa-eval-vm \
  --command-id RunShellScript \
  --scripts "sudo systemctl stop docker"

# Run setup (should recover via retry)
./test_vm_setup.sh

# Expected: Docker starts successfully, setup completes
```

### 4. End-to-End Validation

```bash
# 1. Setup VM
uv run python -m openadapt_evals.benchmarks.cli vm-setup --auto-verify

# 2. Run evaluation
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-claude \
  --server http://$(az vm show --name waa-eval-vm --resource-group OPENADAPT-AGENTS --show-details --query publicIps -o tsv):5000 \
  --task-ids notepad_1

# Expected: Evaluation runs successfully
```

## Integration with Existing Commands

The `vm-setup` command complements existing VM management commands:

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `vm-setup` | Full automated setup from scratch | First-time VM setup, container recreation |
| `vm-start` | Start Azure VM only | VM is stopped but container exists |
| `server-start` | Start existing container | Container stopped but VM running |
| `up` | Start VM + container | Quick restart after VM stop |
| `probe` | Check if server is ready | Verify setup completion |

## Known Limitations

1. **Requires nested virtualization**: VM must be Standard_D4s_v5 or similar
2. **Network dependency**: Image pull requires internet access
3. **Timeout constraints**: 10 min Windows boot + 5 min server start
4. **No parallel execution**: Single-threaded setup process
5. **Azure CLI required**: Must have `az` command available

## Future Enhancements

Potential improvements for future iterations:

1. **Parallel health checks**: Check VNC and server ports simultaneously
2. **Image pre-warming**: Option to pull image without container creation
3. **Snapshot support**: Save VM state after successful setup
4. **Metrics collection**: Track setup time, failure rates, stage durations
5. **Cloud-init integration**: VM setup via cloud-init for faster deployment
6. **Terraform support**: Infrastructure-as-code for VM + container

## Files Modified/Created

### Modified
- `/Users/abrichr/oa/src/openadapt-evals/openadapt_evals/benchmarks/cli.py`
  - Added `cmd_vm_setup()` function (295 lines)
  - Added parser configuration (9 lines)
  - Added handler dispatch (1 line)

- `/Users/abrichr/oa/src/openadapt-evals/CLAUDE.md`
  - Updated Quick Start section
  - Updated CLI Commands table
  - Added "WAA Container Setup (vm-setup)" section (76 lines)

### Created
- `/Users/abrichr/oa/src/openadapt-evals/test_vm_setup.sh`
  - Test script with environment variable support
  - Provides next steps on success

- `/Users/abrichr/oa/src/openadapt-evals/VM_SETUP_IMPLEMENTATION.md`
  - This documentation file

## References

- P00 Reliability Analysis: `/private/tmp/claude/-Users-abrichr-oa-src/tasks/a2cac93.output`
- WAA Integration Fixes: `/Users/abrichr/oa/src/openadapt-evals/WAA_INTEGRATION_FIXES.md`
- WAA Baseline Plan: `/Users/abrichr/oa/src/openadapt-evals/WAA_BASELINE_VALIDATION_PLAN.md`
- Existing CLI: `/Users/abrichr/oa/src/openadapt-evals/openadapt_evals/benchmarks/cli.py`

## Validation Checklist

Before considering this P0 complete:

- [x] Implementation complete
- [x] Syntax validated
- [x] Help text displays correctly
- [x] Test script created
- [x] Documentation updated
- [ ] Tested on fresh VM
- [ ] Tested on existing setup (idempotency)
- [ ] Tested error recovery
- [ ] End-to-end evaluation works
- [ ] 95%+ success rate achieved

**Status**: Ready for field testing on Azure VM.
