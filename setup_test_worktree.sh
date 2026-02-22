#!/bin/bash
# Setup script for manual sync testing worktree
# Run this from: cd /Users/bensmith/development/sts_lightspeed && ./setup_test_worktree.sh

set -e

PROJECT_ROOT="/Users/bensmith/development/sts_lightspeed"
WORKTREE_PATH="$PROJECT_ROOT/.worktrees/test-manual-sync"
BRANCH_NAME="test/manual-sync-verification"

echo "=== Setting up STS Manual Sync Testing Worktree ==="
echo ""

# Clean up any existing worktree
echo "1. Cleaning up any existing worktree..."
cd "$PROJECT_ROOT"
git worktree remove "$WORKTREE_PATH" --force 2>/dev/null || true
git branch -D "$BRANCH_NAME" 2>/dev/null || true

# Create fresh worktree
echo "2. Creating fresh worktree on branch $BRANCH_NAME..."
git worktree add "$WORKTREE_PATH" -b "$BRANCH_NAME"

# Initialize submodules in worktree
echo "3. Initializing git submodules..."
cd "$WORKTREE_PATH"
git submodule update --init --recursive

# Build the project
echo "4. Building simulator (this may take a minute)..."
cmake -B build -S . -DCMAKE_POLICY_VERSION_MINIMUM=3.5
cmake --build build -j$(sysctl -n hw.ncpu)

# Verify Python module
echo "5. Verifying Python module..."
cd build
python3 -c "import sys; sys.path.insert(0, '.'); import slaythespire; print('Simulator module loaded successfully!')"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Worktree created at: $WORKTREE_PATH"
echo ""
echo "To start a new Claude Code session in this worktree:"
echo ""
echo "    cd $WORKTREE_PATH && claude"
echo ""
echo "Or use dc alias if you have it:"
echo ""
echo "    dc Test manual sync between game and simulator"
echo ""
