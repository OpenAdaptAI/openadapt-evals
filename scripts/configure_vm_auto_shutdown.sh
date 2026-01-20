#!/bin/bash
# Configure Azure VM Auto-Shutdown
#
# Sets up daily auto-shutdown at 6:00 PM Pacific Time (02:00 UTC)
# This is the immediate solution - shuts down daily to prevent waste
#
# For full start/stop scheduling (weekdays only), see docs/VM_AUTO_SHUTDOWN_SETUP.md

set -e

# Configuration
VM_NAME="${1:-waa-eval-vm}"
RESOURCE_GROUP="${2:-OPENADAPT-AGENTS}"
SHUTDOWN_TIME="0200"  # 6pm PT = 2am UTC (PST) or 1am UTC (PDT)
EMAIL="${3:-}"  # Optional email for notifications

echo "🔧 Configuring auto-shutdown for VM: $VM_NAME"
echo "   Resource Group: $RESOURCE_GROUP"
echo "   Shutdown Time: ${SHUTDOWN_TIME} UTC (6:00 PM Pacific)"
if [ -n "$EMAIL" ]; then
    echo "   Notification Email: $EMAIL"
fi
echo ""

# Check if VM exists
echo "📋 Verifying VM exists..."
if ! az vm show --name "$VM_NAME" --resource-group "$RESOURCE_GROUP" &> /dev/null; then
    echo "❌ ERROR: VM '$VM_NAME' not found in resource group '$RESOURCE_GROUP'"
    exit 1
fi
echo "✅ VM found"
echo ""

# Configure auto-shutdown
echo "⚙️  Configuring auto-shutdown..."
if [ -n "$EMAIL" ]; then
    az vm auto-shutdown \
        --resource-group "$RESOURCE_GROUP" \
        --name "$VM_NAME" \
        --time "$SHUTDOWN_TIME" \
        --email "$EMAIL"
else
    az vm auto-shutdown \
        --resource-group "$RESOURCE_GROUP" \
        --name "$VM_NAME" \
        --time "$SHUTDOWN_TIME"
fi

echo ""
echo "✅ Auto-shutdown configured successfully!"
echo ""
echo "📊 Configuration Summary:"
echo "   - VM will automatically shutdown at 02:00 UTC daily"
echo "   - This is 6:00 PM Pacific Time (PST/PDT aware)"
echo "   - VM will be DEALLOCATED (stops billing)"
echo "   - You can manually start VM anytime before shutdown"
echo ""
echo "💰 Expected Cost Savings:"
echo "   - Current: \$144/month (24/7 operation)"
echo "   - With 6pm shutdown: ~\$70/month (49% savings)"
echo "   - With full weekday schedule: ~\$35/month (76% savings)"
echo ""
echo "🔄 Manual Override:"
echo "   Start VM manually: az vm start -g $RESOURCE_GROUP -n $VM_NAME"
echo "   Stop VM manually:  az vm deallocate -g $RESOURCE_GROUP -n $VM_NAME"
echo ""
echo "⚠️  NOTE: This only configures shutdown, not auto-start."
echo "   For full weekday scheduling (9am start, 6pm stop, weekends off),"
echo "   see docs/VM_AUTO_SHUTDOWN_SETUP.md for Logic Apps setup."
echo ""
echo "📝 To disable auto-shutdown:"
echo "   az vm auto-shutdown -g $RESOURCE_GROUP -n $VM_NAME --off"
echo ""
