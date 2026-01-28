"""Infrastructure components for VM management and monitoring.

This module provides:
- VMMonitor: Azure VM status monitoring
- AzureOpsTracker: Azure operation logging
- SSHTunnelManager: SSH tunnel management for VNC/API access

Example:
    ```python
    from openadapt_evals.infrastructure import VMMonitor, SSHTunnelManager

    # Monitor VM status
    monitor = VMMonitor()
    status = monitor.get_status()

    # Manage SSH tunnels
    tunnel_manager = SSHTunnelManager()
    tunnel_manager.start_tunnels_for_vm("172.171.112.41", "azureuser")
    ```
"""

from openadapt_evals.infrastructure.vm_monitor import VMMonitor, VMConfig
from openadapt_evals.infrastructure.azure_ops_tracker import AzureOpsTracker
from openadapt_evals.infrastructure.ssh_tunnel import SSHTunnelManager, get_tunnel_manager

__all__ = [
    "VMMonitor",
    "VMConfig",
    "AzureOpsTracker",
    "SSHTunnelManager",
    "get_tunnel_manager",
]
