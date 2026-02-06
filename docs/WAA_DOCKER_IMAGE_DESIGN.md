# WAA Custom Docker Image Design

## Problem

The vanilla `windowsarena/winarena:latest` image does NOT work for unattended WAA evaluation because:

1. **Outdated base**: Uses old dockurr/windows that doesn't auto-download Windows
2. **No FirstLogonCommands**: Missing patches to autounattend.xml that:
   - Run `install.bat` (installs Python, Chrome, dependencies)
   - Create scheduled task for WAA server auto-start
   - Start WAA server on first boot
3. **Manual intervention required**: Without these patches, user must manually click through Windows setup

Our custom `waa-auto` Dockerfile (in `openadapt_ml/benchmarks/waa_deploy/Dockerfile`) solves these issues.

## Current State

- Custom Dockerfile exists at: `openadapt-ml/openadapt_ml/benchmarks/waa_deploy/Dockerfile`
- Building requires manual Docker commands
- No automated push to registry
- Azure parallelization defaults to vanilla image (broken)

## Requirements

1. **Easy CLI**: Single command to build and push custom image
2. **Registry support**: Push to Docker Hub or Azure Container Registry (ACR)
3. **Azure integration**: Parallelization should auto-use custom image
4. **Idempotent**: Skip build if image already exists with same hash

## Proposed CLI Commands

```bash
# Build custom WAA image locally
uv run python -m openadapt_evals.benchmarks.cli waa-image build

# Push to Docker Hub (requires DOCKER_USERNAME, DOCKER_PASSWORD or login)
uv run python -m openadapt_evals.benchmarks.cli waa-image push --registry dockerhub

# Push to Azure Container Registry (uses azure-setup credentials)
uv run python -m openadapt_evals.benchmarks.cli waa-image push --registry acr

# Build and push in one command
uv run python -m openadapt_evals.benchmarks.cli waa-image build-push --registry acr

# Check if custom image exists in registry
uv run python -m openadapt_evals.benchmarks.cli waa-image check
```

## Implementation

### 1. Copy Dockerfile to openadapt-evals

The Dockerfile and supporting files should live in openadapt-evals (the benchmark package), not openadapt-ml:

```
openadapt_evals/
  benchmarks/
    waa_deploy/
      Dockerfile           # Custom WAA image
      start_waa_server.bat # WAA server startup script
```

### 2. CLI Command: `waa-image`

```python
def cmd_waa_image(args):
    action = args.action  # build, push, build-push, check
    registry = args.registry  # dockerhub, acr

    if action in ("build", "build-push"):
        build_waa_image()

    if action in ("push", "build-push"):
        if registry == "dockerhub":
            push_to_dockerhub()
        elif registry == "acr":
            push_to_acr()

    if action == "check":
        check_image_exists(registry)
```

### 3. Build Function

```python
def build_waa_image(tag: str = "waa-auto:latest") -> bool:
    """Build custom WAA Docker image."""
    dockerfile_dir = Path(__file__).parent / "waa_deploy"

    # Check if Dockerfile exists
    if not (dockerfile_dir / "Dockerfile").exists():
        raise FileNotFoundError("Dockerfile not found in waa_deploy/")

    # Build image
    cmd = ["docker", "build", "-t", tag, str(dockerfile_dir)]
    subprocess.run(cmd, check=True)
    return True
```

### 4. Push Functions

```python
def push_to_dockerhub(tag: str, repo: str = "openadaptai/waa-auto"):
    """Push image to Docker Hub."""
    # Tag for Docker Hub
    full_tag = f"{repo}:{tag}"
    subprocess.run(["docker", "tag", f"waa-auto:{tag}", full_tag], check=True)
    subprocess.run(["docker", "push", full_tag], check=True)

def push_to_acr(tag: str):
    """Push image to Azure Container Registry."""
    # Get ACR name from config
    acr_name = os.getenv("AZURE_ACR_NAME", "openadaptacr")
    full_tag = f"{acr_name}.azurecr.io/waa-auto:{tag}"

    # Login to ACR
    subprocess.run(["az", "acr", "login", "--name", acr_name], check=True)

    # Tag and push
    subprocess.run(["docker", "tag", f"waa-auto:{tag}", full_tag], check=True)
    subprocess.run(["docker", "push", full_tag], check=True)
```

### 5. Update Azure Config

Update `azure.py` to use custom image by default:

```python
@dataclass
class AzureConfig:
    # Change default from vanilla to custom
    docker_image: str = "openadaptai/waa-auto:latest"  # Docker Hub
    # Or for ACR:
    # docker_image: str = "{acr_name}.azurecr.io/waa-auto:latest"
```

### 6. Auto-build on First Use

The `azure` command should check if custom image exists and prompt to build:

```python
def cmd_azure(args):
    # Check if custom image exists
    if not image_exists_in_registry():
        print("Custom WAA image not found. Building and pushing...")
        print("Run: uv run python -m openadapt_evals.benchmarks.cli waa-image build-push")
        return 1

    # Continue with Azure evaluation...
```

## Registry Options

### Option A: Docker Hub (Recommended for simplicity)
- Public registry, no Azure setup required
- Image: `openadaptai/waa-auto:latest`
- Requires Docker Hub account and `docker login`

### Option B: Azure Container Registry
- Private registry, integrated with Azure ML
- Faster pulls from Azure compute (same region)
- Requires ACR setup via `azure-setup` command
- Image: `{acr_name}.azurecr.io/waa-auto:latest`

## Current State (Updated 2026-01-29)

**waa_deploy/ ALREADY EXISTS in openadapt-evals:**
```
openadapt_evals/waa_deploy/
├── Dockerfile           # ✅ Complete custom Dockerfile
├── __init__.py          # ✅ Package init
├── api_agent.py         # ✅ API agent for Claude/GPT
└── start_waa_server.bat # ✅ Server startup script
```

The Dockerfile has all critical modifications:
- Uses `dockurr/windows:latest` as modern base (auto-downloads Windows)
- Patches autounattend.xml with FirstLogonCommands
- Runs install.bat, creates scheduled task for WAA server auto-start
- Copies Python 3.9 from vanilla (transformers 4.46.2 compatibility)
- Patches IP addresses (20.20.20.21 → 172.30.0.2)
- Includes api_agent.py for Claude/GPT-4o support

## Remaining Tasks

1. ~~Copy `waa_deploy/` from openadapt-ml to openadapt-evals~~ ✅ DONE
2. Add `waa-image` CLI command (build, push, check)
3. Update `azure.py` default docker_image to use custom image
4. Build and push custom image to Docker Hub
5. Test Azure parallelization with custom image

## Open Questions

1. **Versioning**: Should we tag images with version numbers (v1.0.0) or just use `latest`?
2. **CI/CD**: Should GitHub Actions auto-build on Dockerfile changes?
3. **Size optimization**: Image is ~25GB - can we reduce?

## Testing

```bash
# 1. Build locally
uv run python -m openadapt_evals.benchmarks.cli waa-image build

# 2. Test locally (requires VM with nested virt)
docker run -d --name test-waa \
  --device=/dev/kvm --cap-add NET_ADMIN \
  -p 8006:8006 -p 5000:5000 \
  -v /tmp/waa-storage:/storage \
  -e VERSION=11e \
  waa-auto:latest

# 3. Wait for Windows install, verify WAA server starts automatically

# 4. Push to registry
uv run python -m openadapt_evals.benchmarks.cli waa-image push --registry dockerhub

# 5. Test Azure parallelization
uv run python -m openadapt_evals.benchmarks.cli azure --workers 2 --task-ids notepad_1,notepad_2
```
