#!/bin/bash
# Setup script for CommunicationMod integration

BRIDGE_SCRIPT="$(cd "$(dirname "$0")" && pwd)/harness/communication_bridge.py"
STATE_DIR="/tmp/sts_bridge"
CONFIG_FILE="$HOME/Library/Preferences/ModTheSpire/CommunicationMod/config.properties"

echo "=== CommunicationMod Setup for sts_lightspeed Testing ==="
echo ""

# Check if CommunicationMod config exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: CommunicationMod config not found at:"
    echo "  $CONFIG_FILE"
    echo ""
    echo "Please install CommunicationMod first:"
    echo "  https://github.com/ForgottenArbiter/CommunicationMod"
    exit 1
fi

echo "Current config:"
cat "$CONFIG_FILE"
echo ""

# Create backup
cp "$CONFIG_FILE" "$CONFIG_FILE.backup"
echo "Backup created at: $CONFIG_FILE.backup"

# Update config
echo "command=python $BRIDGE_SCRIPT --state-dir $STATE_DIR" > "$CONFIG_FILE"
echo "runAtGameStart=true" >> "$CONFIG_FILE"

echo ""
echo "Updated config:"
cat "$CONFIG_FILE"
echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "1. Launch Slay the Spire through ModTheSpire"
echo "2. The bridge will start automatically"
echo "3. Run: python tests/integration/run_tests.py --quick --character IRONCLAD"
echo ""
echo "To restore original config: cp $CONFIG_FILE.backup $CONFIG_FILE"
