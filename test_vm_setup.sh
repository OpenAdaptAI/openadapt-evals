#!/bin/bash
# Test vm-setup command
# This script tests the vm-setup command with verification

set -e

echo "============================================"
echo "Testing vm-setup command"
echo "============================================"
echo ""

# Default values
VM_NAME="${VM_NAME:-waa-eval-vm}"
RESOURCE_GROUP="${RESOURCE_GROUP:-OPENADAPT-AGENTS}"

echo "Configuration:"
echo "  VM Name: $VM_NAME"
echo "  Resource Group: $RESOURCE_GROUP"
echo ""

# Test 1: Run vm-setup with verification
echo "Test 1: Running vm-setup with auto-verification..."
echo "--------------------------------------------"
if uv run python -m openadapt_evals.benchmarks.cli vm-setup \
    --vm-name "$VM_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --auto-verify; then
    echo "✓ vm-setup completed successfully"
else
    echo "✗ vm-setup failed"
    exit 1
fi

echo ""
echo "============================================"
echo "All tests passed!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Check server status:"
echo "     uv run python -m openadapt_evals.benchmarks.cli vm-status"
echo ""
echo "  2. Run a test evaluation:"
echo "     uv run python -m openadapt_evals.benchmarks.cli live \\"
echo "       --agent api-claude \\"
echo "       --server http://\$(az vm show --name $VM_NAME --resource-group $RESOURCE_GROUP --show-details --query publicIps -o tsv):5000 \\"
echo "       --task-ids notepad_1"
