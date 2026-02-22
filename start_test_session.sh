#!/bin/bash
# Quick setup for manual sync testing
# Just verify the main repo build is working

set -e

PROJECT_ROOT="/Users/bensmith/development/sts_lightspeed"

echo "=== STS Manual Sync Testing Setup ==="
echo ""
echo "Checking main repo at: $PROJECT_ROOT"
cd "$PROJECT_ROOT"

# Check if build exists
if [ ! -f "build/slaythespire.cpython-314-darwin.so" ]; then
    echo "Build not found. Building..."
    cmake -B build -S . -DCMAKE_POLICY_VERSION_MINIMUM=3.5
    cmake --build build -j$(sysctl -n hw.ncpu)
else
    echo "Build found: build/slaythespire.cpython-314-darwin.so"
fi

# Verify Python module loads
echo ""
echo "Verifying Python module..."
cd build
python3 -c "import sys; sys.path.insert(0, '.'); import slaythespire; print('SUCCESS: Simulator module loaded!')"
cd ..

# Check CommunicationMod config
echo ""
echo "Checking CommunicationMod configuration..."
if [ -f "$HOME/Library/Preferences/ModTheSpire/CommunicationMod/config.properties" ]; then
    echo "CommunicationMod config found:"
    cat "$HOME/Library/Preferences/ModTheSpire/CommunicationMod/config.properties"
else
    echo "WARNING: CommunicationMod config not found!"
fi

# Check bridge state directory
echo ""
echo "Checking bridge state directory..."
if [ -d "/tmp/sts_bridge" ]; then
    echo "Bridge state directory exists: /tmp/sts_bridge"
    ls -la /tmp/sts_bridge/
else
    echo "Bridge state directory not found. Will be created when game starts."
fi

echo ""
echo "=== Ready for Testing ==="
echo ""
echo "To test, you need TWO terminals:"
echo ""
echo "TERMINAL 1 - Start the game:"
echo '    open "~/Library/Application Support/Steam/steamapps/common/SlayTheSpire/ModTheSpire.app"'
echo ""
echo "TERMINAL 2 - Start the sync tool:"
echo "    cd $PROJECT_ROOT"
echo "    python3 integration/manual_sync_play.py --seed 12345"
echo ""
echo "Then in the sync tool, type commands like:"
echo "    play 0        # Play first card"
echo "    end           # End turn"
echo "    choose 0      # Pick first option"
echo "    status        # Show state comparison"
echo ""
