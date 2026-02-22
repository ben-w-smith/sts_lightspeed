#!/bin/bash
set -e

echo "=== Setting up worktree properly for manual sync testing ==="

cd /Users/bensmith/development/sts_lightspeed

# Step 1: Commit the current fixes
echo ""
echo "Step 1: Committing fixes..."
git add -A
git commit -m "Fix compilation issues and add manual sync test infrastructure" || echo "Nothing to commit or commit failed"

# Step 2: Create worktree
echo ""
echo "Step 2: Creating worktree..."
WORKTREE_PATH=".worktrees/test-manual-sync"
if [ -d "$WORKTREE_PATH" ]; then
    echo "Worktree already exists, removing..."
    git worktree remove "$WORKTREE_PATH" --force 2>/dev/null || rm -rf "$WORKTREE_PATH"
fi
git worktree add "$WORKTREE_PATH" -b test/manual-sync-verification

# Step 3: Initialize submodules in worktree
echo ""
echo "Step 3: Initializing submodules..."
cd "$WORKTREE_PATH"
git submodule update --init --recursive

# Step 4: Build
echo ""
echo "Step 4: Building..."
cmake -B build -S . -DCMAKE_POLICY_VERSION_MINIMUM=3.5
cmake --build build -j$(sysctl -n hw.ncpu)

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Worktree is ready at: $(pwd)"
echo ""
echo "To start testing, run:"
echo "  cd $(pwd)"
echo "  claude 'Test manual sync between game and simulator for sts_lightspeed'"
