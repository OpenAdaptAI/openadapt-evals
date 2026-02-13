"""Infrastructure components for VM management and monitoring.

This module provides:
- AzureVMManager: Azure VM lifecycle management (SDK + CLI fallback)
- PoolManager: Multi-VM pool orchestration
- VMMonitor: Azure VM status monitoring
- AzureOpsTracker: Azure operation logging
- SSHTunnelManager: SSH tunnel management for VNC/API access

Example:
    ```python
    from openadapt_evals.infrastructure import AzureVMManager, PoolManager

    # Manage VMs
    vm = AzureVMManager()
    ip = vm.get_vm_ip("waa-eval-vm")

    # Create and manage pools
    pool = PoolManager()
    pool.create(workers=3)
    ```
"""

from openadapt_evals.infrastructure.azure_ops_tracker import AzureOpsTracker
from openadapt_evals.infrastructure.azure_vm import AzureVMManager
from openadapt_evals.infrastructure.pool import PoolManager, PoolRunResult
from openadapt_evals.infrastructure.ssh_tunnel import SSHTunnelManager, get_tunnel_manager
from openadapt_evals.infrastructure.vm_monitor import VMMonitor, VMConfig

__all__ = [
    "AzureOpsTracker",
    "AzureVMManager",
    "PoolManager",
    "PoolRunResult",
    "VMMonitor",
    "VMConfig",
    "SSHTunnelManager",
    "get_tunnel_manager",
]
